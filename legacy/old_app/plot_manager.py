"""Obsługa danych wykresu, skali, czyszczenia i później zapisu próbek."""

import pyqtgraph as pg

class PlotManager:
    def __init__(self, window) -> None:
        self.window = window
        self.time_data: list[float] = []
        self.voltage_in0_data: list[float] = []
        self.voltage_in1_data: list[float] = []

        self.curve_in0 = self.window.plot_widget.plot(pen="#1f77b4", name="Detektor 1 — IN0")
        self.curve_in1 = self.window.plot_widget.plot(pen="#d62728", name="Detektor 2 — IN1")
        self.window.plot_widget.addLegend()

    def add_sample(self, time_value: float, voltage_in0: float, voltage_in1: float) -> None:
        self.time_data.append(time_value)
        self.voltage_in0_data.append(voltage_in0)
        self.voltage_in1_data.append(voltage_in1)

        # Prezentujemy tylko ostatnie 20 sekund danych.
        x_max = max(20.0, time_value)
        x_min = max(0.0, time_value - 20.0)

        visible_times = []
        visible_in0 = []
        visible_in1 = []
        for t, v0, v1 in zip(self.time_data, self.voltage_in0_data, self.voltage_in1_data):
            if x_min <= t <= x_max:
                visible_times.append(t)
                visible_in0.append(v0)
                visible_in1.append(v1)

        self.curve_in0.setData(visible_times, visible_in0)
        self.curve_in1.setData(visible_times, visible_in1)
        self.window.plot_widget.setXRange(x_min, x_max, padding=0)

    def clear_plot(self) -> None:
        self.time_data.clear()
        self.voltage_in0_data.clear()
        self.voltage_in1_data.clear()
        self.curve_in0.setData([], [])
        self.curve_in1.setData([], [])
        self.window.plot_widget.setXRange(0.0, 20.0, padding=0)

    def apply_manual_scale(self) -> None:
        x_min = self.window.x_min_input.value()
        x_max = self.window.x_max_input.value()
        y_min = self.window.y_min_input.value()
        y_max = self.window.y_max_input.value()
        self.window.plot_widget.setXRange(x_min, x_max)
        self.window.plot_widget.setYRange(y_min, y_max)

    def enable_auto_scale(self) -> None:
        self.window.plot_widget.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis)

    def get_data(self) -> tuple[list[float], list[float], list[float]]:
        return self.time_data, self.voltage_in0_data, self.voltage_in1_data
