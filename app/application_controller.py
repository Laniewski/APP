"""Składanie modułów aplikacji i koordynacja zamknięcia."""

from app.main_window import MainWindow
from app.port_manager import PortManager
from modules.tc200.controller import TC200Controller


class ApplicationController:
    def __init__(self, window: MainWindow, port_manager: PortManager | None = None) -> None:
        self.window = window
        self.port_manager = port_manager or PortManager()
        self.tc200 = TC200Controller(window.tc200_panel, self.port_manager)
        self.tc200.refresh_ports()

    def shutdown(self) -> None:
        self.tc200.shutdown()
