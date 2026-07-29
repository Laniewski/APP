"""Kontroler łączący GUI z logiką aplikacji."""

from app.main_window import MainWindow

from app.serial_ports import scan_serial_ports


class MainController:
    """Koordynuje działanie GUI i pozostałych elementów aplikacji."""

    def __init__(self, window: MainWindow) -> None:
        """Łączy kontroler z głównym oknem aplikacji i inicjalizuje sygnały."""
        self.window = window
        self.connect_signals()

    def _connect_signals(self) -> None:
        """Łączy sygnały kontrolek GUI z metodami kontrolera."""
        self.window.tc_refresh_ports_button.clicked.connect(
            self.refresh_tc_ports
        )

    def refresh_tc_ports(self) -> None:
        """Wyszukuje porty szeregowe i wyświetla je na liście TC200."""
        ports = scan_serial_ports()
        combo = self.window.tc_port_combo

        combo.clear()

        if not ports:
            combo.addItem("Brak dostępnych portów", None)
            combo.setEnabled(False)
            return

        combo.setEnabled(True)

        for port in ports:
            description = port.description or "Nieznane urządzenie"
            display_text = f"{port.device} — {description}"
            combo.addItem(display_text, port.device)

    def get_selected_tc_port(self) -> str | None:
        """Zwraca nazwę wybranego portu TC200 albo None."""
        selected_port = self.window.tc_port_combo.currentData()
        return selected_port