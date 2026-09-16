"""Kontroler MPC220 i worker będący jedynym właścicielem drivera."""

import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from modules.mpc220.calibration import (angle_to_command, calculate_target_angle,
                                        clamp_angle, raw_position_to_angle)
from modules.mpc220.driver import MPC220Driver
from modules.mpc220.polarization_optimizer import PolarizationOptimizer

logger = logging.getLogger(__name__)


class MPC220Worker(QObject):
    connected = Signal()
    disconnected = Signal()
    position_updated = Signal(int, float)
    busy_changed = Signal(bool)
    error = Signal(str)
    stopped = Signal()
    optimizer_progress = Signal(dict)
    optimizer_finished = Signal(dict)
    optimizer_error = Signal(str)
    optimizer_active_changed = Signal(bool)
    piezo_set_requested = Signal(float)
    piezo_ramp_requested = Signal(float, float)
    piezo_stop_requested = Signal()

    def __init__(self, driver_factory=MPC220Driver) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._driver = None
        self.optimizer = PolarizationOptimizer(
            self._optimizer_move,
            self._optimizer_read_position,
            self._optimizer_move_and_wait,
            self,
        )
        self.optimizer.progress.connect(self.optimizer_progress)
        self.optimizer.finished.connect(self._optimizer_done)
        self.optimizer.error.connect(self._optimizer_failed)
        self.optimizer.piezo_set_requested.connect(self.piezo_set_requested)
        self.optimizer.piezo_ramp_requested.connect(self.piezo_ramp_requested)
        self.optimizer.piezo_stop_requested.connect(self.piezo_stop_requested)

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

    @Slot()
    def start_optimizer(self) -> None:
        try:
            self._require_driver()
            self.optimizer_active_changed.emit(True)
            self.optimizer.start()
        except Exception as exc:
            self._optimizer_failed(str(exc))

    @Slot()
    def cancel_optimizer(self) -> None:
        self.optimizer.cancel()

    @Slot(float, float)
    def add_optimizer_sample(self, in0: float, in1: float) -> None:
        self.optimizer.add_sample(in0, in1)

    def _optimizer_move(self, p1: float, p2: float) -> tuple[float, float]:
        driver = self._require_driver()
        p1, p2 = clamp_angle(p1), clamp_angle(p2)
        driver.move_absolute_units(1, angle_to_command(p1))
        driver.move_absolute_units(2, angle_to_command(p2))
        self.position_updated.emit(1, p1)
        self.position_updated.emit(2, p2)
        return p1, p2

    def _optimizer_read_position(self) -> tuple[float, float]:
        return self._read_angle(1), self._read_angle(2)

    def _optimizer_move_and_wait(self, p1: float, p2: float) -> tuple[float, float]:
        driver = self._require_driver()
        p1, p2 = clamp_angle(p1), clamp_angle(p2)
        driver.move_absolute_units(1, angle_to_command(p1))
        driver.move_absolute_units(2, angle_to_command(p2))
        driver.wait_until_stopped(1)
        driver.wait_until_stopped(2)
        actual = self._optimizer_read_position()
        self.position_updated.emit(1, actual[0])
        self.position_updated.emit(2, actual[1])
        return actual

    @Slot(dict)
    def _optimizer_done(self, result: dict) -> None:
        self.optimizer_active_changed.emit(False)
        self.optimizer_finished.emit(result)
        status = result.get("status")
        if status == "CANCELLED":
            logger.info("Optymalizacja polaryzacji anulowana.")
            return

        amplitude = self._format_result_value(result.get("best_amplitude_v"), " V")
        p1 = self._format_result_value(result.get("best_p1_deg"), "°")
        p2 = self._format_result_value(result.get("best_p2_deg"), "°")
        best_time = self._format_result_value(
            result.get("best_measurement_time_s"), " s",
        )
        total_time = self._format_result_value(result.get("total_time_s"), " s")
        if status == "SUCCESS":
            logger.info(
                "Optymalizacja polaryzacji zakończona:\n"
                "A_D max = %s\nP1 = %s\nP2 = %s\n"
                "Czas znalezienia maksimum = %s\nCzas całkowity = %s",
                amplitude, p1, p2, best_time, total_time,
            )
        elif status == "NOT_FOUND":
            logger.info(
                "Optymalizacja polaryzacji zakończona - nie osiągnięto kryterium:\n"
                "Najlepsze A_D = %s\nP1 = %s\nP2 = %s\n"
                "Czas znalezienia najlepszego wyniku = %s\nCzas całkowity = %s",
                amplitude, p1, p2, best_time, total_time,
            )

    @Slot(str)
    def _optimizer_failed(self, message) -> None:
        self.optimizer_active_changed.emit(False)
        self.optimizer_error.emit(str(message))
        logger.error("Optymalizacja polaryzacji zakończona błędem: %s", message)

    @staticmethod
    def _format_result_value(value, unit: str) -> str:
        return "brak danych" if value is None else f"{float(value):.3f}{unit}"

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
        if self.optimizer.active:
            self.optimizer.cancel()
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
    request_optimizer_start = Signal()
    request_optimizer_cancel = Signal()
    request_optimizer_sample = Signal(float, float)

    def __init__(self, panel, port_manager, worker_factory=MPC220Worker) -> None:
        super().__init__(panel)
        self.panel = panel
        self.port_manager = port_manager
        self._port = None
        self._connected = False
        self._mdt_controller = None
        self._measurement_controller = None
        self._tc200_controller = None
        self.thread = QThread(self)
        self.worker = worker_factory()
        self.worker.moveToThread(self.thread)
        queued = Qt.ConnectionType.QueuedConnection
        self.request_connect.connect(self.worker.connect_device, queued)
        self.request_disconnect.connect(self.worker.disconnect_device, queued)
        self.request_set_angle.connect(self.worker.set_angle, queued)
        self.request_adjust_angle.connect(self.worker.adjust_angle, queued)
        self.request_stop.connect(self.worker.stop, queued)
        self.request_optimizer_start.connect(self.worker.start_optimizer, queued)
        self.request_optimizer_cancel.connect(self.worker.cancel_optimizer, queued)
        self.request_optimizer_sample.connect(self.worker.add_optimizer_sample, queued)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.position_updated.connect(panel.show_position)
        self.worker.busy_changed.connect(panel.set_busy)
        self.worker.error.connect(self._on_error)
        self.worker.optimizer_progress.connect(panel.show_optimization_progress)
        self.worker.optimizer_finished.connect(panel.show_optimization_result)
        self.worker.optimizer_error.connect(panel.show_optimization_error)
        self.worker.optimizer_active_changed.connect(panel.set_optimizing)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        panel.refresh_requested.connect(self.refresh_ports)
        panel.connect_requested.connect(self.connect)
        panel.disconnect_requested.connect(self.disconnect)
        panel.set_angle_requested.connect(self.request_set_angle)
        panel.adjust_angle_requested.connect(self.request_adjust_angle)
        panel.optimization_requested.connect(self.start_optimization)
        panel.optimization_cancel_requested.connect(self.cancel_optimization)

    def attach_optimizer_dependencies(
        self, mdt_controller, measurement_controller, tc200_controller=None,
    ) -> None:
        """Łączy istniejące workery; nie tworzy żadnych nowych driverów."""
        self._mdt_controller = mdt_controller
        self._measurement_controller = measurement_controller
        self._tc200_controller = tc200_controller
        self.worker.piezo_set_requested.connect(mdt_controller.request_set_voltage)
        self.worker.piezo_ramp_requested.connect(mdt_controller.request_start_ramp)
        self.worker.piezo_stop_requested.connect(mdt_controller.request_stop_ramp)
        measurement_controller.worker.sample_ready.connect(self.request_optimizer_sample)

    @Slot()
    def start_optimization(self) -> None:
        missing = []
        if not self._connected:
            missing.append("MPC220 odłączony")
        if self._mdt_controller is None or not self._mdt_controller.is_connected():
            missing.append("MDT694B odłączony")
        if self._measurement_controller is None or not self._measurement_controller.is_running():
            missing.append("rozpocznij pomiar ADS1263")
        if (self._tc200_controller is None
                or not self._tc200_controller.is_heater_confirmed_off()):
            missing.append("wyłącz grzałkę lub odłącz TC200")
        if missing:
            self.panel.show_optimization_error("Brak: " + ", ".join(missing) + ".")
            return
        self.request_optimizer_start.emit()

    @Slot()
    def cancel_optimization(self) -> None:
        self.request_optimizer_cancel.emit()

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
            self.request_optimizer_cancel.emit()
            self.request_stop.emit()
            if not self.thread.wait(timeout_ms):
                logger.error("Wątek MPC220 nie zakończył się w limicie czasu")
                self.thread.quit()
                self.thread.wait(timeout_ms)
        self._release_port()
