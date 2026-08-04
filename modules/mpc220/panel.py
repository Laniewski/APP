"""GUI kontrolera MPC220."""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class MPC220Panel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("MPC220 — kontroler polaryzacji")
        layout = QVBoxLayout(self)

        self.mpc_status_label = QLabel("Niepołączony")
        layout.addWidget(QLabel("Status:"))
        layout.addWidget(self.mpc_status_label)

        layout.addWidget(self._create_paddle_panel(1))
        layout.addWidget(self._create_paddle_panel(2))

        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel("Port:"))
        self.mpc_port_combo = QComboBox()
        self.mpc_port_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        port_layout.addWidget(self.mpc_port_combo)
        self.mpc_refresh_ports_button = QPushButton("Odśwież porty")
        port_layout.addWidget(self.mpc_refresh_ports_button)
        self.mpc_connect_button = QPushButton("Połącz")
        port_layout.addWidget(self.mpc_connect_button)
        port_layout.addStretch()

        layout.addLayout(port_layout)
        layout.addStretch()

    def _create_paddle_panel(self, paddle_number: int) -> QGroupBox:
        group = QGroupBox(f"Łopatka {paddle_number}")
        layout = QGridLayout(group)

        left_large = QPushButton("-10°")
        left_medium = QPushButton("-5°")
        left_small = QPushButton("-1°")
        position_label = QLabel("—")
        target_spinbox = QDoubleSpinBox()
        target_spinbox.setDecimals(0)
        target_spinbox.setRange(1, 160)
        target_spinbox.setSuffix("°")
        set_button = QPushButton("Ustaw")
        right_small = QPushButton("+1°")
        right_medium = QPushButton("+5°")
        right_large = QPushButton("+10°")

        setattr(self, f"mpc{paddle_number}_left_large_button", left_large)
        setattr(self, f"mpc{paddle_number}_left_medium_button", left_medium)
        setattr(self, f"mpc{paddle_number}_left_small_button", left_small)
        setattr(self, f"mpc{paddle_number}_position_label", position_label)
        setattr(self, f"mpc{paddle_number}_target_spinbox", target_spinbox)
        setattr(self, f"mpc{paddle_number}_set_button", set_button)
        setattr(self, f"mpc{paddle_number}_right_small_button", right_small)
        setattr(self, f"mpc{paddle_number}_right_medium_button", right_medium)
        setattr(self, f"mpc{paddle_number}_right_large_button", right_large)

        move_layout = QHBoxLayout()
        move_layout.addWidget(left_large)
        move_layout.addWidget(left_medium)
        move_layout.addWidget(left_small)
        move_layout.addStretch()
        move_layout.addWidget(right_small)
        move_layout.addWidget(right_medium)
        move_layout.addWidget(right_large)

        layout.addLayout(move_layout, 0, 0, 1, 3)
        layout.addWidget(QLabel("Aktualna pozycja:"), 1, 0)
        layout.addWidget(position_label, 1, 1, 1, 2)
        layout.addWidget(QLabel("Pozycja docelowa:"), 2, 0)
        layout.addWidget(target_spinbox, 2, 1)
        layout.addWidget(set_button, 2, 2)

        return group
