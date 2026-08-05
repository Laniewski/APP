"""Asynchroniczna obsługa MDT694B poza wątkiem GUI."""

import logging

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from modules.mdt694b.driver import MDT694BDriver

logger = logging.getLogger(__name__)


class MDT694BWorker(QObject):
    connected = Signal()
    disconnected = Signal()
    voltage_updated = Signal(float)
    voltage_range_updated = Signal(float, float)
    busy_changed = Signal(bool)
    error = Signal(str)

    def __init__(self, driver_factory=MDT694BDriver, poll_interval_ms: int = 500) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._poll_interval_ms = poll_interval_ms
        self._driver = None
        self._timer = None

    @Slot(str)
    def connect_device(self, port: str) -> None:
        self.busy_changed.emit(True)
        self._close_driver()
        try:
            self._driver = self._driver_factory(port)
            self._driver.connect()
            minimum, maximum = self._driver.read_voltage_range()
            voltage = self._driver.read_voltage()
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
            logger.info("MDT694B: zadano %.2f V", value)
            voltage = self._require_driver().set_voltage(value)
            logger.info("MDT694B: urządzenie zwróciło %.2f V", voltage)
            self.voltage_updated.emit(voltage)
        except Exception as exc:
            self._fail("Nie udało się ustawić napięcia MDT694B", exc)
        finally:
            self.busy_changed.emit(False)

    @Slot()
    def refresh_voltage(self) -> None:
        try:
            self.voltage_updated.emit(self._require_driver().read_voltage())
        except Exception as exc:
            self._fail("Nie udało się odczytać napięcia MDT694B", exc)

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
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        driver, self._driver = self._driver, None
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
    request_stop = Signal()

    def __init__(self, panel, port_manager, worker_factory=MDT694BWorker) -> None:
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
        self.request_set_voltage.connect(self.worker.set_voltage, queued)
        self.request_refresh_voltage.connect(self.worker.refresh_voltage, queued)
        self.request_stop.connect(self.worker.stop, queued)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.voltage_updated.connect(panel.show_voltage)
        self.worker.voltage_range_updated.connect(panel.set_voltage_range)
        self.worker.busy_changed.connect(panel.set_busy)
        self.worker.error.connect(self._on_error)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        panel.refresh_requested.connect(self.refresh_ports)
        panel.connect_requested.connect(self.connect)
        panel.disconnect_requested.connect(self.disconnect)
        panel.set_voltage_requested.connect(self.set_voltage)

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
                logger.error("Wątek MDT694B nie zakończył się w limicie czasu")
                self.thread.quit()
                self.thread.wait(timeout_ms)
        self._release_port()
