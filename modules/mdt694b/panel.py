"""GUI kontrolera MDT694B."""

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
)


class MDT694BPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("MDT694B — sterownik piezo")
        layout = QGridLayout(self)

        self.mdt_current_voltage_label = QLabel("— V")
        self.mdt_setpoint_spinbox = QDoubleSpinBox()
        self.mdt_setpoint_spinbox.setDecimals(3)
        self.mdt_setpoint_spinbox.setRange(0.0, 150.0)
        self.mdt_setpoint_spinbox.setSuffix(" V")
        self.mdt_set_button = QPushButton("Ustaw napięcie")
        self.mdt_status_label = QLabel("Niepołączony")
        self.mdt_port_combo = QComboBox()
        self.mdt_refresh_ports_button = QPushButton("Odśwież porty")

        layout.addWidget(QLabel("Napięcie aktualne:"), 0, 0)
        layout.addWidget(self.mdt_current_voltage_label, 0, 1, 1, 2)

        layout.addWidget(QLabel("Napięcie zadane:"), 1, 0)
        layout.addWidget(self.mdt_setpoint_spinbox, 1, 1)
        layout.addWidget(self.mdt_set_button, 1, 2)

        layout.addWidget(QLabel("Status:"), 2, 0)
        layout.addWidget(self.mdt_status_label, 2, 1, 1, 2)

        self.mdt_connect_button = QPushButton("Połącz")
        self.mdt_port_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout.addWidget(QLabel("Port:"), 3, 0)
        layout.addWidget(self.mdt_port_combo, 3, 1)
        layout.addWidget(self.mdt_refresh_ports_button, 3, 2)
        layout.addWidget(self.mdt_connect_button, 3, 3)
