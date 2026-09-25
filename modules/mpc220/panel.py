"""Panel MPC220 emitujący wyłącznie intencje użytkownika."""

from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QSizePolicy)


class MPC220Panel(QGroupBox):
    refresh_requested = Signal()
    connect_requested = Signal(str)
    disconnect_requested = Signal()
    set_angle_requested = Signal(int, float)
    adjust_angle_requested = Signal(int, float)
    optimization_requested = Signal()
    optimization_cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__("MPC220 — kontroler polaryzacji")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        ports = QHBoxLayout()
        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Odśwież")
        self.connect_button = QPushButton("Połącz")
        self.disconnect_button = QPushButton("Rozłącz")
        ports.addWidget(QLabel("Port:"))
        ports.addWidget(self.port_combo, 1)
        self.port_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setMinimumContentsLength(10)
        layout.addLayout(ports)
        connection_buttons = QHBoxLayout()
        connection_buttons.addWidget(self.refresh_button)
        connection_buttons.addWidget(self.connect_button)
        connection_buttons.addWidget(self.disconnect_button)
        layout.addLayout(connection_buttons)
        self.optimization_button = QPushButton("Automatyczna optymalizacja")
        self.optimization_status = QLabel("")
        self.optimization_status.setWordWrap(True)
        self.optimization_status.hide()
        layout.addWidget(self.optimization_button)
        layout.addWidget(self.optimization_status)
        self._movement_widgets = []
        for paddle in (1, 2):
            layout.addWidget(self._create_paddle_panel(paddle))
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.connect_button.clicked.connect(self._request_connect)
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        self.optimization_button.clicked.connect(self._toggle_optimization)
        self._connected = False
        self._busy = False
        self._optimizing = False
        self.set_connected(False)

    def _create_paddle_panel(self, paddle: int) -> QGroupBox:
        group = QGroupBox(f"Łopatka {paddle}")
        layout = QGridLayout(group)
        position = QLabel("—")
        target = QDoubleSpinBox()
        target.setRange(1, 160)
        target.setDecimals(0)
        target.setSuffix("°")
        set_button = QPushButton("Ustaw")
        steps = QGridLayout()
        for index, delta in enumerate((-10, -5, -1, 1, 5, 10)):
            button = QPushButton(f"{delta:+d}°")
            button.clicked.connect(partial(self.adjust_angle_requested.emit, paddle, float(delta)))
            steps.addWidget(button, index // 3, index % 3)
            self._movement_widgets.append(button)
        set_button.clicked.connect(
            lambda _checked=False, p=paddle, field=target:
            self.set_angle_requested.emit(p, field.value())
        )
        setattr(self, f"position_{paddle}", position)
        setattr(self, f"target_{paddle}", target)
        layout.addLayout(steps, 0, 0, 1, 2)
        layout.addWidget(QLabel("Aktualna pozycja:"), 1, 0)
        layout.addWidget(position, 1, 1)
        layout.addWidget(QLabel("Pozycja docelowa:"), 2, 0)
        layout.addWidget(target, 2, 1)
        layout.addWidget(set_button, 3, 0, 1, 2)
        self._movement_widgets.extend((target, set_button))
        return group

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
        self._apply_state()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._busy = False
        self._apply_state()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._apply_state()

    def _apply_state(self) -> None:
        has_port = self.port_combo.currentData() is not None
        self.port_combo.setEnabled(not self._connected and not self._busy and has_port)
        self.refresh_button.setEnabled(not self._connected and not self._busy)
        self.connect_button.setEnabled(not self._connected and not self._busy and has_port)
        self.disconnect_button.setEnabled(self._connected and not self._busy and not self._optimizing)
        # Pozostaje dostępny także przed połączeniem, aby kliknięcie mogło
        # wyświetlić kompletną listę brakujących urządzeń.
        self.optimization_button.setEnabled(not self._busy)
        for widget in self._movement_widgets:
            widget.setEnabled(self._connected and not self._busy and not self._optimizing)

    def _toggle_optimization(self) -> None:
        if self._optimizing:
            self.optimization_cancel_requested.emit()
        else:
            self.optimization_requested.emit()

    def set_optimizing(self, optimizing: bool) -> None:
        self._optimizing = bool(optimizing)
        self.optimization_button.setText(
            "Anuluj optymalizację" if optimizing else "Automatyczna optymalizacja"
        )
        if optimizing:
            self.optimization_status.clear()
            self.optimization_status.hide()
        self._apply_state()

    def show_optimization_progress(self, progress: dict) -> None:
        # Postęp nie jest wyświetlany; panel pozostaje możliwie mały.
        pass

    def show_optimization_result(self, result: dict) -> None:
        self.set_optimizing(False)
        self.optimization_status.clear()
        self.optimization_status.hide()

    def show_optimization_error(self, message: str) -> None:
        self.set_optimizing(False)
        self.optimization_status.setText(message)
        self.optimization_status.show()
        self.show_error(message)

    def show_position(self, paddle_number: int, angle_deg: float) -> None:
        getattr(self, f"position_{paddle_number}").setText(f"{angle_deg:.1f}°")

    def show_error(self, message: str) -> None:
        # Panel celowo nie ma globalnego statusu; błąd jest dostępny jako tooltip.
        self.setToolTip(f"Błąd komunikacji: {message}")
