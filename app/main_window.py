"""Główne okno aplikacji, bez logiki komunikacji z urządzeniami."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from modules.tc200.panel import TC200Panel


class MainWindow(QMainWindow):
    """Główne okno nowej aplikacji APPv2."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("APPv2 — Sterowanie stanowiskiem laboratoryjnym")
        self.resize(1250, 820)
        self.setMinimumSize(1000, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self._create_device_column())
        self.main_splitter.addWidget(self._create_measurement_column())
        self.main_splitter.setSizes([450, 800])
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 2)

        main_layout.addWidget(self.main_splitter)

    def _create_device_column(self) -> QWidget:
        content = QWidget()
        content_layout = QVBoxLayout(content)

        self.tc200_panel = TC200Panel()
        content_layout.addWidget(self.tc200_panel)

        self.mdt694b_panel = self._create_mdt_panel()
        content_layout.addWidget(self.mdt694b_panel)

        self.mpc220_panel = self._create_mpc_panel()
        content_layout.addWidget(self.mpc220_panel)
        content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumWidth(420)

        return scroll

    def _create_mdt_panel(self) -> QGroupBox:
        group = QGroupBox("MDT694B — sterownik piezo")
        layout = QGridLayout(group)

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

        return group

    def _create_mpc_panel(self) -> QGroupBox:
        group = QGroupBox("MPC220 — kontroler polaryzacji")
        layout = QVBoxLayout(group)

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

        return group

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

    def _create_measurement_column(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self.ads1263_panel = self._create_plot_panel()
        layout.addWidget(self.ads1263_panel)
        layout.addLayout(self._create_measurement_buttons())
        layout.addWidget(self._create_log_panel())

        return container

    def _create_plot_panel(self) -> QGroupBox:
        group = QGroupBox("ADS1263")
        layout = QVBoxLayout(group)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.setLabel("bottom", "Czas [s]")
        self.plot_widget.setLabel("left", "Napięcie [V]")
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True)

        self.in0_curve = self.plot_widget.plot(
            [], [],
            pen=pg.mkPen(color="#1f77b4", width=2),
            name="IN0",
        )
        self.in1_curve = self.plot_widget.plot(
            [], [],
            pen=pg.mkPen(color="#ff7f0e", width=2),
            name="IN1",
        )

        layout.addWidget(self.plot_widget)

        return group

    def _create_measurement_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.measurement_start_button = QPushButton("Rozpocznij pomiar")
        self.measurement_stop_button = QPushButton("Zatrzymaj pomiar")
        self.plot_clear_button = QPushButton("Wyczyść wykres")
        self.data_save_button = QPushButton("Zapisz dane")

        self.plot_clear_button.clicked.connect(self._clear_plot)

        layout.addWidget(self.measurement_start_button)
        layout.addWidget(self.measurement_stop_button)
        layout.addWidget(self.plot_clear_button)
        layout.addWidget(self.data_save_button)
        layout.addStretch()

        return layout

    def _create_log_panel(self) -> QGroupBox:
        group = QGroupBox("Logi")
        layout = QVBoxLayout(group)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.log_clear_button = QPushButton("Wyczyść log")
        self.log_clear_button.clicked.connect(self.log_output.clear)

        layout.addWidget(self.log_output)
        layout.addWidget(
            self.log_clear_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        return group

    def _clear_plot(self) -> None:
        self.in0_curve.setData([], [])
        self.in1_curve.setData([], [])

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
