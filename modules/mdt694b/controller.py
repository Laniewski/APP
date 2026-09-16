"""Asynchroniczna obsługa MDT694B poza wątkiem GUI."""

import logging
import math
import time

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from modules.mdt694b.driver import MDT694BDriver

logger = logging.getLogger(__name__)


class MDT694BWorker(QObject):
    connected = Signal()
    disconnected = Signal()
    voltage_updated = Signal(float)
    voltage_range_updated = Signal(float, float)
    busy_changed = Signal(bool)
    ramp_active_changed = Signal(bool)
    error = Signal(str)
    command_error = Signal(str)

    def __init__(
        self,
        driver_factory=MDT694BDriver,
        poll_interval_ms: int = 500,
        ramp_interval_ms: int = 50,
    ) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._poll_interval_ms = poll_interval_ms
        self._driver = None
        self._timer = None
        self._ramp_interval_ms = ramp_interval_ms
        self._ramp_timer = None
        self._voltage_range = None
        self._current_voltage = None
        self._ramp_start_voltage = 0.0
        self._ramp_target_voltage = 0.0
        self._ramp_rate_v_per_s = 0.0
        self._ramp_direction = 0.0
        self._ramp_start_time = 0.0

    @Slot(str)
    def connect_device(self, port: str) -> None:
        self.busy_changed.emit(True)
        self._close_driver()
        try:
            self._driver = self._driver_factory(port)
            self._driver.connect()
            minimum, maximum = self._driver.read_voltage_range()
            voltage = self._driver.read_voltage()
            self._voltage_range = (minimum, maximum)
            self._current_voltage = voltage
            self.voltage_range_updated.emit(minimum, maximum)
            self.voltage_updated.emit(voltage)
            self.connected.emit()
            self._timer = QTimer(self)
            self._timer.setInterval(self._poll_interval_ms)
            self._timer.timeout.connect(self.refresh_voltage)
            self._timer.start()
        except Exception as exc:
            self._fail("Nie udało się połączyć z MDT694B", exc)
        finally:
            self.busy_changed.emit(False)

    @Slot(float)
    def set_voltage(self, value: float) -> None:
        self.busy_changed.emit(True)
        try:
            self._stop_ramp()
            logger.info("MDT694B: zadano %.2f V", value)
            voltage = self._require_driver().set_voltage(value)
            self._current_voltage = voltage
            logger.info("MDT694B: urządzenie zwróciło %.2f V", voltage)
            self.voltage_updated.emit(voltage)
        except Exception as exc:
            self._fail("Nie udało się ustawić napięcia MDT694B", exc)
        finally:
            self.busy_changed.emit(False)

    @Slot()
    def refresh_voltage(self) -> None:
        try:
            voltage = self._require_driver().read_voltage()
            self._current_voltage = voltage
            self.voltage_updated.emit(voltage)
        except Exception as exc:
            self._fail("Nie udało się odczytać napięcia MDT694B", exc)

    @Slot(float, float)
    def start_ramp(self, target_voltage: float, ramp_rate_v_per_s: float) -> None:
        try:
            self._stop_ramp()
            self._require_driver()
            target_voltage = float(target_voltage)
            ramp_rate_v_per_s = float(ramp_rate_v_per_s)
            if not math.isfinite(ramp_rate_v_per_s) or ramp_rate_v_per_s <= 0.0:
                raise ValueError("Prędkość rampy musi być dodatnią, skończoną wartością.")
            if not math.isfinite(target_voltage):
                raise ValueError("Napięcie docelowe musi być skończoną wartością.")
            if self._voltage_range is None:
                self._voltage_range = self._require_driver().read_voltage_range()
            minimum, maximum = self._voltage_range
            if not minimum <= target_voltage <= maximum:
                raise ValueError(
                    f"Napięcie docelowe musi być w zakresie {minimum:.2f}–{maximum:.2f} V."
                )
            if self._current_voltage is None:
                self._current_voltage = self._require_driver().read_voltage()

            self._ramp_start_voltage = float(self._current_voltage)
            self._ramp_target_voltage = target_voltage
            self._ramp_rate_v_per_s = ramp_rate_v_per_s
            delta = target_voltage - self._ramp_start_voltage
            if delta == 0.0:
                self.voltage_updated.emit(self._current_voltage)
                self.ramp_active_changed.emit(False)
                return
            self._ramp_direction = 1.0 if delta > 0.0 else -1.0
            self._ramp_start_time = time.monotonic()
            logger.info(
                "start ramp: %.1f V → %.1f V, %.1f V/s",
                self._ramp_start_voltage,
                target_voltage,
                ramp_rate_v_per_s,
            )
            self._ramp_timer = QTimer(self)
            self._ramp_timer.setInterval(self._ramp_interval_ms)
            self._ramp_timer.timeout.connect(self._ramp_tick)
            self._ramp_timer.start()
            self.ramp_active_changed.emit(True)
        except ValueError as exc:
            self.command_error.emit(str(exc))
        except Exception as exc:
            self._fail("Nie udało się uruchomić rampy MDT694B", exc)

    @Slot()
    def _ramp_tick(self) -> None:
        if self._ramp_timer is None:
            return
        try:
            elapsed = time.monotonic() - self._ramp_start_time
            requested = (
                self._ramp_start_voltage
                + self._ramp_direction * self._ramp_rate_v_per_s * elapsed
            )
            minimum, maximum = self._voltage_range
            requested = min(max(requested, minimum), maximum)
            reached_target = (
                requested >= self._ramp_target_voltage
                if self._ramp_direction > 0.0
                else requested <= self._ramp_target_voltage
            )
            if reached_target:
                requested = self._ramp_target_voltage
            voltage = self._require_driver().set_voltage(requested)
            self._current_voltage = voltage
            self.voltage_updated.emit(voltage)
            if reached_target:
                self._stop_ramp()
                logger.info("ramp finished: actual voltage %.1f V", voltage)
        except Exception as exc:
            self._fail("Błąd rampy napięcia MDT694B", exc)

    @Slot()
    def stop_ramp(self) -> None:
        self._stop_ramp()

    def _stop_ramp(self) -> None:
        was_active = self._ramp_timer is not None
        if self._ramp_timer is not None:
            self._ramp_timer.stop()
            self._ramp_timer.deleteLater()
            self._ramp_timer = None
        if was_active:
            self.ramp_active_changed.emit(False)

    @Slot()
    def disconnect_device(self) -> None:
        self.busy_changed.emit(True)
        try:
            self._close_driver()
            self.disconnected.emit()
        finally:
            self.busy_changed.emit(False)

    def _require_driver(self):
        if self._driver is None:
            raise RuntimeError("MDT694B nie jest połączony.")
        return self._driver

    def _fail(self, context: str, exc: Exception) -> None:
        logger.exception(context)
        self._close_driver()
        self.disconnected.emit()
        self.error.emit(str(exc))

    def _close_driver(self) -> None:
        self._stop_ramp()
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        driver, self._driver = self._driver, None
        self._voltage_range = None
        self._current_voltage = None
        if driver is not None:
            driver.close()

    @Slot()
    def stop(self) -> None:
        self._close_driver()
        QThread.currentThread().quit()


