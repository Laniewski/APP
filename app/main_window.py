"""Główne okno aplikacji, bez logiki komunikacji z urządzeniami."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modules.mdt694b.panel import MDT694BPanel
from modules.measurement.panel import MeasurementPanel
from modules.mpc220.panel import MPC220Panel
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
        layout = QVBoxLayout(content)

        self.tc200_panel = TC200Panel()
        layout.addWidget(self.tc200_panel)

        self.mdt694b_panel = self._create_mdt_panel()
        layout.addWidget(self.mdt694b_panel)

        self.mpc220_panel = self._create_mpc_panel()
        layout.addWidget(self.mpc220_panel)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumWidth(420)

        return scroll

    def _create_mdt_panel(self) -> MDT694BPanel:
        panel = MDT694BPanel()
        self.mdt_current_voltage_label = panel.mdt_current_voltage_label
        self.mdt_setpoint_spinbox = panel.mdt_setpoint_spinbox
        self.mdt_set_button = panel.mdt_set_button
        self.mdt_status_label = panel.mdt_status_label
        self.mdt_port_combo = panel.mdt_port_combo
        self.mdt_refresh_ports_button = panel.mdt_refresh_ports_button
        self.mdt_connect_button = panel.mdt_connect_button
        return panel

    def _create_mpc_panel(self) -> MPC220Panel:
        panel = MPC220Panel()
        self.mpc_status_label = panel.mpc_status_label
        self.mpc_port_combo = panel.mpc_port_combo
        self.mpc_refresh_ports_button = panel.mpc_refresh_ports_button
        self.mpc_connect_button = panel.mpc_connect_button

        for index in (1, 2):
            setattr(self, f"mpc{index}_left_large_button", getattr(panel, f"mpc{index}_left_large_button"))
            setattr(self, f"mpc{index}_left_medium_button", getattr(panel, f"mpc{index}_left_medium_button"))
            setattr(self, f"mpc{index}_left_small_button", getattr(panel, f"mpc{index}_left_small_button"))
            setattr(self, f"mpc{index}_position_label", getattr(panel, f"mpc{index}_position_label"))
            setattr(self, f"mpc{index}_target_spinbox", getattr(panel, f"mpc{index}_target_spinbox"))
            setattr(self, f"mpc{index}_set_button", getattr(panel, f"mpc{index}_set_button"))
            setattr(self, f"mpc{index}_right_small_button", getattr(panel, f"mpc{index}_right_small_button"))
            setattr(self, f"mpc{index}_right_medium_button", getattr(panel, f"mpc{index}_right_medium_button"))
            setattr(self, f"mpc{index}_right_large_button", getattr(panel, f"mpc{index}_right_large_button"))

        return panel

    def _create_measurement_column(self) -> QWidget:
        self.measurement_panel = MeasurementPanel()
        self.ads1263_panel = self.measurement_panel.ads1263_panel
        self.plot_widget = self.measurement_panel.plot_widget
        self.in0_curve = self.measurement_panel.in0_curve
        self.in1_curve = self.measurement_panel.in1_curve
        self.measurement_start_button = self.measurement_panel.measurement_start_button
        self.measurement_stop_button = self.measurement_panel.measurement_stop_button
        self.plot_clear_button = self.measurement_panel.plot_clear_button
        self.data_save_button = self.measurement_panel.data_save_button
        self.log_panel = self.measurement_panel.log_panel
        self.log_output = self.measurement_panel.log_output
        self.log_clear_button = self.measurement_panel.log_clear_button
        self.append_log = self.measurement_panel.append_log
        self.clear_log = self.measurement_panel.clear_log
        self._clear_plot = self.measurement_panel.clear_plot
        return self.measurement_panel

    def _clear_plot(self) -> None:
        self.in0_curve.setData([], [])
        self.in1_curve.setData([], [])

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def clear_log(self) -> None:
        self.log_output.clear()
