"""Testy asystenta bez modelu i bez jakiegokolwiek sprzętu."""
import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication
from modules.measurement_assistant.actions import MeasurementActions, ACTION_REGISTRY, ArgumentSpec, ActionSpec
from modules.measurement_assistant.plan_schema import parse_response, PlanValidator, response_schema
from modules.measurement_assistant.script_builder import ScriptBuilder
from modules.measurement_assistant.runner import Runner
from modules.measurement_assistant.panel import MeasurementAssistantPanel
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.action_registry import EXECUTABLE_ACTIONS
from modules.measurement_assistant.controller import MeasurementAssistantController
from pathlib import Path


def plan(action="wait", **args):
    return {"type": "procedure", "answer": "", "steps": [{"action": action, "args": args}]}


def request_for(p):
    templates = {"wait": "Poczekaj {seconds} sekund", "set_temperature": "Ustaw temperaturę na {value_c}",
                 "set_piezo_voltage": "Ustaw piezo na {value_v}",
                 "set_polarization_angle": "Ustaw łopatkę {paddle} na {angle_deg}",
                 "start_measurement": "Rozpocznij pomiar", "stop_measurement": "Zatrzymaj pomiar"}
    return "; ".join(templates[s["action"]].format(**s["args"]) for s in p["steps"])


class Worker(QObject):
    error = Signal(str)
    operation_finished = Signal(str)
    voltage_set = Signal(float)
    angle_set = Signal(int, float)
    started = Signal()
    stopped = Signal()


class FakeController:
    def __init__(self):
        self.worker = Worker()
        self.calls = []
        self.running = False
    def is_connected(self): return True
    def is_optimizing(self): return False
    def is_running(self): return self.running
    def record(self, *args): self.calls.append((threading.get_ident(), args))
    def set_temperature(self, value):
        self.record("temperature", value)
        self.worker.operation_finished.emit("Temperatura ustawiona")
    def set_heater(self, enabled):
        self.record("heater", enabled)
        self.worker.operation_finished.emit("Stan grzania zmieniony")
    def adjust_angle(self, paddle, delta):
        self.record("move", paddle, delta)
        self.worker.angle_set.emit(paddle, 45)
    def set_voltage(self, value):
        self.record("voltage", value)
        self.worker.voltage_set.emit(value)
    def set_angle(self, paddle, angle):
        self.record("angle", paddle, angle)
        self.worker.angle_set.emit(paddle, angle)
    def start_measurement(self):
        self.record("start")
        self.running = True
        self.worker.started.emit()
    def stop_measurement(self):
        self.record("stop")
        self.running = False
        self.worker.stopped.emit()


class AssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


    def test_parser_strict(self):
        for text in ('```json\n{}\n```', '{"title":1,"title":2}', '{"x":NaN}', '[]'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_response(text)

    def test_unknown_action(self):
        self.assertFalse(PlanValidator().validate(plan("execute_python")).runnable)

    def test_valid_plan(self):
        self.assertTrue(PlanValidator().validate(plan(seconds=0)).runnable)


    def test_backend_closed_does_not_restart(self):
        backend = LLMBackend()
        backend.shutdown()
        with patch("modules.measurement_assistant.backend.subprocess.Popen") as spawn:
            with self.assertRaises(RuntimeError): backend.generate("Poczekaj 1 sekundę")
            spawn.assert_not_called()


    def test_controller_plan_only_no_actions(self):
        with tempfile.TemporaryDirectory() as root:
            panel = MeasurementAssistantPanel()
            fake_backend = SimpleNamespace(
                config=AssistantConfig(runs_dir=Path(root)),
                generate=lambda request, status, **kwargs: plan(seconds=0), shutdown=lambda: None)
            devices = [FakeController() for _ in range(4)]
            controller = MeasurementAssistantController(panel, *devices, backend=fake_backend)
            try:
                panel.request_input.setPlainText("Poczekaj 0 sekund")
                panel.generate_button.click()
                deadline = time.monotonic() + 3
                while controller._busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertFalse(controller._busy)
                self.assertFalse(panel.start_button.isEnabled())
                self.assertFalse((controller._directory / "script.py").exists())
                self.assertIn("1. wait", panel.plan_view.toPlainText())
                metrics = json.loads((controller._directory / "metrics.json").read_text())
                self.assertTrue(metrics["valid"])
                self.assertTrue(metrics["runnable"])
                with patch("modules.measurement_assistant.controller.Runner") as runner:
                    controller.start()
                    self.app.processEvents()
                    runner.assert_not_called()
                self.assertTrue(all(not device.calls for device in devices))
            finally:
                controller.shutdown()
                panel.deleteLater()

    def test_wrong_arguments(self):
        for args in ({"seconds": True}, {"seconds": -1}, {"seconds": "1"},
                     {"seconds": 1, "code": "print(1)"}, {}, {"seconds": 10**1000}):
            self.assertFalse(PlanValidator().validate(plan(**args)).runnable)

    def test_missing_information_blocks_builder(self):
        p = plan(seconds=0)
        p["missing_parameters"] = ["Podaj czas stabilizacji i tolerancję"]
        self.assertFalse(PlanValidator().validate(p).runnable)
        with self.assertRaises(ValueError): ScriptBuilder().build(p)
        with tempfile.TemporaryDirectory() as root:
            folder = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            self.assertTrue((folder / "plan.json").exists())
            self.assertFalse((folder / "script.py").exists())


    def test_runner_and_tamper(self):
        calls = []
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            actions = SimpleNamespace(wait=lambda **args: calls.append(args))
            self.assertTrue(Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, actions))
            self.assertEqual(calls, [{"seconds": 0}])
            (directory / "script.py").write_text("raise RuntimeError('bad')")
            with self.assertRaises(ValueError): Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, actions)

    def test_runner_stop(self):
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            self.assertFalse(Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, object(), event))

    def test_runner_failure_cancels_and_logs(self):
        cancelled = []
        def fail(**args): raise RuntimeError("fake failure")
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            fake = SimpleNamespace(wait=fail, cancel=lambda: cancelled.append(True))
            with self.assertRaises(RuntimeError):
                Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, fake)
            self.assertEqual(cancelled, [True])
            self.assertIn("fake failure", (directory / "run.log").read_text())

    def test_panel_rejects_invalid_plan(self):
        panel = MeasurementAssistantPanel()
        p = plan(seconds="bad")
        p["notes"] = 1
        panel.show_plan(p, PlanValidator().validate(p))
        self.assertFalse(panel.start_button.isEnabled())
        panel.deleteLater()

    def test_registry_matches_bridge(self):
        for name in EXECUTABLE_ACTIONS:
            self.assertTrue(callable(getattr(MeasurementActions, name)))

    def test_bridge_dispatches_in_gui_and_waits_for_ack(self):
        controllers = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*controllers, execution_enabled=True)
        p = plan("set_temperature", value_c=25)
        p["steps"] += [plan("set_piezo_voltage", value_v=10)["steps"][0],
                        plan("set_polarization_angle", paddle=1, angle_deg=30)["steps"][0],
                        plan("start_measurement")["steps"][0],
                        plan(seconds=0)["steps"][0], plan("stop_measurement")["steps"][0]]
        result = []
        with tempfile.TemporaryDirectory() as root:
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            def execute():
                try: result.append(Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, actions))
                except Exception as exc: result.append(exc)
            thread = threading.Thread(target=execute)
            thread.start()
            deadline = time.monotonic() + 5
            while thread.is_alive() and time.monotonic() < deadline:
                self.app.processEvents()
                thread.join(.005)
            if thread.is_alive():
                actions.cancel()
                thread.join(1)
            self.assertEqual(result, [True])
        for controller in controllers:
            self.assertTrue(controller.calls)
            self.assertTrue(all(tid == threading.get_ident() for tid, _ in controller.calls))
        actions.deleteLater()

    def test_heater_and_both_paddles_use_acknowledged_adapter(self):
        devices = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*devices, execution_enabled=True)
        result = []
        def execute():
            try:
                actions.heater_on()
                actions.heater_off()
                actions.set_polarization_angle("both", 100)
                actions.move_polarization("both", 5)
                result.append(True)
            except Exception as exc:
                result.append(exc)
        thread = threading.Thread(target=execute)
        thread.start()
        deadline = time.monotonic() + 3
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            thread.join(.005)
        if thread.is_alive():
            actions.cancel()
            thread.join(1)
        self.assertEqual(result, [True])
        self.assertEqual([call for _, call in devices[0].calls], [("heater", True), ("heater", False)])
        self.assertEqual([call for _, call in devices[2].calls], [
            ("angle", 1, 100), ("angle", 2, 100), ("move", 1, 5), ("move", 2, 5)])
        actions.deleteLater()

    def test_answer_and_error_never_enable_execution_or_write_script(self):
        for kind, key in (("answer", "answer"), ("error", "message")):
            with tempfile.TemporaryDirectory() as root:
                value = {"type": kind, key: "Treść dla użytkownika", "steps": []}
                panel = MeasurementAssistantPanel()
                backend = SimpleNamespace(config=AssistantConfig(runs_dir=Path(root), execution_enabled=True),
                                          shutdown=lambda: None)
                devices = [FakeController() for _ in range(4)]
                controller = MeasurementAssistantController(panel, *devices, backend=backend)
                try:
                    controller._on_plan(value)
                    self.assertIn(value[key], panel.plan_view.toPlainText())
                    self.assertFalse(panel.start_button.isEnabled())
                    self.assertFalse((controller._directory / "script.py").exists())
                    controller.start()
                    self.assertTrue(all(not device.calls for device in devices))
                finally:
                    controller.shutdown()
                    panel.deleteLater()

    def test_cancel_does_not_stop_manual_session(self):
        controllers = [FakeController() for _ in range(4)]
        controllers[-1].running = True
        actions = MeasurementActions(*controllers, execution_enabled=True)
        actions.cancel()
        self.app.processEvents()
        self.assertTrue(controllers[-1].running)
        self.assertEqual(controllers[-1].calls, [])
        actions.deleteLater()

    def test_wait_is_cooperatively_stopped(self):
        controllers = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*controllers, execution_enabled=True)
        result = []
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=30)
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            thread = threading.Thread(target=lambda: result.append(
                Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, actions)))
            thread.start()
            time.sleep(.02)
            actions.cancel()
            thread.join(1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [False])
        self.app.processEvents()
        actions.deleteLater()

    def test_next_action_waits_for_delayed_ack(self):
        controllers = [FakeController() for _ in range(4)]
        ack = []
        def set_temperature(value):
            controllers[0].record("temperature", value)
            def complete():
                ack.append(True)
                controllers[0].worker.operation_finished.emit("Temperatura ustawiona")
            QTimer.singleShot(50, complete)
        controllers[0].set_temperature = set_temperature
        def set_voltage(value):
            controllers[1].record("ack_before_voltage", bool(ack))
            controllers[1].worker.voltage_set.emit(value)
        controllers[1].set_voltage = set_voltage
        actions = MeasurementActions(*controllers, execution_enabled=True)
        result = []
        with tempfile.TemporaryDirectory() as root:
            p = plan("set_temperature", value_c=25)
            p["steps"].append(plan("set_piezo_voltage", value_v=10)["steps"][0])
            directory = ScriptBuilder().save(root, request_for(p), p, execution_enabled=True)
            def run():
                try: result.append(Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, actions))
                except Exception as exc: result.append(exc)
            thread = threading.Thread(target=run)
            thread.start()
            deadline = time.monotonic() + 3
            while thread.is_alive() and time.monotonic() < deadline:
                self.app.processEvents()
                thread.join(.005)
            if thread.is_alive():
                actions.cancel()
                thread.join(1)
            self.assertEqual(result, [True])
            self.assertEqual(controllers[1].calls[0][1], ("ack_before_voltage", True))
        actions.deleteLater()

    def test_disabled_runner_and_actions(self):
        devices = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*devices, execution_enabled=False)
        try:
            for name in EXECUTABLE_ACTIONS:
                args = {"set_temperature": {"value_c": 40}, "set_piezo_voltage": {"value_v": 30},
                        "set_polarization_angle": {"paddle": 1, "angle_deg": 30}, "wait": {"seconds": 0}, "move_polarization": {"paddle": "both", "delta_deg": 5}}.get(name, {})
                with self.assertRaisesRegex(RuntimeError, "wyłączony"):
                    getattr(actions, name)(**args)
                request = SimpleNamespace(name=name, args=args, error=None, done=threading.Event())
                actions._dispatch(request)
                self.assertTrue(request.done.is_set())
                self.assertIn("wyłączony", request.error)
            actions._owns_measurement = True
            actions.cancel()
            self.app.processEvents()
            with self.assertRaisesRegex(RuntimeError, "wyłączony"):
                Runner(AssistantConfig()).run("nonexistent", plan(seconds=0), actions)
            self.assertTrue(all(not device.calls for device in devices))
        finally:
            actions.deleteLater()

    def test_execution_environment(self):
        with patch.dict(os.environ, {"APP_AI_EXECUTION_ENABLED": "0"}):
            self.assertFalse(AssistantConfig.from_env().execution_enabled)
        with patch.dict(os.environ, {"APP_AI_EXECUTION_ENABLED": "1"}):
            self.assertTrue(AssistantConfig.from_env().execution_enabled)
        with patch.dict(os.environ, {"APP_AI_EXECUTION_ENABLED": "maybe"}):
            with self.assertRaises(ValueError): AssistantConfig.from_env()

    def test_generation_parameters_and_schema_formats(self):
        for nested in (True, False):
            backend = LLMBackend(AssistantConfig(schema_in_response_format=nested))
            response = {"choices": [{"message": {"content": json.dumps({"steps": [{"id": 0, "action": "wait", "args": {"seconds": 0}}]})}}]}
            with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", return_value=response) as call:
                backend.generate("Poczekaj 0 sekund")
                payload = call.call_args.args[2]
                self.assertEqual(payload["max_tokens"], 2048)
                self.assertEqual(payload["temperature"], 0.0)
                self.assertEqual("schema" in payload["response_format"], nested)
                self.assertEqual("json_schema" in payload, not nested)

    def test_external_server_not_spawned_or_killed(self):
        backend = LLMBackend()
        with patch.object(backend, "_request", return_value={"status": "ok"}), patch("modules.measurement_assistant.backend.subprocess.Popen") as spawn:
            backend.ensure_ready(lambda message: None)
            backend.shutdown()
            spawn.assert_not_called()
            self.assertIsNone(backend._process)

    def test_owned_server_start_and_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            binary, model = Path(root) / "server", Path(root) / "model.gguf"
            binary.touch(); model.touch()
            backend = LLMBackend(AssistantConfig(binary=binary, model=model))
            process = Mock()
            process.poll.return_value = None
            with patch.object(backend, "_port_in_use", return_value=False), patch.object(backend, "is_ready", side_effect=[False, True]), patch("modules.measurement_assistant.backend.subprocess.Popen", return_value=process) as spawn:
                backend.ensure_ready(lambda message: None)
                command = spawn.call_args.args[0]
                self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
                self.assertEqual(command[command.index("-c") + 1], "16384")
                self.assertEqual(command[command.index("--parallel") + 1], "1")
                backend.shutdown()
                process.terminate.assert_called_once()
                process.wait.assert_called_once()
                self.assertIsNone(backend._server_log)

    def test_invalid_json_logged_and_not_runnable(self):
        with tempfile.TemporaryDirectory() as root:
            panel = MeasurementAssistantPanel()
            backend = LLMBackend(AssistantConfig(runs_dir=Path(root)))
            devices = [FakeController() for _ in range(4)]
            controller = MeasurementAssistantController(panel, *devices, backend=backend)
            try:
                response = {"choices": [{"message": {"content": "invalid JSON"}}], "usage": {"completion_tokens": 2}}
                with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", return_value=response) as call:
                    panel.request_input.setPlainText("Rozpocznij pomiar")
                    controller.generate()
                    deadline = time.monotonic() + 3
                    while controller._busy and time.monotonic() < deadline:
                        self.app.processEvents()
                        time.sleep(.005)
                    self.assertFalse(controller._busy)
                    self.assertEqual(call.call_count, 1)
                folder = controller._directory
                self.assertEqual((folder / "llm_response.json").read_text(), "invalid JSON")
                metrics = json.loads((folder / "metrics.json").read_text())
                self.assertFalse(metrics["valid"])
                self.assertFalse(metrics["runnable"])
                self.assertTrue(metrics["validation_errors"])
                self.assertFalse(panel.start_button.isEnabled())
                self.assertFalse((folder / "script.py").exists())
                panel.copy_button.click()
                self.assertEqual(self.app.clipboard().text(), "invalid JSON")
                self.assertTrue(all(not device.calls for device in devices))
            finally:
                controller.shutdown()
                panel.deleteLater()

    def test_examples_only_insert_text(self):
        panel = MeasurementAssistantPanel()
        generated = []
        panel.generate_requested.connect(lambda: generated.append(True))
        panel.examples.activated.emit(1)
        self.assertEqual(panel.request_input.toPlainText(), panel.examples.itemText(1))
        self.assertEqual(generated, [])
        panel.deleteLater()

    def test_generation_keeps_gui_responsive(self):
        with tempfile.TemporaryDirectory() as root:
            panel = MeasurementAssistantPanel()
            entered, release = threading.Event(), threading.Event()
            worker_threads = []
            def generate(request, status, **kwargs):
                worker_threads.append(threading.get_ident())
                status("Ładowanie modelu...")
                entered.set()
                release.wait(2)
                status("Model gotowy")
                return plan(seconds=0)
            backend = SimpleNamespace(config=AssistantConfig(runs_dir=Path(root)),
                                      generate=generate, shutdown=lambda: release.set())
            controller = MeasurementAssistantController(panel, *[FakeController() for _ in range(4)], backend=backend)
            try:
                panel.request_input.setPlainText("Poczekaj 0 sekund")
                controller.generate()
                self.assertTrue(entered.wait(1))
                tick = []
                QTimer.singleShot(0, lambda: tick.append(True))
                self.app.processEvents()
                self.assertEqual(tick, [True])
                self.assertTrue(controller._busy)
                self.assertTrue((controller._directory / "request.txt").exists())
                self.assertFalse(json.loads((controller._directory / "metrics.json").read_text())["runnable"])
                self.assertNotEqual(worker_threads, [threading.get_ident()])
                release.set()
                deadline = time.monotonic() + 2
                while controller._busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.005)
                self.assertFalse(controller._busy)
            finally:
                release.set()
                controller.shutdown()
                panel.deleteLater()

    def test_rejected_and_missing_plans_metrics(self):
        for p in (plan("unknown"), dict(plan(seconds=0), missing_parameters=["Podaj parametr"])):
            with tempfile.TemporaryDirectory() as root:
                validation = PlanValidator().validate(p)
                folder = ScriptBuilder().save(root, "Poczekaj 0 sekund", p, validation=validation)
                metrics = json.loads((folder / "metrics.json").read_text())
                self.assertEqual(metrics["valid"], not bool(validation.errors))
                self.assertFalse(metrics["runnable"])
                self.assertEqual(metrics["missing_parameters_count"], len(validation.missing_parameters))
                self.assertFalse((folder / "script.py").exists())

    def test_worker_disabled_execution_never_constructs_runner(self):
        from modules.measurement_assistant.controller import _AssistantWorker
        worker = _AssistantWorker(SimpleNamespace(config=AssistantConfig()), object(), threading.Event())
        errors = []
        worker.error.connect(errors.append)
        with patch("modules.measurement_assistant.controller.Runner") as runner:
            worker.execute((Path("nonexistent"), plan(seconds=0)))
            runner.assert_not_called()
        self.assertTrue(errors)

    def test_external_loading_server_not_duplicated(self):
        backend = LLMBackend(AssistantConfig(binary=Path("missing"), model=Path("missing")))
        with patch.object(backend, "_port_in_use", return_value=True), patch.object(backend, "is_ready", side_effect=[False, True]), patch("modules.measurement_assistant.backend.subprocess.Popen") as spawn:
            backend.ensure_ready(lambda message: None)
            backend.shutdown()
            spawn.assert_not_called()
            self.assertIsNone(backend._process)
