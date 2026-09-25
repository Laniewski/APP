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
from modules.measurement_assistant.backend import LLMBackend, system_prompt
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

    def test_system_prompt_preserves_incomplete_actions(self):
        from modules.measurement_assistant.context_builder import tool_definitions, planning_examples
        prompt = system_prompt()
        self.assertIn("brakujący wymagany argument zwróć jako null", prompt)
        self.assertIn("Nie pomijaj niekompletnej akcji", prompt)
        self.assertIn("NIE są wartościami domyślnymi", prompt)
        self.assertIn("Nie decyduj, że plan jest runnable", prompt)
        self.assertEqual([t["name"] for t in tool_definitions()], list(ACTION_REGISTRY))
        self.assertEqual(len(planning_examples()), 5)
        for alias in ("płytka piezo", "nastawnik polaryzacji", "pierwsza", "drugi"):
            self.assertIn(alias, prompt)
        self.assertIn('"angle_deg":null', prompt)
        self.assertIn('"value_v":null', prompt)

    def test_required_null_is_incomplete_not_invalid(self):
        cases = [
            ("Ustaw piezo.", plan("set_piezo_voltage", value_v=None), "Podaj napięcie piezo."),
            ("Ustaw drugą łopatkę.", plan("set_polarization_angle", paddle=2, angle_deg=None), "Podaj kąt drugiej łopatki."),
            ("Ustaw temperaturę.", plan("set_temperature", value_c=None), "Podaj temperaturę zadaną."),
        ]
        for request, p, question in cases:
            with self.subTest(request=request):
                result = PlanValidator().validate(p, request)
                self.assertTrue(result.structurally_valid)
                self.assertEqual(result.errors, ())
                self.assertEqual(result.status, "INCOMPLETE")
                self.assertFalse(result.runnable)
                self.assertIn(question, " ".join(result.missing_parameters))
                self.assertEqual(p["missing_parameters"], [])
                with self.assertRaises(ValueError):
                    ScriptBuilder().build(p)
                with tempfile.TemporaryDirectory() as root:
                    folder = ScriptBuilder().save(root, request, p, execution_enabled=True)
                    self.assertFalse((folder / "script.py").exists())
                    metrics = json.loads((folder / "metrics.json").read_text())
                    self.assertTrue(metrics["valid"])
                    self.assertFalse(metrics["runnable"])
                    self.assertEqual(metrics["missing_parameters_count"], 1)

    def test_complete_numeric_plan_is_not_natural_language_parsed(self):
        for angle in (30, 90):
            result = PlanValidator().validate(plan("set_polarization_angle", paddle=2, angle_deg=angle),
                                               "Ustaw drugą łopatkę.")
            self.assertEqual(result.status, "COMPLETE")
            self.assertTrue(result.runnable)

    def test_nullable_optional_and_nonnullable_arguments(self):
        spec = ActionSpec("test_optional", "Test", {
            "required": ArgumentSpec("number", "Wymagany", question="Podaj wymagany argument."),
            "optional": ArgumentSpec("number", "Opcjonalny", required=False),
            "strict": ArgumentSpec("integer", "Bez null", nullable=False),
        })
        with patch.dict(ACTION_REGISTRY, {spec.name: spec}):
            for args in ({"required": 1, "strict": 2}, {"required": 1, "strict": 2, "optional": None}):
                self.assertTrue(PlanValidator().validate(plan(spec.name, **args)).runnable)
            result = PlanValidator().validate(plan(spec.name, required=None, strict=2, optional=None))
            self.assertEqual(result.status, "INCOMPLETE")
            self.assertEqual(len(result.missing_parameters), 1)
            self.assertEqual(PlanValidator().validate(plan(spec.name, required=1, strict=None)).status, "INVALID")
            self.assertEqual(PlanValidator().validate(plan(spec.name, strict=2)).status, "INVALID")

    def test_null_schema_and_empty_plan_are_consistent(self):
        schema = response_schema()
        self.assertEqual(schema["properties"]["steps"]["minItems"], 0)
        for variant in schema["properties"]["steps"]["items"]["oneOf"]:
            spec = ACTION_REGISTRY[variant["properties"]["action"]["const"]]
            for key, arg in spec.arguments.items():
                self.assertIn("null", variant["properties"]["args"]["properties"][key]["type"])
                if arg.choices:
                    self.assertIn(None, variant["properties"]["args"]["properties"][key]["enum"])
        p = {"title": "Test", "steps": [], "missing_parameters": [], "notes": []}
        result = PlanValidator().validate(p)
        self.assertTrue(result.structurally_valid)
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertFalse(result.runnable)

    def test_invalid_plan_remains_invalid(self):
        for p in (plan("unknown"), plan("set_polarization_angle", paddle=3, angle_deg=30),
                  plan("set_polarization_angle", paddle=2, angle_deg=200),
                  plan("set_polarization_angle", paddle=2, angle_deg="30"),
                  plan("set_polarization_angle", paddle=2, angle_deg=None, extra=1),
                  dict(plan(seconds=1), extra=True)):
            with self.subTest(p=p):
                result = PlanValidator().validate(p)
                self.assertEqual(result.status, "INVALID")
                self.assertFalse(result.runnable)

    def test_piezo_without_unit_remains_an_observed_model_decision(self):
        # No language parser or assumed voltage is introduced in validation.
        result = PlanValidator().validate(plan("set_piezo_voltage", value_v=10), "Ustaw piezo na 10.")
        self.assertTrue(result.runnable)
        self.assertIn("Nie zgaduj jednostek", system_prompt())

    def test_controller_uses_deterministic_missing_parameters(self):
        with tempfile.TemporaryDirectory() as root:
            panel = MeasurementAssistantPanel()
            backend = SimpleNamespace(config=AssistantConfig(runs_dir=Path(root), execution_enabled=True),
                                      shutdown=lambda: None)
            devices = [FakeController() for _ in range(4)]
            controller = MeasurementAssistantController(panel, *devices, backend=backend)
            try:
                controller._request = "Ustaw drugą łopatkę."
                controller._on_plan(plan("set_polarization_angle", paddle=2, angle_deg=None))
                self.assertIn("Podaj kąt drugiej łopatki.", " ".join(controller._plan["missing_parameters"]))
                self.assertFalse(panel.start_button.isEnabled())
                self.assertFalse((controller._directory / "script.py").exists())
                controller.start()
                self.assertTrue(all(not device.calls for device in devices))
            finally:
                controller.shutdown()
                panel.deleteLater()

    def test_malformed_selector_with_null_never_crashes_validator(self):
        p = plan("set_polarization_angle", paddle=[], angle_deg=None)
        result = PlanValidator().validate(p)
        self.assertEqual(result.status, "INVALID")
        self.assertTrue(result.errors)
        self.assertTrue(result.missing_parameters)
        self.assertFalse(result.runnable)

    def test_benchmark_counts_validator_derived_missing_questions(self):
        from tests_x.benchmark_measurement_assistant_models import evaluate
        p = plan("set_piezo_voltage", value_v=None)
        missing = PlanValidator().validate(p).missing_parameters
        score = evaluate(p, [("set_piezo_voltage", {"value_v": None})], missing)
        self.assertTrue(score["correct_actions"])
        self.assertTrue(score["correct_parameters"])
        self.assertTrue(score["missing_detected"])
        self.assertFalse(score["hallucinated_parameter"])
        score = evaluate(plan("set_polarization_angle", paddle=2, angle_deg=35),
                         [("set_polarization_angle", {"paddle": 2, "angle_deg": None})], ())
        self.assertFalse(score["correct_parameters"])
        self.assertFalse(score["missing_detected"])
        self.assertTrue(score["hallucinated_parameter"])

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
                self.assertFalse(panel.start_button.isEnabled())
                self.assertFalse((controller._directory / "script.py").exists())
                self.assertIn("1. Krok", panel.plan_view.toPlainText())
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
            folder = ScriptBuilder().save(root, "request", p, execution_enabled=True)
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
            directory = ScriptBuilder().save(root, "request", p, execution_enabled=True)
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
            directory = ScriptBuilder().save(root, "request", p, execution_enabled=True)
            self.assertFalse(Runner(AssistantConfig(execution_enabled=True)).run(directory / "script.py", p, object(), event))

    def test_runner_failure_cancels_and_logs(self):
        cancelled = []
        def fail(**args): raise RuntimeError("fake failure")
        with tempfile.TemporaryDirectory() as root:
            p = plan(seconds=0)
            directory = ScriptBuilder().save(root, "fake only", p, execution_enabled=True)
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
        for name in ACTION_REGISTRY:
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
            directory = ScriptBuilder().save(root, "fake only", p, execution_enabled=True)
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
            directory = ScriptBuilder().save(root, "fake only", p, execution_enabled=True)
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
            directory = ScriptBuilder().save(root, "fake only", p, execution_enabled=True)
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
            for name in ACTION_REGISTRY:
                args = {"set_temperature": {"value_c": 40}, "set_piezo_voltage": {"value_v": 30},
                        "set_polarization_angle": {"paddle": 1, "angle_deg": 30}, "wait": {"seconds": 0}}.get(name, {})
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
            response = {"choices": [{"message": {"content": json.dumps(plan(seconds=0))}}]}
            with patch.object(backend, "ensure_ready"), patch.object(backend, "_request", return_value=response) as call:
                backend.generate("Poczekaj 0 sekund")
                payload = call.call_args.args[2]
                self.assertEqual(payload["max_tokens"], 400)
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
                self.assertEqual(command[command.index("-c") + 1], "2048")
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
                    self.assertEqual(call.call_count, 2)
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
                folder = ScriptBuilder().save(root, "test", p, validation=validation)
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
