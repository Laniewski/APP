"""GUI pomiaru ADS1263."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.widgets.log_panel import LogPanel


class MeasurementPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self.ads1263_panel = QGroupBox("ADS1263")
        ads_layout = QVBoxLayout(self.ads1263_panel)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("w")
        self.plot_widget.setLabel("bottom", "Czas [s]")
        self.plot_widget.setLabel("left", "Napięcie [V]")
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setXRange(0, 20, padding=0)

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
        ads_layout.addWidget(self.plot_widget)

        layout.addWidget(self.ads1263_panel)
        layout.addLayout(self._create_measurement_buttons())
        self.log_panel = LogPanel()
        self.log_output = self.log_panel.log_output
        self.log_clear_button = self.log_panel.log_clear_button
        layout.addWidget(self.log_panel)

        self.set_measurement_running(False)

    def _create_measurement_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.measurement_start_button = QPushButton("Rozpocznij pomiar")
        self.measurement_stop_button = QPushButton("Zatrzymaj pomiar")
        self.plot_clear_button = QPushButton("Wyczyść wykres")
        self.data_save_button = QPushButton("Zapisz dane")

        self.plot_clear_button.clicked.connect(self.clear_plot)

        layout.addWidget(self.measurement_start_button)
        layout.addWidget(self.measurement_stop_button)
        layout.addWidget(self.plot_clear_button)
        layout.addWidget(self.data_save_button)
        layout.addStretch()

        return layout

    def set_measurement_running(self, running: bool) -> None:
        self.measurement_start_button.setEnabled(not running)
        self.measurement_stop_button.setEnabled(running)

    def update_plot(self, times, in0_values, in1_values) -> None:
        self.in0_curve.setData(times, in0_values)
        self.in1_curve.setData(times, in1_values)
        if times:
            max_time = max(times)
            self.plot_widget.setXRange(max(0.0, max_time - 20.0), max_time + 0.5, padding=0)
            self.plot_widget.enableAutoRange(axis="y")

    def clear_plot(self) -> None:
        self.in0_curve.setData([], [])
        self.in1_curve.setData([], [])
        self.plot_widget.setXRange(0, 20, padding=0)

    def append_log(self, message: str) -> None:
        self.log_panel.append_log(message)

    def clear_log(self) -> None:
        self.log_panel.clear_log()

    def show_error(self, message: str) -> None:
        self.append_log(message)

    def choose_save_path(self, callback) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Zapisz dane pomiarowe",
            "",
            "Pliki CSV (*.csv)",
        )
        if path:
            callback(path)
