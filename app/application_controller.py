"""Składanie modułów aplikacji i koordynacja zamknięcia."""

from app.main_window import MainWindow
from app.port_manager import PortManager
from modules.measurement.controller import MeasurementController
from modules.tc200.controller import TC200Controller


class ApplicationController:
    def __init__(self, window: MainWindow, port_manager: PortManager | None = None) -> None:
        self.window = window
        self.port_manager = port_manager or PortManager()
        self.measurement = MeasurementController(window.measurement_panel)
        self.tc200 = TC200Controller(window.tc200_panel, self.port_manager)
        self.tc200.refresh_ports()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self.measurement.shutdown(timeout_ms=timeout_ms)
        self.tc200.shutdown(timeout_ms=timeout_ms)