class MDT694BController(QObject):
    request_connect = Signal(str)
    request_disconnect = Signal()
    request_set_voltage = Signal(float)
    request_refresh_voltage = Signal()
    request_start_ramp = Signal(float, float)
    request_stop_ramp = Signal()
    request_stop = Signal()

    def __init__(self, panel, port_manager, worker_factory=MDT694BWorker) -> None:
        super().__init__(panel)
        self.panel = panel
        self.port_manager = port_manager
        self._port = None
        self._connected = False
        self.thread = QThread(self)
        self.worker = worker_factory()
        self.worker.moveToThread(self.thread)
        queued = Qt.ConnectionType.QueuedConnection
        self.request_connect.connect(self.worker.connect_device, queued)
        self.request_disconnect.connect(self.worker.disconnect_device, queued)
        self.request_set_voltage.connect(self.worker.set_voltage, queued)
        self.request_refresh_voltage.connect(self.worker.refresh_voltage, queued)
        self.request_start_ramp.connect(self.worker.start_ramp, queued)
        self.request_stop_ramp.connect(self.worker.stop_ramp, queued)
        self.request_stop.connect(self.worker.stop, queued)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.voltage_updated.connect(panel.show_voltage)
        self.worker.voltage_range_updated.connect(panel.set_voltage_range)
        self.worker.busy_changed.connect(panel.set_busy)
        self.worker.ramp_active_changed.connect(panel.set_ramp_active)
        self.worker.error.connect(self._on_error)
        self.worker.command_error.connect(panel.show_command_error)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        panel.refresh_requested.connect(self.refresh_ports)
        panel.connect_requested.connect(self.connect)
        panel.disconnect_requested.connect(self.disconnect)
        panel.set_voltage_requested.connect(self.set_voltage)
        panel.start_ramp_requested.connect(self.start_ramp)
        panel.stop_ramp_requested.connect(self.stop_ramp)

    @Slot()
    def refresh_ports(self) -> None:
        try:
            self.panel.set_ports(self.port_manager.list_ports())
        except Exception as exc:
            logger.exception("Nie udało się przeskanować portów dla MDT694B")
            self.panel.show_error(str(exc))

    @Slot(str)
    def connect(self, port: str) -> None:
        if not port:
            self.panel.show_error("Wybierz port szeregowy.")
            return
        if not self.port_manager.reserve(port, self):
            self.panel.show_error(f"Port {port} jest już używany.")
            return
        self._port = port
        self.panel.set_busy(True)
        self.request_connect.emit(port)

    @Slot()
    def disconnect(self) -> None:
        self.panel.set_busy(True)
        self.request_disconnect.emit()

    @Slot(float)
    def set_voltage(self, value: float) -> None:
        self.panel.set_busy(True)
        self.request_set_voltage.emit(value)

    @Slot(float, float)
    def start_ramp(self, target_voltage: float, ramp_rate_v_per_s: float) -> None:
        self.request_start_ramp.emit(target_voltage, ramp_rate_v_per_s)

    @Slot()
    def stop_ramp(self) -> None:
        self.request_stop_ramp.emit()

    def is_connected(self) -> bool:
        return self._connected

    @Slot()
    def _on_connected(self) -> None:
        self._connected = True
        self.panel.set_connected(True)

    @Slot()
    def _on_disconnected(self) -> None:
        self._connected = False
        self._release_port()
        self.panel.set_connected(False)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._connected = False
        self._release_port()
        self.panel.set_connected(False)
        self.panel.show_error(message)

    def _release_port(self) -> None:
        if self._port is not None:
            self.port_manager.release(self._port, self)
            self._port = None

    def shutdown(self, timeout_ms: int = 3000) -> None:
        if self.thread.isRunning():
            self.request_stop.emit()
            if not self.thread.wait(timeout_ms):
                logger.error("Wątek MDT694B nie zakończył się w limicie czasu")
                self.thread.quit()
                self.thread.wait(timeout_ms)
        self._release_port()
