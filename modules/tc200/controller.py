"""Kontroler i worker TC200. Cała komunikacja blokująca działa w QThread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt

from modules.tc200.driver import TC200Driver

logger = logging.getLogger(__name__)


class TC200Worker(QObject):
    connected = Signal(str)
    disconnected = Signal()
    readings = Signal(float, float)
    status = Signal(object)
    operation_finished = Signal(str)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, driver_factory=TC200Driver, poll_interval_ms: int = 1000) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._poll_interval_ms = poll_interval_ms
        self._driver = None
        self._timer = None

    @Slot(str)
    def connect_device(self, port: str) -> None:
        self._close_driver()
        try:
            driver = self._driver_factory(port)
            self._driver = driver
            driver.connect()
            identity = driver.identify()
            self.connected.emit(identity)
            self._publish_all()
            self._timer = QTimer(self)
            self._timer.setInterval(self._poll_interval_ms)
            self._timer.timeout.connect(self.poll)
            self._timer.start()
        except Exception as exc:
            logger.exception("Nie udało się połączyć z TC200")
            self._close_driver()
            self.error.emit(str(exc))

    @Slot()
    def disconnect_device(self) -> None:
        self._close_driver()
        self.disconnected.emit()

    @Slot(float)
    def set_temperature(self, value: float) -> None:
        try:
            self._require_driver().set_temperature(value)
            self._publish_all()
            self.operation_finished.emit("Temperatura ustawiona")
        except Exception as exc:
            logger.exception("Nie udało się ustawić temperatury TC200")
            self._close_driver()
            self.error.emit(str(exc))

    @Slot(bool)
    def set_heater(self, enabled: bool) -> None:
        try:
            status = self._require_driver().set_heater(enabled)
            self.status.emit(status)
            self.operation_finished.emit("Stan grzania zmieniony")
        except Exception as exc:
            logger.exception("Nie udało się zmienić stanu grzania TC200")
            self._close_driver()
            self.error.emit(str(exc))

    @Slot()
    def poll(self) -> None:
        try:
            self._publish_all()
        except Exception as exc:
            logger.exception("Okresowy odczyt TC200 nie powiódł się")
            self._close_driver()
            self.error.emit(str(exc))

    def _publish_all(self) -> None:
        driver = self._require_driver()
        self.readings.emit(driver.read_temperature(), driver.read_setpoint())
        self.status.emit(driver.read_status())

    def _require_driver(self):
        if self._driver is None:
            raise RuntimeError("TC200 nie jest połączony.")
        return self._driver

    def _close_driver(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @Slot()
    def stop(self) -> None:
        self._close_driver()
        self.stopped.emit()
        QThread.currentThread().quit()


class TC200Controller(QObject):
    request_connect = Signal(str)
    request_disconnect = Signal()
    request_temperature = Signal(float)
    request_heater = Signal(bool)
    request_stop = Signal()

    def __init__(self, panel, port_manager, worker_factory=TC200Worker) -> None:
        super().__init__(panel)
        self.panel = panel
        self.port_manager = port_manager
        self._port = None
        self._closing = False

        self.thread = QThread(self)
        self.worker = worker_factory()
        self.worker.moveToThread(self.thread)
        self.request_connect.connect(self.worker.connect_device, Qt.ConnectionType.QueuedConnection)
        self.request_disconnect.connect(self.worker.disconnect_device, Qt.ConnectionType.QueuedConnection)
        self.request_temperature.connect(self.worker.set_temperature, Qt.ConnectionType.QueuedConnection)
        self.request_heater.connect(self.worker.set_heater, Qt.ConnectionType.QueuedConnection)
        self.request_stop.connect(self.worker.stop, Qt.ConnectionType.QueuedConnection)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.readings.connect(panel.show_readings)
        self.worker.status.connect(panel.show_status)
        self.worker.operation_finished.connect(self._on_operation_finished)
        self.worker.error.connect(self._on_error)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()

        panel.refresh_requested.connect(self.refresh_ports)
        panel.connect_requested.connect(self.connect)
        panel.disconnect_requested.connect(self.disconnect)
        panel.set_temperature_requested.connect(self.set_temperature)
        panel.heater_requested.connect(self.set_heater)

    @Slot()
    def refresh_ports(self) -> None:
        try:
            self.panel.set_ports(self.port_manager.list_ports())
            logger.info("Odświeżono listę portów szeregowych")
        except Exception as exc:
            logger.exception("Nie udało się przeskanować portów")
            self.panel.show_error(f"Nie udało się odświeżyć portów: {exc}")

    @Slot(str)
    def connect(self, port: str) -> None:
        if not port:
            self.panel.show_error("Wybierz port szeregowy.")
            return
        if not self.port_manager.is_available(port):
            self.panel.show_error(f"Port {port} jest już używany.")
            return
        if not self.port_manager.reserve(port, self):
            self.panel.show_error(f"Port {port} jest już używany.")
            return
        self._port = port
        self.panel.set_busy("Łączenie…")
        logger.info("Łączenie z TC200 na %s", port)
        self.request_connect.emit(port)

    @Slot()
    def disconnect(self) -> None:
        self.panel.set_busy("Rozłączanie…")
        self.request_disconnect.emit()

    @Slot(float)
    def set_temperature(self, value: float) -> None:
        self.panel.set_busy("Ustawianie…")
        self.request_temperature.emit(value)

    @Slot(bool)
    def set_heater(self, enabled: bool) -> None:
        self.panel.set_busy("Zmienianie stanu grzania…")
        self.request_heater.emit(enabled)

    @Slot(str)
    def _on_connected(self, identity: str) -> None:
        logger.info("Połączono z %s", identity)
        self.panel.status_label.setText("Połączono")
        self.panel.set_connected(True)

    @Slot()
    def _on_disconnected(self) -> None:
        self._release_port()
        self.panel.status_label.setText("Rozłączono")
        self.panel.set_connected(False)
        logger.info("Rozłączono TC200")

    @Slot(str)
    def _on_operation_finished(self, message: str) -> None:
        self.panel.status_label.setText("Połączono")
        self.panel.set_connected(True)
        logger.info("TC200: %s", message)

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._release_port()
        self.panel.show_error(message)
        self.panel.set_connected(False)
        logger.error("TC200: %s", message)

    def _release_port(self) -> None:
        if self._port is not None:
            self.port_manager.release(self._port, self)
            self._port = None

    def shutdown(self, timeout_ms: int = 3000) -> None:
        if not self.thread.isRunning():
            self._release_port()
            return
        self._closing = True
        self.request_stop.emit()
        if not self.thread.wait(timeout_ms):
            logger.error("Wątek TC200 nie zakończył się w limicie czasu")
            self.thread.quit()
            self.thread.wait(timeout_ms)
        self._release_port()
