"""Koordynacja GUI, lokalnego modelu i runnera poza głównym wątkiem."""

import copy
import logging
import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from .actions import MeasurementActions
from .backend import LLMBackend
from .plan_schema import PlanValidator
from .runner import Runner
from .script_builder import ScriptBuilder

logger = logging.getLogger(__name__)


class _AssistantWorker(QObject):
    status = Signal(str)
    generated = Signal(object)
    completed = Signal(bool)
    error = Signal(str)

    def __init__(self, backend, actions, stop_event):
        super().__init__()
        self.backend, self.actions, self.stop_event = backend, actions, stop_event

    @Slot(str)
    def generate(self, request):
        try:
            if self.stop_event.is_set():
                raise RuntimeError("Generowanie anulowane.")
            self.generated.emit(self.backend.generate(request, self.status.emit, stop_event=self.stop_event))
        except Exception as exc:
            logger.exception("Błąd modelu lokalnego")
            self.error.emit(str(exc))

    @Slot(object)
    def execute(self, job):
        try:
            self.completed.emit(Runner().run(job[0], job[1], self.actions, self.stop_event))
        except Exception as exc:
            self.error.emit(str(exc))


class MeasurementAssistantController(QObject):
    request_generate = Signal(str)
    request_execute = Signal(object)
    procedure_active_changed = Signal(bool)

    def __init__(self, panel, tc200, mdt694b, mpc220, measurement, backend=None):
        super().__init__(panel)
        self.panel = panel
        self.backend = backend or LLMBackend()
        self.actions = MeasurementActions(tc200, mdt694b, mpc220, measurement, self)
        self.stop_event = threading.Event()
        self._plan, self._directory, self._request = None, None, ""
        self._busy = False
        self._executing = False
        self._closing = False
        self.thread = QThread(self)
        self.worker = _AssistantWorker(self.backend, self.actions, self.stop_event)
        self.worker.moveToThread(self.thread)
        self.request_generate.connect(self.worker.generate, Qt.ConnectionType.QueuedConnection)
        self.request_execute.connect(self.worker.execute, Qt.ConnectionType.QueuedConnection)
        self.worker.status.connect(panel.status_label.setText)
        self.worker.generated.connect(self._on_plan)
        self.worker.completed.connect(self._on_completed)
        self.worker.error.connect(self._on_error)
        self.actions.step_started.connect(self._on_step)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        panel.generate_requested.connect(self.generate)
        panel.start_requested.connect(self.start)
        panel.stop_requested.connect(self.stop)

    @Slot()
    def generate(self):
        if self._busy:
            return
        text = self.panel.request_input.toPlainText().strip()
        if not text:
            self.panel.status_label.setText("Podaj opis pomiaru.")
            return
        self._request = text
        self._plan, self._directory = None, None
        self._busy = True
        self.stop_event.clear()
        self.panel.set_busy(True)
        self.request_generate.emit(text)

    @Slot(object)
    def _on_plan(self, plan):
        if self._closing:
            return
        self._busy = False
        if self.stop_event.is_set():
            self.panel.set_busy(False)
            return
        validation = PlanValidator().validate(plan, self._request)
        if validation.missing_parameters and isinstance(plan.get("missing_parameters"), list):
            plan = copy.deepcopy(plan)
            plan["missing_parameters"] = list(validation.missing_parameters)
        self.panel.show_plan(plan, validation)
        self._plan = copy.deepcopy(plan)
        try:
            self._directory = ScriptBuilder().save(
                self.backend.config.runs_dir, self._request, plan,
                llm_response=getattr(self.backend, "last_raw_response", None),
            )
            logger.info("Zapisano plan w %s", self._directory)
            if validation.errors:
                logger.warning("Plan odrzucony: %s", validation.errors)
            if validation.runnable:
                logger.info("Zaakceptowano plan; wygenerowano script.py.")
            self.panel.status_label.setText("Plan gotowy — sprawdź kroki przed rozpoczęciem." if validation.runnable else "Plan wymaga uzupełnienia lub korekty.")
            self.panel.set_busy(False, validation.runnable)
        except Exception as exc:
            self._on_error(str(exc))

    @Slot()
    def start(self):
        if self._busy or self._directory is None or not PlanValidator().validate(self._plan, self._request).runnable:
            return
        self.stop_event.clear()
        self._busy = self._executing = True
        self.panel.set_busy(True)
        self.procedure_active_changed.emit(True)
        self.panel.status_label.setText("Wykonywanie procedury...")
        self.request_execute.emit((self._directory / "script.py", copy.deepcopy(self._plan)))

    @Slot()
    def stop(self):
        self.stop_event.set()
        if self._executing:
            self.actions.cancel()
        else:
            self.backend.cancel()
        self.panel.status_label.setText("Zatrzymywanie...")

    @Slot(str)
    def _on_step(self, name):
        self.panel.status_label.setText(f"Wykonywanie: {name}")

    @Slot(bool)
    def _on_completed(self, completed):
        self._busy = self._executing = False
        self.procedure_active_changed.emit(False)
        self.panel.status_label.setText("Procedura zakończona." if completed else "Procedura zatrzymana.")
        # Ponowne uruchomienie wymaga nowego planu; start ADS nie może skasować sesji przypadkiem.
        self.panel.set_busy(False)

    @Slot(str)
    def _on_error(self, message):
        self._busy = self._executing = False
        self.procedure_active_changed.emit(False)
        self.panel.status_label.setText(f"Błąd: {message}")
        self.panel.set_busy(False)
        logger.error("Asystent pomiaru: %s", message)

    def shutdown(self, timeout_ms=3000):
        self._closing = True
        if self._busy:
            self.stop()
        self.backend.shutdown()
        self.thread.quit()
        if not self.thread.wait(timeout_ms):
            logger.error("Asystent kończy blokującą operację; czekam na bezpieczne zamknięcie.")
            self.thread.wait()
