"""Rejestr AI i jedyny most automatyzacji do publicznych API kontrolerów."""

import logging
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal, Slot, QThread

from modules.tc200.driver import TC200Driver
from modules.mpc220.calibration import MPC_MIN_ANGLE_DEG, MPC_MAX_ANGLE_DEG

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArgumentSpec:
    kind: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()

    def schema(self):
        result = {"type": self.kind, "description": self.description}
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.choices:
            result["enum"] = list(self.choices)
        return result


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    arguments: dict[str, ArgumentSpec] = field(default_factory=dict)


ACTION_REGISTRY = {
    spec.name: spec for spec in (
        ActionSpec("set_temperature", "Ustaw temperaturę zadaną TC200; nie włącza grzałki ani nie czeka na stabilizację.", {
            "value_c": ArgumentSpec("number", "Temperatura zadana w °C", TC200Driver.MIN_TEMPERATURE, TC200Driver.MAX_TEMPERATURE),
        }),
        ActionSpec("set_piezo_voltage", "Ustaw napięcie piezo MDT694B; zakres sprawdza istniejący sterownik.", {
            "value_v": ArgumentSpec("number", "Napięcie w V"),
        }),
        ActionSpec("set_polarization_angle", "Ustaw kąt jednej łopatki MPC220 i poczekaj na zakończenie ruchu.", {
            "paddle": ArgumentSpec("integer", "Numer łopatki", choices=(1, 2)),
            "angle_deg": ArgumentSpec("number", "Kąt w stopniach", MPC_MIN_ANGLE_DEG, MPC_MAX_ANGLE_DEG),
        }),
        ActionSpec("start_measurement", "Rozpocznij ADS1263 z kanałami wybranymi w GUI."),
        ActionSpec("stop_measurement", "Zatrzymaj ADS1263; dane pozostają w buforze."),
        ActionSpec("wait", "Poczekaj podaną liczbę sekund; nie jest to detekcja stabilizacji.", {
            "seconds": ArgumentSpec("number", "Jawnie podany czas oczekiwania", 0, 3600),
        }),
    )
}


class ActionStopped(RuntimeError):
    pass


@dataclass
class _Request:
    name: str
    args: dict
    done: threading.Event = field(default_factory=threading.Event)
    error: str | None = None


class MeasurementActions(QObject):
    requested = Signal(object)
    cancel_requested = Signal()
    step_started = Signal(str)

    def __init__(self, tc200, mdt694b, mpc220, measurement, parent=None):
        super().__init__(parent)
        self.tc200, self.mdt694b = tc200, mdt694b
        self.mpc220, self.measurement = mpc220, measurement
        self.stop_event = threading.Event()
        self._pending = None
        self._owns_measurement = False
        self.requested.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        self.cancel_requested.connect(self._cancel_devices, Qt.ConnectionType.QueuedConnection)
        tc200.worker.operation_finished.connect(self._temperature_done)
        mdt694b.worker.voltage_set.connect(self._voltage_done)
        mpc220.worker.angle_set.connect(self._angle_done)
        measurement.worker.started.connect(self._measurement_started)
        measurement.worker.stopped.connect(self._measurement_stopped)
        for controller in (tc200, mdt694b, mpc220, measurement):
            controller.worker.error.connect(self._error)

    def prepare(self, stop_event):
        self.stop_event = stop_event

    def _invoke(self, name, **args):
        if QThread.currentThread() == self.thread():
            raise RuntimeError("Akcje blokujące wolno wykonywać tylko w workerze runnera.")
        if self.stop_event.is_set():
            raise ActionStopped("Procedura zatrzymana.")
        self.step_started.emit(name)
        logger.info("Asystent: krok %s %s", name, args)
        if name == "wait":
            if self.stop_event.wait(args["seconds"]):
                raise ActionStopped("Procedura zatrzymana.")
            return
        request = _Request(name, args)
        self.requested.emit(request)
        deadline = time.monotonic() + 30
        while not request.done.wait(0.05):
            if self.stop_event.is_set():
                raise ActionStopped("Procedura zatrzymana.")
            if time.monotonic() >= deadline:
                self.cancel()
                raise TimeoutError(f"Brak potwierdzenia zakończenia {name}.")
        if request.error:
            raise RuntimeError(request.error)

    def set_temperature(self, value_c):
        self._invoke("set_temperature", value_c=value_c)

    def set_piezo_voltage(self, value_v):
        self._invoke("set_piezo_voltage", value_v=value_v)

    def set_polarization_angle(self, paddle, angle_deg):
        self._invoke("set_polarization_angle", paddle=paddle, angle_deg=angle_deg)

    def start_measurement(self):
        self._invoke("start_measurement")

    def stop_measurement(self):
        self._invoke("stop_measurement")

    def wait(self, seconds):
        self._invoke("wait", seconds=seconds)

    @Slot(object)
    def _dispatch(self, request):
        if self.stop_event.is_set():
            request.error = "Procedura zatrzymana."
            request.done.set()
            return
        if self._pending is not None:
            request.error = "Poprzednia operacja nie została zakończona."
            request.done.set()
            return
        self._pending = request
        try:
            if self.mpc220.is_optimizing():
                raise RuntimeError("Zatrzymaj optymalizację polaryzacji przed procedurą.")
            if request.name == "set_temperature":
                if not self.tc200.is_connected():
                    raise RuntimeError("TC200 odłączony.")
                self.tc200.set_temperature(request.args["value_c"])
            elif request.name == "set_piezo_voltage":
                if not self.mdt694b.is_connected():
                    raise RuntimeError("MDT694B odłączony.")
                self.mdt694b.set_voltage(request.args["value_v"])
            elif request.name == "set_polarization_angle":
                if not self.mpc220.is_connected():
                    raise RuntimeError("MPC220 odłączony.")
                self.mpc220.set_angle(request.args["paddle"], request.args["angle_deg"])
            elif request.name == "start_measurement":
                if self.measurement.is_running():
                    raise RuntimeError("Pomiar już działa; nie nadpiszę jego bufora.")
                self._owns_measurement = True
                self.measurement.start_measurement()
            elif request.name == "stop_measurement":
                if not self.measurement.is_running():
                    self._finish()
                else:
                    self.measurement.stop_measurement()
            else:
                raise ValueError("Nieznana akcja.")
        except Exception as exc:
            self._finish(str(exc))

    def _finish(self, error=None):
        request, self._pending = self._pending, None
        if request:
            request.error = error
            request.done.set()

    @Slot(str)
    def _temperature_done(self, message):
        if self._pending and self._pending.name == "set_temperature" and message == "Temperatura ustawiona":
            self._finish()

    @Slot(float)
    def _voltage_done(self, _voltage):
        if self._pending and self._pending.name == "set_piezo_voltage":
            self._finish()

    @Slot(int, float)
    def _angle_done(self, paddle, _angle):
        if self._pending and self._pending.name == "set_polarization_angle" and self._pending.args["paddle"] == paddle:
            self._finish()

    @Slot()
    def _measurement_started(self):
        if self._pending and self._pending.name == "start_measurement":
            self._owns_measurement = True
            self._finish()

    @Slot()
    def _measurement_stopped(self):
        self._owns_measurement = False
        if self._pending and self._pending.name == "stop_measurement":
            self._finish()

    @Slot(str)
    def _error(self, message):
        if self._pending:
            self._finish(message)

    def cancel(self):
        self.stop_event.set()
        self.cancel_requested.emit()

    @Slot()
    def _cancel_devices(self):
        self._finish("Procedura zatrzymana.")
        if self._owns_measurement:
            self.measurement.stop_measurement()
