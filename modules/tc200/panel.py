"""Wyłącznie interfejs użytkownika modułu TC200."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
)


class TC200Panel(QGroupBox):
    refresh_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    set_temperature_requested = Signal(float)
    heater_requested = Signal(bool)

    def __init__(self) -> None:
        super().__init__("TC200 — kontroler temperatury")
        layout = QGridLayout(self)
        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Odśwież")
        self.connect_button = QPushButton("Połącz")
        self.disconnect_button = QPushButton("Rozłącz")
        self.status_label = QLabel("Rozłączono")
        self.current_label = QLabel("— °C")
        self.setpoint_label = QLabel("— °C")
        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setRange(20.0, 200.0)
        self.temperature_input.setDecimals(1)
        self.temperature_input.setSuffix(" °C")
        self.set_button = QPushButton("Ustaw temperaturę")
        self.heater_button = QPushButton("Włącz grzanie")
        self.heater_button.setCheckable(True)
        self.device_details = QLabel("Stan urządzenia: —")
        self.alarm_label = QLabel("Alarmy: brak")
        self.alarm_label.setWordWrap(True)
        self._connected = False
        self._optimization_locked = False

        layout.addWidget(QLabel("Port:"), 0, 0)
        layout.addWidget(self.port_combo, 0, 1)
        layout.addWidget(self.refresh_button, 0, 2)
        layout.addWidget(self.connect_button, 0, 3)
        layout.addWidget(self.disconnect_button, 0, 4)
        layout.addWidget(QLabel("Połączenie:"), 1, 0)
        layout.addWidget(self.status_label, 1, 1, 1, 4)
        layout.addWidget(QLabel("Temperatura aktualna:"), 2, 0)
        layout.addWidget(self.current_label, 2, 1)
        layout.addWidget(QLabel("Temperatura zadana:"), 3, 0)
        layout.addWidget(self.setpoint_label, 3, 1)
        layout.addWidget(self.temperature_input, 3, 2)
        layout.addWidget(self.set_button, 3, 3, 1, 2)
        layout.addWidget(self.heater_button, 4, 0, 1, 5)
        layout.addWidget(self.device_details, 5, 0, 1, 5)
        layout.addWidget(self.alarm_label, 6, 0, 1, 5)

        self.refresh_button.clicked.connect(self.refresh_requested)
        self.connect_button.clicked.connect(self._request_connect)
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        self.set_button.clicked.connect(
            lambda: self.set_temperature_requested.emit(self.temperature_input.value())
        )
        self.heater_button.clicked.connect(self.heater_requested)
        self.set_connected(False)

    def _request_connect(self) -> None:
        port = self.port_combo.currentData()
        self.connect_requested.emit(port if isinstance(port, str) else "")

    def set_ports(self, ports) -> None:
        selected = self.port_combo.currentData()
        self.port_combo.clear()
        for port in ports:
            self.port_combo.addItem(f"{port.device} — {port.description}", port.device)
        if not ports:
            self.port_combo.addItem("Brak dostępnych portów", None)
        index = self.port_combo.findData(selected)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        self.port_combo.setEnabled(bool(ports))
        self.connect_button.setEnabled(bool(ports))

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self.port_combo.setEnabled(not connected and self.port_combo.currentData() is not None)
        self.refresh_button.setEnabled(not connected)
        self.connect_button.setEnabled(not connected and self.port_combo.currentData() is not None)
        self.disconnect_button.setEnabled(connected)
        self.temperature_input.setEnabled(connected)
        self.set_button.setEnabled(connected)
        self.heater_button.setEnabled(connected)
        if not connected:
            self.heater_button.setChecked(False)
            self.heater_button.setText("Włącz grzanie")
        self._apply_optimization_lock()

    def set_busy(self, text: str) -> None:
        self.status_label.setText(text)
        for widget in (self.connect_button, self.disconnect_button, self.set_button, self.heater_button):
            widget.setEnabled(False)

    def set_optimization_locked(self, locked: bool) -> None:
        self._optimization_locked = bool(locked)
        if locked:
            self._apply_optimization_lock()
        else:
            self.set_connected(self._connected)

    def _apply_optimization_lock(self) -> None:
        if self._optimization_locked:
            for button in self.findChildren(QPushButton):
                button.setEnabled(False)

    def show_readings(self, current: float, setpoint: float) -> None:
        self.current_label.setText(f"{current:.1f} °C")
        self.setpoint_label.setText(f"{setpoint:.1f} °C")
        if not self.temperature_input.hasFocus():
            self.temperature_input.setValue(setpoint)

    def show_status(self, status) -> None:
        self.heater_button.blockSignals(True)
        self.heater_button.setChecked(status.heater_enabled)
        self.heater_button.setText(
            "Wyłącz grzanie" if status.heater_enabled else "Włącz grzanie"
        )
        self.heater_button.blockSignals(False)
        mode = "cykl" if status.cycle_mode else "normalny"
        pause = ", pauza" if status.cycle_paused else ""
        self.device_details.setText(
            f"Stan urządzenia: tryb {mode}{pause}, czujnik {status.sensor}, "
            f"jednostki {status.units}, status 0x{status.raw:02X}"
        )
        self.alarm_label.setText(
            "Alarmy: " + (", ".join(status.alarms) if status.alarms else "brak")
        )

    def show_error(self, message: str) -> None:
        self.status_label.setText(f"Błąd komunikacji: {message}")
