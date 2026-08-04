import os
import tempfile
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

from modules.measurement.controller import MeasurementController
from modules.measurement.data_buffer import DataBuffer
from modules.measurement.panel import MeasurementPanel


class FakeDriver:
    def __init__(self):
        self.connected = False
        self.started = False
        self.samples = [(0.0, 1.0, 2.0), (0.1, 1.5, 2.5)]
        self.calls = []

    def connect(self):
        self.connected = True
        self.calls.append("connect")

    def start_measurement(self):
        self.started = True
        self.calls.append("start")

    def read_sample(self):
        if not self.started:
            raise RuntimeError("measurement not started")
        sample = self.samples.pop(0) if self.samples else (time.perf_counter(), 0.0, 0.0)
        return sample[1], sample[2]

    def stop_measurement(self):
        self.started = False
        self.calls.append("stop")

    def close(self):
        self.connected = False
        self.calls.append("close")


class DataBufferTests(unittest.TestCase):
    def test_buffer_adds_and_clears_samples(self):
        buffer = DataBuffer()
        buffer.add_sample(0.0, 1.0, 2.0)
        buffer.add_sample(0.5, 3.0, 4.0)
        self.assertEqual(buffer.get_all_data()[0], [0.0, 0.5])
        self.assertEqual(buffer.get_all_data()[1], [1.0, 3.0])
        self.assertEqual(buffer.get_all_data()[2], [2.0, 4.0])

        visible = buffer.get_visible_data(window_seconds=1.0)
        self.assertEqual(visible[0], [0.0, 0.5])
        buffer.clear()
        self.assertEqual(buffer.get_all_data(), ([], [], []))

    def test_visible_window_is_limited_to_20_seconds(self):
        buffer = DataBuffer()
        for offset in (0.0, 5.0, 10.0, 30.0):
            buffer.add_sample(offset, offset, offset + 1)
        visible = buffer.get_visible_data(window_seconds=20.0)
        self.assertEqual(len(visible[0]), 3)
        self.assertEqual(visible[0][-1], 10.0)


class MeasurementControllerTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.panel = MeasurementPanel()

    def tearDown(self):
        self.panel = None

    def test_start_stop_and_buffer_update(self):
        fake = FakeDriver()
        controller = MeasurementController(self.panel, driver_factory=lambda: fake, sample_interval_ms=10)
        try:
            controller.start_measurement()
            self.app.processEvents()
            time.sleep(0.05)
            self.assertTrue(controller.is_running())
            self.assertTrue(fake.started)
            controller.stop_measurement()
            self.app.processEvents()
            self.assertFalse(controller.is_running())
        finally:
            controller.shutdown(timeout_ms=500)

    def test_clear_and_save_csv(self):
        fake = FakeDriver()
        controller = MeasurementController(self.panel, driver_factory=lambda: fake, sample_interval_ms=10)
        try:
            controller.buffer.add_sample(0.0, 1.0, 2.0)
            controller.buffer.add_sample(1.0, 3.0, 4.0)
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
                path = tmp.name
            try:
                controller.save_csv(path)
                with open(path, "r", encoding="utf-8") as handle:
                    contents = handle.read()
                self.assertIn("time_s,in0_v,in1_v", contents)
            finally:
                os.remove(path)

            controller.clear_data()
            self.assertEqual(controller.buffer.get_all_data(), ([], [], []))
            controller.save_csv(path)
            self.assertFalse(os.path.exists(path))
        finally:
            controller.shutdown(timeout_ms=500)

    def test_hardware_unavailable_does_not_log_success_before_failure(self):
        class MissingHardwareDriver:
            def connect(self):
                raise RuntimeError("Na tym komputerze brakuje wsparcia Raspberry Pi GPIO/SPI dla ADS1263.")

            def start_measurement(self):
                pass

            def stop_measurement(self):
                pass

            def close(self):
                pass

        panel = MeasurementPanel()
        controller = MeasurementController(panel, driver_factory=lambda: MissingHardwareDriver(), sample_interval_ms=10)
        try:
            with self.assertLogs("modules.measurement.controller", level="ERROR") as captured:
                controller.start_measurement()
                for _ in range(10):
                    self.app.processEvents()
                    time.sleep(0.05)
            self.assertTrue(any("Nie udało się uruchomić pomiaru ADS1263" in entry for entry in captured.output))
            self.assertFalse(any("Rozpoczęto pomiar ADS1263" in entry for entry in captured.output))
            self.assertIn("ADS1263: Na tym komputerze brakuje wsparcia", panel.log_output.toPlainText())
        finally:
            controller.shutdown(timeout_ms=500)

    def test_panel_states_and_error(self):
        panel = MeasurementPanel()
        panel.set_measurement_running(False)
        self.assertFalse(panel.measurement_stop_button.isEnabled())
        panel.set_measurement_running(True)
        self.assertTrue(panel.measurement_stop_button.isEnabled())
        panel.show_error("błąd testowy")
        self.assertIn("błąd testowy", panel.log_output.toPlainText())


if __name__ == "__main__":
    unittest.main()
