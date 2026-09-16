"""Kontroler pomiarowy ADS1263 zgodny z architekturą TC200."""

from __future__ import annotations

import csv
import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot

from modules.measurement.data_buffer import DataBuffer

logger = logging.getLogger(__name__)


class MeasurementWorker(QObject):
    sample_ready = Signal(float, float)
    started = Signal()
    error = Signal(str)
    stopped = Signal()
    finished = Signal()

    def __init__(self, driver_factory: Callable[[], object], sample_interval_ms: int = 200) -> None:
        super().__init__()
        self._driver_factory = driver_factory
        self._sample_interval_ms = sample_interval_ms
        self._timer: QTimer | None = None
        self._driver = None
        self._running = False

    @Slot()
    def start_measurement(self) -> None:
        if self._running:
            return
        try:
            self._driver = self._driver_factory()
            self._driver.connect()
            self._driver.start_measurement()
            self._running = True
            if self._timer is not None:
                self._timer.stop()
                self._timer.deleteLater()
            self._timer = QTimer(self)
            self._timer.setInterval(self._sample_interval_ms)
            self._timer.timeout.connect(self._read_once)
            self._timer.start()
            self.started.emit()
        except Exception as exc:
            logger.exception("Nie udało się uruchomić pomiaru ADS1263")
            self._running = False
            self._cleanup_driver()
            self.error.emit(f"ADS1263: {exc}")
            self.stopped.emit()

    @Slot()
    def _read_once(self) -> None:
        if not self._running or self._driver is None:
            return
        try:
            in0, in1 = self._driver.read_sample()
            self.sample_ready.emit(in0, in1)
        except Exception as exc:
            logger.exception("Błąd odczytu ADS1263")
            self.stop_measurement()
            self.error.emit(f"ADS1263: {exc}")

    @Slot()
    def stop_measurement(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._cleanup_driver()
        self.stopped.emit()

    def _cleanup_driver(self) -> None:
        if self._driver is not None:
            try:
                self._driver.stop_measurement()
            except Exception:
                pass
            try:
                self._driver.close()
            except Exception:
                pass
            self._driver = None

    @Slot()
    def shutdown(self) -> None:
        self.stop_measurement()
        self.finished.emit()
        QThread.currentThread().quit()


class MeasurementController(QObject):
    request_start = Signal()
    request_stop = Signal()
    request_clear = Signal()
    request_save = Signal(str)
    request_shutdown = Signal()

    def __init__(self, panel, driver_factory=None, sample_interval_ms: int = 200) -> None:
        super().__init__(panel)
        self.panel = panel
        self.buffer = DataBuffer()
        self._driver_factory = driver_factory or self._default_driver_factory
        self._sample_interval_ms = sample_interval_ms
        self._measurement_start = time.perf_counter()
        self._running = False
        self._active_channel_keys = self.panel.get_selected_measurement_channels()
        self._latest_temperature_c: float | None = None
        self._latest_piezo_voltage_v: float | None = None
        self._latest_paddle_angles_deg: dict[int, float | None] = {
            1: None,
            2: None,
        }
        self._thread = QThread(self)
        self.thread = self._thread
        self.worker = MeasurementWorker(self._driver_factory, sample_interval_ms)
        self.worker.moveToThread(self._thread)

        self.request_start.connect(self.worker.start_measurement, Qt.ConnectionType.QueuedConnection)
        self.request_stop.connect(self.worker.stop_measurement, Qt.ConnectionType.QueuedConnection)
        self.request_clear.connect(self.clear_data, Qt.ConnectionType.QueuedConnection)
        self.request_save.connect(self.save_csv, Qt.ConnectionType.QueuedConnection)
        self.request_shutdown.connect(self.worker.shutdown, Qt.ConnectionType.QueuedConnection)

        self.worker.started.connect(self._on_started)
        self.worker.sample_ready.connect(self._on_sample_ready)
        self.worker.error.connect(self._on_error)
        self.worker.stopped.connect(self._on_stopped)
        self._thread.finished.connect(self.worker.deleteLater)
        self._thread.start()

        self.panel.measurement_start_button.clicked.connect(self.start_measurement)
        self.panel.measurement_stop_button.clicked.connect(self.stop_measurement)
        self.panel.plot_clear_button.clicked.connect(self.clear_data)
        self.panel.data_save_button.clicked.connect(self._request_save)
        self.panel.set_measurement_running(False)

    @staticmethod
    def _default_driver_factory():
        from modules.measurement.driver import ADS1263Driver
        return ADS1263Driver()

    def _request_save(self) -> None:
        self.panel.choose_save_path(self.save_csv)

    def start_measurement(self) -> None:
        if self._running:
            return
        self._measurement_start = time.perf_counter()
        self.buffer.clear()
        self._active_channel_keys = self.panel.get_selected_measurement_channels()
        logger.debug("Selected channels: %s", self._active_channel_keys)
        self._running = True
        self.panel.set_measurement_running(True)
        self.request_start.emit()

    def stop_measurement(self) -> None:
        self._running = False
        self.panel.set_measurement_running(False)
        self.request_stop.emit()
        logger.info("Zatrzymano pomiar ADS1263.")

    def clear_data(self) -> None:
        self.buffer.clear()
        self.panel.clear_plot()

    def is_running(self) -> bool:
        return self._running

    def _on_sample_ready(self, in0: float, in1: float) -> None:
        relative_time = time.perf_counter() - self._measurement_start
        values = {
            "in0_v": float(in0),
            "in1_v": float(in1),
            # Wolniejsze urządzenia są odpytywane przez ich istniejące workery.
            # Rekord wykorzystuje ostatnią opublikowaną wartość, bez blokowania ADS1263.
            "temperature_c": self._latest_temperature_c,
            "piezo_voltage_v": self._latest_piezo_voltage_v,
            "paddle_1_angle_deg": self._latest_paddle_angles_deg[1],
            "paddle_2_angle_deg": self._latest_paddle_angles_deg[2],
        }
        selected_values = {key: values[key] for key in self._active_channel_keys}
        # IN0/IN1 pozostają w tym samym rekordzie jako źródło głównego wykresu,
        # nawet jeśli użytkownik wyłączy ich kolumny w eksporcie.
        selected_values.setdefault("in0_v", float(in0))
        selected_values.setdefault("in1_v", float(in1))
        record = self.buffer.add_record(relative_time, selected_values)
        if len(self.buffer.get_records()) == 1:
            logger.debug("First measurement record: %s", record)
        times, in0_values, in1_values = self.buffer.get_all_data()
        self.panel.update_plot(times, in0_values, in1_values)

    @Slot(float, float)
    def update_tc200_readings(self, temperature_c: float, _setpoint_c: float) -> None:
        self._latest_temperature_c = float(temperature_c)

    @Slot(float)
    def update_piezo_voltage(self, voltage_v: float) -> None:
        self._latest_piezo_voltage_v = float(voltage_v)

    @Slot(int, float)
    def update_paddle_angle(self, paddle_number: int, angle_deg: float) -> None:
        if paddle_number in self._latest_paddle_angles_deg:
            self._latest_paddle_angles_deg[paddle_number] = float(angle_deg)

    def _on_started(self) -> None:
        if not self._running:
            return
        self.panel.set_measurement_running(True)
        logger.info("Rozpoczęto pomiar ADS1263.")

    def _on_stopped(self) -> None:
        self._running = False
        self.panel.set_measurement_running(False)

    def _on_error(self, message: str) -> None:
        self._running = False
        self.panel.show_error(message)
        self.panel.set_measurement_running(False)
        logger.error(message)

    def save_csv(self, file_path: str | None = None) -> None:
        if not file_path:
            return
        records = self.buffer.get_records()
        if not records:
            self.panel.show_error("Brak danych do zapisania.")
            return
        fieldnames = ["time_s", *self._active_channel_keys]
        logger.debug("Records before export: %d", len(records))
        logger.debug("First record keys before export: %s", list(records[0]))
        logger.debug("CSV columns: %s", fieldnames)
        with open(file_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for record in records:
                writer.writerow({
                    key: self._format_csv_value(record.get(key))
                    for key in fieldnames
                })
        logger.info("Zapisano dane pomiarowe do %s", file_path)

    @staticmethod
    def _format_csv_value(value: float | None) -> str:
        return "" if value is None else f"{float(value):.6f}"

    def shutdown(self, timeout_ms: int = 3000) -> None:
        if self._thread.isRunning():
            self.request_stop.emit()
            self.request_shutdown.emit()
            if not self._thread.wait(timeout_ms):
                self._thread.quit()
                self._thread.wait(timeout_ms)
        self.panel.set_measurement_running(False)
