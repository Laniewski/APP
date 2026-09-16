"""Testy asystenta bez modelu i bez jakiegokolwiek sprzętu."""
import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication
from modules.measurement_assistant.actions import MeasurementActions, ACTION_REGISTRY
from modules.measurement_assistant.plan_schema import parse_response, PlanValidator
from modules.measurement_assistant.script_builder import ScriptBuilder
from modules.measurement_assistant.runner import Runner
from modules.measurement_assistant.panel import MeasurementAssistantPanel
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.controller import MeasurementAssistantController
from pathlib import Path


def plan(action="wait", **args):
    return {"title": "Test", "steps": [{"description": "Krok", "action": action,
            "args": args}], "missing_parameters": [], "notes": []}


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

    def test_unsupported_stabilization_cannot_be_declared_runnable(self):
        p = plan(seconds=10)
        result = PlanValidator().validate(p, "Poczekaj aż temperatura się ustabilizuje")
        self.assertFalse(result.runnable)
        self.assertTrue(result.missing_parameters)
        self.assertTrue(PlanValidator().validate(p, "Poczekaj 10 sekund").runnable)

    def test_backend_blocks_hallucinated_stabilization(self):
        backend = LLMBackend()
        response = {"choices": [{"message": {"content": json.dumps(plan(seconds=10))}}]}
        with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", return_value=response):
            p = backend.generate("Poczekaj aż temperatura się ustabilizuje")
        self.assertFalse(PlanValidator().validate(p).runnable)
        with self.assertRaises(ValueError): ScriptBuilder().build(p)

    def test_guessed_stabilization_wait_is_rejected_not_corrected(self):
        backend = LLMBackend()
        p = plan("set_temperature", value_c=40)
        guessed = plan(seconds=10)["steps"][0]
        guessed["description"] = "Poczekaj aż się ustabilizuje"
        p["steps"].append(guessed)
        raw = json.dumps(p)
        response = {"choices": [{"message": {"content": raw}}]}
        with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", return_value=response):
            normalized = backend.generate("Ustaw 40 stopni i poczekaj aż się ustabilizuje")
        self.assertEqual(len(normalized["steps"]), 1)
        self.assertEqual(backend.last_raw_response, raw)
        self.assertFalse(PlanValidator().validate(normalized).runnable)

    def test_backend_closed_does_not_restart(self):
        backend = LLMBackend()
        backend.shutdown()
        with patch("modules.measurement_assistant.backend.subprocess.Popen") as spawn:
            with self.assertRaises(RuntimeError): backend.generate("Poczekaj 1 sekundę")
            spawn.assert_not_called()

    def test_backend_parser_retries_once(self):
        backend = LLMBackend()
        responses = [{"choices": [{"message": {"content": "bad"}}]},
                     {"choices": [{"message": {"content": json.dumps(plan(seconds=1))}}]}]
        with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", side_effect=responses) as call:
            self.assertEqual(backend.generate("Poczekaj 1 sekundę"), plan(seconds=1))
            self.assertEqual(call.call_count, 2)

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
                self.assertTrue(panel.start_button.isEnabled())
                self.assertTrue((controller._directory / "script.py").is_file())
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
            folder = ScriptBuilder().save(root, "request", p)
            self.assertTrue((folder / "plan.json").exists())
            self.assertFalse((folder / "script.py").exists())

    def test_builder_ignores_text_code(self):
        p = plan(seconds=0)
        p["steps"][0]["description"] = "__import__('os').system('bad')"
        source = ScriptBuilder().build(p)
        self.assertNotIn("__import__", source)
        self.assertIn("actions.wait(seconds=0)", source)

    def test_runner_and_tamper(self):
        calls = []
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, "request", p)
            actions = SimpleNamespace(wait=lambda **args: calls.append(args))
            self.assertTrue(Runner().run(directory / "script.py", p, actions))
            self.assertEqual(calls, [{"seconds": 0}])
            (directory / "script.py").write_text("raise RuntimeError('bad')")
            with self.assertRaises(ValueError): Runner().run(directory / "script.py", p, actions)

    def test_runner_stop(self):
        event = threading.Event()
        event.set()
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, "request", p)
            self.assertFalse(Runner().run(directory / "script.py", p, object(), event))

    def test_runner_failure_cancels_and_logs(self):
        cancelled = []
        def fail(**args): raise RuntimeError("fake failure")
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, "fake only", p)
            fake = SimpleNamespace(wait=fail, cancel=lambda: cancelled.append(True))
            with self.assertRaises(RuntimeError):
                Runner().run(directory / "script.py", p, fake)
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
        for name in ACTION_REGISTRY:
            self.assertTrue(callable(getattr(MeasurementActions, name)))

    def test_bridge_dispatches_in_gui_and_waits_for_ack(self):
        controllers = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*controllers)
        p = plan("set_temperature", value_c=25)
        p["steps"] += [plan("set_piezo_voltage", value_v=10)["steps"][0],
                        plan("set_polarization_angle", paddle=1, angle_deg=30)["steps"][0],
                        plan("start_measurement")["steps"][0],
                        plan(seconds=0)["steps"][0], plan("stop_measurement")["steps"][0]]
        result = []
        with tempfile.TemporaryDirectory() as root:
            directory = ScriptBuilder().save(root, "fake only", p)
            def execute():
                try: result.append(Runner().run(directory / "script.py", p, actions))
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

    def test_cancel_does_not_stop_manual_session(self):
        controllers = [FakeController() for _ in range(4)]
        controllers[-1].running = True
        actions = MeasurementActions(*controllers)
        actions.cancel()
        self.app.processEvents()
        self.assertTrue(controllers[-1].running)
        self.assertEqual(controllers[-1].calls, [])
        actions.deleteLater()

    def test_wait_is_cooperatively_stopped(self):
        controllers = [FakeController() for _ in range(4)]
        actions = MeasurementActions(*controllers)
        result = []
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=30)
            directory = ScriptBuilder().save(root, "fake only", p)
            thread = threading.Thread(target=lambda: result.append(
                Runner().run(directory / "script.py", p, actions)))
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
        actions = MeasurementActions(*controllers)
        result = []
        with tempfile.TemporaryDirectory() as root:
            p = plan("set_temperature", value_c=25)
            p["steps"].append(plan("set_piezo_voltage", value_v=10)["steps"][0])
            directory = ScriptBuilder().save(root, "fake only", p)
            def run():
                try: result.append(Runner().run(directory / "script.py", p, actions))
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
