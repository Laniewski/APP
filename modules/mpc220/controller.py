"""Kontroler MPC220 i worker będący jedynym właścicielem drivera."""

import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from modules.mpc220.calibration import (angle_to_command, calculate_target_angle,
                                        clamp_angle, raw_position_to_angle)
from modules.mpc220.driver import MPC220Driver

logger = logging.getLogger(__name__)


class MPC220Worker(QObject):
    connected = Signal()
    disconnected = Signal()
    position_updated = Signal(int, float)
    busy_changed = Signal(bool)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, driver_factory=MPC220Driver) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._driver = None

    @Slot(str)
    def connect_device(self, port: str) -> None:
        self.busy_changed.emit(True)
        self._close_driver()
        try:
            self._driver = self._driver_factory(port)
            self._driver.connect()
            positions = [self._read_angle(paddle) for paddle in (1, 2)]
            self.connected.emit()
            for paddle, angle in enumerate(positions, 1):
                self.position_updated.emit(paddle, angle)
        except Exception as exc:
            self._communication_error("Nie udało się połączyć z MPC220", exc)
        finally:
            self.busy_changed.emit(False)

    @Slot()
    def disconnect_device(self) -> None:
        self.busy_changed.emit(True)
        try:
            self._close_driver()
            self.disconnected.emit()
        finally:
            self.busy_changed.emit(False)

    @Slot(int, float)
    def set_angle(self, paddle_number: int, angle_deg: float) -> None:
        try:
            self._move_to_angle(paddle_number, clamp_angle(angle_deg))
        except Exception as exc:
            self._communication_error("Nie udało się ustawić kąta MPC220", exc)

    @Slot(int, float)
    def adjust_angle(self, paddle_number: int, delta_deg: float) -> None:
        self.busy_changed.emit(True)
        try:
            current = self._read_angle(paddle_number)
            self._move_to_angle(
                paddle_number, calculate_target_angle(current, delta_deg),
                manage_busy=False,
            )
        except Exception as exc:
            self._communication_error("Nie udało się zmienić kąta MPC220", exc)
        finally:
            self.busy_changed.emit(False)

    def _move_to_angle(self, paddle_number: int, angle_deg: float,
                       manage_busy: bool = True) -> None:
        if manage_busy:
            self.busy_changed.emit(True)
        try:
            driver = self._require_driver()
            driver.move_absolute_units(paddle_number, angle_to_command(angle_deg))
            driver.wait_until_stopped(paddle_number)
            self.position_updated.emit(paddle_number, self._read_angle(paddle_number))
        finally:
            if manage_busy:
                self.busy_changed.emit(False)

    def _read_angle(self, paddle_number: int) -> float:
        raw = self._require_driver().read_position_units(paddle_number)
        return clamp_angle(raw_position_to_angle(raw))

    def _require_driver(self):
        if self._driver is None:
            raise RuntimeError("MPC220 nie jest połączony.")
        return self._driver

    def _communication_error(self, context: str, exc: Exception) -> None:
        logger.exception(context)
        self._close_driver()
        self.disconnected.emit()
        self.error.emit(str(exc))

    def _close_driver(self) -> None:
        driver, self._driver = self._driver, None
        if driver is not None:
            driver.close()

    @Slot()
    def stop(self) -> None:
        self._close_driver()
        self.stopped.emit()
        QThread.currentThread().quit()


class MPC220Controller(QObject):
    request_connect = Signal(str)
    request_disconnect = Signal()
    request_set_angle = Signal(int, float)
    request_adjust_angle = Signal(int, float)
    request_stop = Signal()

    def __init__(self, panel, port_manager, worker_factory=MPC220Worker) -> None:
        super().__init__(panel)
        self.panel = panel
        self.port_manager = port_manager
        self._port = None
        self.thread = QThread(self)
        self.worker = worker_factory()
        self.worker.moveToThread(self.thread)
        queued = Qt.ConnectionType.QueuedConnection
        self.request_connect.connect(self.worker.connect_device, queued)
        self.request_disconnect.connect(self.worker.disconnect_device, queued)
        self.request_set_angle.connect(self.worker.set_angle, queued)
        self.request_adjust_angle.connect(self.worker.adjust_angle, queued)
        self.request_stop.connect(self.worker.stop, queued)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.position_updated.connect(panel.show_position)
        self.worker.busy_changed.connect(panel.set_busy)
        self.worker.error.connect(self._on_error)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        panel.refresh_requested.connect(self.refresh_ports)
        panel.connect_requested.connect(self.connect)
        panel.disconnect_requested.connect(self.disconnect)
        panel.set_angle_requested.connect(self.request_set_angle)
        panel.adjust_angle_requested.connect(self.request_adjust_angle)

    @Slot()
    def refresh_ports(self) -> None:
        try:
            self.panel.set_ports(self.port_manager.list_ports())
        except Exception as exc:
            logger.exception("Nie udało się przeskanować portów dla MPC220")
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

    @Slot()
    def _on_connected(self) -> None:
        self.panel.set_connected(True)

    @Slot()
    def _on_disconnected(self) -> None:
        self._release_port()
        self.panel.set_connected(False)

    @Slot(str)
    def _on_error(self, message: str) -> None:
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
                logger.error("Wątek MPC220 nie zakończył się w limicie czasu")
                self.thread.quit()
                self.thread.wait(timeout_ms)
        self._release_port()
