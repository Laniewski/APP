"""GUI pomiaru ADS1263."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

    def clear_plot(self) -> None:
        self.in0_curve.setData([], [])
        self.in1_curve.setData([], [])

    def append_log(self, message: str) -> None:
        self.log_panel.append_log(message)

    def clear_log(self) -> None:
        self.log_panel.clear_log()
