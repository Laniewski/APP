"""Panel GUI kontrolera piezo MDT694B."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton, QSizePolicy


class MDT694BPanel(QGroupBox):
    refresh_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    set_voltage_requested = Signal(float)
    start_ramp_requested = Signal(float, float)
    stop_ramp_requested = Signal()

    def __init__(self) -> None:
        super().__init__("MDT694B — sterownik piezo")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QGridLayout(self)
        layout.setColumnStretch(1, 1)
        self.mdt_port_label = QLabel("Port:")
        self.mdt_port_combo = QComboBox()
        self.mdt_refresh_ports_button = QPushButton("Odśwież")
        self.mdt_connect_button = QPushButton("Połącz")
        self.mdt_disconnect_button = QPushButton("Rozłącz")
        self.mdt_actual_voltage_label = QLabel("— V")
        self.mdt_voltage_input = QDoubleSpinBox()
        self.mdt_voltage_input.setDecimals(2)
        self.mdt_voltage_input.setSingleStep(0.1)
        self.mdt_voltage_input.setRange(0.0, 150.0)
        self.mdt_voltage_input.setSuffix(" V")
        self.mdt_set_button = QPushButton("Ustaw napięcie")
        self.mdt_ramp_rate_input = QDoubleSpinBox()
        self.mdt_ramp_rate_input.setDecimals(2)
        self.mdt_ramp_rate_input.setRange(0.01, 1000.0)
        self.mdt_ramp_rate_input.setValue(10.0)
        self.mdt_ramp_rate_input.setSuffix(" V/s")
        self.mdt_start_ramp_button = QPushButton("Rozpocznij rampę")
        self.mdt_stop_ramp_button = QPushButton("Zatrzymaj rampę")
        self.mdt_ramp_status_label = QLabel("Rampa nieaktywna")
        self.mdt_status_label = QLabel("Rozłączono")
        self.mdt_port_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mdt_port_combo.setMinimumContentsLength(10)
        self.mdt_status_label.setWordWrap(True)
        self.mdt_ramp_status_label.setWordWrap(True)
        layout.addWidget(self.mdt_port_label, 0, 0)
        layout.addWidget(self.mdt_port_combo, 0, 1)
        connection_buttons = QHBoxLayout()
        for button in (self.mdt_refresh_ports_button, self.mdt_connect_button, self.mdt_disconnect_button):
            connection_buttons.addWidget(button)
        layout.addLayout(connection_buttons, 1, 0, 1, 2)
        layout.addWidget(QLabel("Napięcie aktualne:"), 2, 0)
        layout.addWidget(self.mdt_actual_voltage_label, 2, 1)
        layout.addWidget(QLabel("Napięcie zadane:"), 3, 0)
        layout.addWidget(self.mdt_voltage_input, 3, 1)
        layout.addWidget(self.mdt_set_button, 4, 0, 1, 2)
        layout.addWidget(QLabel("Prędkość rampy:"), 5, 0)
        layout.addWidget(self.mdt_ramp_rate_input, 5, 1)
        ramp_buttons = QHBoxLayout()
        ramp_buttons.addWidget(self.mdt_start_ramp_button)
        ramp_buttons.addWidget(self.mdt_stop_ramp_button)
        layout.addLayout(ramp_buttons, 6, 0, 1, 2)
        layout.addWidget(QLabel("Rampa:"), 7, 0)
        layout.addWidget(self.mdt_ramp_status_label, 7, 1)
        layout.addWidget(QLabel("Status:"), 8, 0)
        layout.addWidget(self.mdt_status_label, 8, 1)
        self.mdt_refresh_ports_button.clicked.connect(self.refresh_requested)
        self.mdt_connect_button.clicked.connect(self._request_connect)
        self.mdt_disconnect_button.clicked.connect(self.disconnect_requested)
        self.mdt_set_button.clicked.connect(
            lambda: self.set_voltage_requested.emit(self.mdt_voltage_input.value())
        )
        self.mdt_start_ramp_button.clicked.connect(
            lambda: self.start_ramp_requested.emit(
                self.mdt_voltage_input.value(), self.mdt_ramp_rate_input.value()
            )
        )
        self.mdt_stop_ramp_button.clicked.connect(self.stop_ramp_requested)
        self._connected = False
        self._busy = False
        self._ramp_active = False
        self._optimization_locked = False
        self.set_connected(False)

    def _request_connect(self) -> None:
        port = self.mdt_port_combo.currentData()
        self.connect_requested.emit(port if isinstance(port, str) else "")

    def set_ports(self, ports) -> None:
        selected = self.mdt_port_combo.currentData()
        self.mdt_port_combo.clear()
        preferred = -1
        for index, port in enumerate(ports):
            self.mdt_port_combo.addItem(f"{port.device} — {port.description}", port.device)
            if ((getattr(port, "vid", None) == 0x1313
                 and getattr(port, "pid", None) == 0x1004)
                    or "mdt694b" in port.description.lower()):
                preferred = index
        selected_index = self.mdt_port_combo.findData(selected)
        if selected_index >= 0:
            self.mdt_port_combo.setCurrentIndex(selected_index)
        elif preferred >= 0:
            self.mdt_port_combo.setCurrentIndex(preferred)
        if not ports:
            self.mdt_port_combo.addItem("Brak dostępnych portów", None)
        self._apply_state()

    def set_connected(self, connected: bool) -> None:
        self._connected, self._busy = connected, False
        if not connected:
            self._ramp_active = False
            self.mdt_ramp_status_label.setText("Rampa nieaktywna")
        self.mdt_status_label.setText("Połączono" if connected else "Rozłączono")
        self._apply_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._apply_state()

    def _apply_state(self) -> None:
        port = self.mdt_port_combo.currentData() is not None
        self.mdt_port_combo.setEnabled(not self._connected and not self._busy and port)
        self.mdt_refresh_ports_button.setEnabled(not self._connected and not self._busy)
        self.mdt_connect_button.setEnabled(not self._connected and not self._busy and port)
        self.mdt_disconnect_button.setEnabled(self._connected and not self._busy)
        controls_enabled = self._connected and not self._busy and not self._ramp_active
        self.mdt_voltage_input.setEnabled(controls_enabled)
        self.mdt_ramp_rate_input.setEnabled(controls_enabled)
        self.mdt_set_button.setEnabled(controls_enabled)
        self.mdt_start_ramp_button.setEnabled(controls_enabled)
        self.mdt_stop_ramp_button.setEnabled(
            self._connected and not self._busy and self._ramp_active
        )
        if self._optimization_locked:
            for button in self.findChildren(QPushButton):
                button.setEnabled(False)

    def set_optimization_locked(self, locked: bool) -> None:
        self._optimization_locked = bool(locked)
        self._apply_state()

    def set_ramp_active(self, active: bool) -> None:
        self._ramp_active = bool(active)
        self.mdt_ramp_status_label.setText("Rampa aktywna" if active else "Rampa nieaktywna")
        self._apply_state()

    def show_voltage(self, voltage: float) -> None:
        self.mdt_actual_voltage_label.setText(f"{voltage:.2f} V")

    def set_voltage_range(self, minimum: float, maximum: float) -> None:
        self.mdt_voltage_input.setRange(minimum, maximum)

    def show_error(self, message: str) -> None:
        self.mdt_status_label.setText(f"Błąd komunikacji: {message}")

    def show_command_error(self, message: str) -> None:
        self.mdt_status_label.setText(f"Błąd: {message}")
