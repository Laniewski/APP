"""Składanie modułów aplikacji i koordynacja zamknięcia."""

from app.main_window import MainWindow
from app.port_manager import PortManager
from modules.mdt694b.controller import MDT694BController
from modules.measurement.controller import MeasurementController
from modules.mpc220.controller import MPC220Controller
from modules.tc200.controller import TC200Controller


class ApplicationController:
    def __init__(self, window: MainWindow, port_manager: PortManager | None = None) -> None:
        self.window = window
        self.port_manager = port_manager or PortManager()
        self.measurement = MeasurementController(window.measurement_panel)
        self.tc200 = TC200Controller(window.tc200_panel, self.port_manager)
        self.mdt694b = MDT694BController(window.mdt694b_panel, self.port_manager)
        self.mpc220 = MPC220Controller(window.mpc220_panel, self.port_manager)
        self.mpc220.attach_optimizer_dependencies(
            self.mdt694b, self.measurement, self.tc200,
        )
        self.mpc220.worker.optimizer_active_changed.connect(
            window.set_optimization_lock,
        )
        self.mpc220.worker.optimizer_active_changed.connect(
            window.tc200_panel.set_optimization_locked,
        )
        self.mpc220.worker.optimizer_active_changed.connect(
            window.mdt694b_panel.set_optimization_locked,
        )
        self.mpc220.worker.optimizer_active_changed.connect(
            window.measurement_panel.set_optimization_locked,
        )
        self.tc200.worker.readings.connect(self.measurement.update_tc200_readings)
        self.mdt694b.worker.voltage_updated.connect(self.measurement.update_piezo_voltage)
        self.mpc220.worker.position_updated.connect(self.measurement.update_paddle_angle)
        self.tc200.refresh_ports()
        self.mdt694b.refresh_ports()
        self.mpc220.refresh_ports()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self.measurement.shutdown(timeout_ms=timeout_ms)
        self.tc200.shutdown(timeout_ms=timeout_ms)
        self.mdt694b.shutdown(timeout_ms=timeout_ms)
        self.mpc220.shutdown(timeout_ms=timeout_ms)
