"""GUI pomiaru ADS1263."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.measurement.channels import MEASUREMENT_CHANNELS
from app.widgets.log_panel import LogPanel


class MeasurementPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self.ads1263_panel = QGroupBox("ADS1263")
        ads_layout = QVBoxLayout(self.ads1263_panel)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget._dark_background = "#0b0f14"
        self.plot_widget.setBackground(self.plot_widget._dark_background)
        self.plot_widget.setLabel("bottom", "Czas [s]", **{"color": "#dfe7f3"})
        self.plot_widget.setLabel("left", "Napięcie [V]", **{"color": "#dfe7f3"})
        self.plot_widget.getAxis("bottom").setPen("#a9b6c5")
        self.plot_widget.getAxis("left").setPen("#a9b6c5")
        self.plot_widget.getAxis("bottom").setTextPen("#dfe7f3")
        self.plot_widget.getAxis("left").setTextPen("#dfe7f3")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.setXRange(0, 20, padding=0)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.getPlotItem().getViewBox().setMouseMode(pg.ViewBox.RectMode)
        self._auto_view_enabled = True
        self._measurement_running = False
        self._optimization_locked = False

        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.getPlotItem().legend.setBrush((30, 35, 42, 180))

        self.in0_curve = self.plot_widget.plot(
            [], [],
            pen=pg.mkPen(color="#38bdf8", width=2),
            name="IN0",
        )
        self.in1_curve = self.plot_widget.plot(
            [], [],
            pen=pg.mkPen(color="#f59e0b", width=2),
            name="IN1",
        )
        ads_layout.addWidget(self.plot_widget)

        layout.addWidget(self.ads1263_panel)
        layout.addWidget(self._create_channel_selection())
        layout.addLayout(self._create_measurement_buttons())
        self.log_panel = LogPanel()
        self.log_output = self.log_panel.log_output
        self.log_clear_button = self.log_panel.log_clear_button
        layout.addWidget(self.log_panel)

        self.plot_widget.getPlotItem().getViewBox().sigRangeChangedManually.connect(self._on_manual_range_changed)
        self._update_auto_button()
        self.set_measurement_running(False)

    def _create_channel_selection(self) -> QGroupBox:
        group = QGroupBox("Dane rejestrowane podczas pomiaru")
        layout = QVBoxLayout(group)
        self.measurement_channel_checkboxes = {}
        for channel in MEASUREMENT_CHANNELS:
            checkbox = QCheckBox(f"{channel.label} [{channel.unit}]")
            checkbox.setChecked(channel.default_enabled)
            self.measurement_channel_checkboxes[channel.key] = checkbox
            layout.addWidget(checkbox)
        return group

    def get_selected_measurement_channels(self) -> list[str]:
        return [
            channel.key
            for channel in MEASUREMENT_CHANNELS
            if self.measurement_channel_checkboxes[channel.key].isChecked()
        ]

    def _create_measurement_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.measurement_start_button = QPushButton("Rozpocznij pomiar")
        self.measurement_stop_button = QPushButton("Zatrzymaj pomiar")
        self.plot_clear_button = QPushButton("Wyczyść wykres")
        self.auto_view_button = QPushButton("Auto: WŁ.")
        self.auto_view_button.setCheckable(True)
        self.data_save_button = QPushButton("Zapisz dane")

        self.plot_clear_button.clicked.connect(self.clear_plot)
        self.auto_view_button.clicked.connect(self._toggle_auto_view)

        layout.addWidget(self.measurement_start_button)
        layout.addWidget(self.measurement_stop_button)
        layout.addWidget(self.plot_clear_button)
        layout.addWidget(self.auto_view_button)
        layout.addWidget(self.data_save_button)
        layout.addStretch()

        return layout

    def set_measurement_running(self, running: bool) -> None:
        self._measurement_running = bool(running)
        self.measurement_start_button.setEnabled(not running)
        self.measurement_stop_button.setEnabled(running and not self._optimization_locked)
        for checkbox in self.measurement_channel_checkboxes.values():
            checkbox.setEnabled(not running)
        if self._optimization_locked:
            for button in self.findChildren(QPushButton):
                button.setEnabled(False)

    def set_optimization_locked(self, locked: bool) -> None:
        self._optimization_locked = bool(locked)
        self.set_measurement_running(self._measurement_running)

    def _set_auto_view_enabled(self, enabled: bool) -> None:
        self._auto_view_enabled = bool(enabled)
        self._update_auto_button()
        if self._auto_view_enabled:
            self._apply_auto_view()
        else:
            self.plot_widget.disableAutoRange(axis="y")

    def _toggle_auto_view(self) -> None:
        self._set_auto_view_enabled(not self._auto_view_enabled)

    def _apply_auto_view(self) -> None:
        if not self.in0_curve or not self.in1_curve:
            self.plot_widget.setXRange(0, 20, padding=0)
            self.plot_widget.enableAutoRange(axis="y")
            return

        data_x = self.in0_curve.getData()[0]
        if data_x is None or len(data_x) == 0:
            self.plot_widget.setXRange(0, 20, padding=0)
            self.plot_widget.enableAutoRange(axis="y")
            return

        latest_time = float(max(data_x))
        if latest_time <= 20.0:
            x_min, x_max = 0.0, 20.0
        else:
            x_min = latest_time - 20.0
            x_max = latest_time
        self.plot_widget.setXRange(x_min, x_max, padding=0)
        self.plot_widget.enableAutoRange(axis="y")

    def _update_auto_button(self) -> None:
        if hasattr(self, "auto_view_button"):
            self.auto_view_button.setChecked(self._auto_view_enabled)
            self.auto_view_button.setText("Auto: WŁ." if self._auto_view_enabled else "Auto: WYŁ.")

    def _on_manual_range_changed(self, *args) -> None:
        self._set_auto_view_enabled(False)

    def update_plot(self, times, in0_values, in1_values) -> None:
        self.in0_curve.setData(times, in0_values)
        self.in1_curve.setData(times, in1_values)
        if self._auto_view_enabled:
            self._apply_auto_view()

    def clear_plot(self) -> None:
        self.in0_curve.setData([], [])
        self.in1_curve.setData([], [])
        self._set_auto_view_enabled(True)
        self.plot_widget.setXRange(0, 20, padding=0)
        self.plot_widget.enableAutoRange(axis="y")

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
