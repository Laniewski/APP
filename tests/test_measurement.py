import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtWidgets import QApplication

from modules.measurement.controller import MeasurementController, MeasurementWorker
from modules.measurement.data_buffer import DataBuffer
from modules.measurement.driver import ADS1263Driver
from modules.measurement.panel import MeasurementPanel
from modules.measurement.vendor.ADS1263 import ADS1263, ADS1263_REG
import modules.measurement.vendor.config as measurement_config
import modules.measurement.vendor.ADS1263 as waveshare_adc


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

    def test_visible_window_tracks_last_20_seconds(self):
        buffer = DataBuffer()
        for offset in (0.0, 5.0, 10.0, 30.0):
            buffer.add_sample(offset, offset, offset + 1)
        visible = buffer.get_visible_data(window_seconds=20.0)
        self.assertEqual(visible[0], [10.0, 30.0])
        self.assertEqual(visible[1], [10.0, 30.0])
        self.assertEqual(visible[2], [11.0, 31.0])

    def test_working_backend_is_reset_after_close(self):
        class FakeBackend:
            def module_exit(self):
                pass

        measurement_config._backend = FakeBackend()
        measurement_config.module_exit()
        self.assertIsNone(measurement_config._backend)

    def test_worker_can_restart_after_failed_start(self):
        attempts = {"count": 0}

        class FailingThenWorkingDriver:
            def connect(self):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("boom")

            def start_measurement(self):
                pass

            def read_sample(self):
                return 1.0, 2.0

            def stop_measurement(self):
                pass

            def close(self):
                pass

        worker = MeasurementWorker(lambda: FailingThenWorkingDriver(), sample_interval_ms=5)
        finished_events = []
        errors = []
        worker.finished.connect(lambda: finished_events.append("finished"))
        worker.error.connect(errors.append)

        worker.start_measurement()
        self.assertEqual(len(finished_events), 0)
        self.assertEqual(len(errors), 1)
        self.assertFalse(worker._running)

        worker.start_measurement()
        self.assertTrue(worker._running)
        worker.stop_measurement()

    def test_driver_close_does_not_double_close_backend(self):
        class FakeADC:
            def __init__(self):
                self.module_exit_calls = 0

            def module_exit(self):
                self.module_exit_calls += 1

        fake_driver = ADS1263Driver()
        fake_backend = FakeADC()
        fake_driver._adc = fake_backend

        fake_driver.close()

        self.assertEqual(fake_backend.module_exit_calls, 1)
        self.assertIsNone(fake_driver._adc)


class ADS1263HardwareProtocolTests(unittest.TestCase):
    def setUp(self):
        self.adc = ADS1263()
        self.register_writes = []

    def test_single_ended_channels_use_aincom(self):
        self.adc.ADS1263_WriteReg = lambda register, value: self.register_writes.append(
            (register, value)
        )
        self.adc.ADS1263_SetChannal(0)
        self.adc.ADS1263_SetChannal(1)
        self.assertEqual(self.register_writes, [
            (ADS1263_REG["REG_INPMUX"], 0x0A),
            (ADS1263_REG["REG_INPMUX"], 0x1A),
        ])

    def test_hardware_configuration_matches_working_main_driver(self):
        self.adc.ADS1263_WriteReg = lambda register, value: self.register_writes.append(
            (register, value)
        )
        self.adc.ADS1263_ConfigADC(0, 0x08)
        self.assertIn((ADS1263_REG["REG_MODE2"], 0x88), self.register_writes)
        self.assertIn((ADS1263_REG["REG_REFMUX"], 0x24), self.register_writes)
        self.assertIn((ADS1263_REG["REG_MODE0"], 0x03), self.register_writes)
        self.assertIn((ADS1263_REG["REG_MODE1"], 0x84), self.register_writes)

    def _checksum(self, raw):
        total = 0x9B
        value = raw
        while value:
            total += value & 0xFF
            value >>= 8
        return total & 0xFF

    def test_adc1_reads_four_data_bytes_and_checksum(self):
        reads = [[0x40], [0x12, 0x34, 0x56, 0x78, self._checksum(0x12345678)]]
        counts = []
        with patch.object(waveshare_adc.config, "digital_write"), \
             patch.object(waveshare_adc.config, "spi_writebyte"), \
             patch.object(waveshare_adc.config, "spi_readbytes",
                          side_effect=lambda count: counts.append(count) or reads.pop(0)):
            self.assertEqual(self.adc.ADS1263_Read_ADC_Data(), 0x12345678)
        self.assertEqual(counts, [1, 5])

    def test_invalid_checksum_and_short_frame_raise(self):
        for frame in ([0, 0, 0, 1, 0], [0, 0, 0]):
            reads = [[0x40], frame]
            with patch.object(waveshare_adc.config, "digital_write"), \
                 patch.object(waveshare_adc.config, "spi_writebyte"), \
                 patch.object(waveshare_adc.config, "spi_readbytes", side_effect=reads):
                with self.assertRaises(RuntimeError):
                    self.adc.ADS1263_Read_ADC_Data()

    def test_bad_chip_id_fails_initialization(self):
        self.adc.ADS1263_reset = lambda: None
        self.adc.ADS1263_ReadChipID = lambda: 0
        with self.assertRaisesRegex(RuntimeError, "Chip ID"):
            self.adc.ADS1263_init_ADC1()

    def test_signed_voltage_conversion_and_full_scale(self):
        driver = ADS1263Driver(reference_voltage=5.0)
        self.assertAlmostEqual(driver._raw_to_voltage(0x7FFFFFFF), 5.0)
        self.assertLess(driver._raw_to_voltage(0xFFFFFFFF), 0.0)
        self.assertAlmostEqual(
            driver._raw_to_voltage(0x80000000),
            -5.0,
            places=6,
        )

    def test_read_sample_reads_in0_and_in1_separately(self):
        class FakeADC:
            def __init__(self): self.channels = []
            def ADS1263_GetChannalValue(self, channel):
                self.channels.append(channel)
                return 0x10000000 if channel == 0 else 0x20000000

        driver = ADS1263Driver()
        driver._adc = FakeADC()
        driver._connected = True
        in0, in1 = driver.read_sample()
        self.assertEqual(driver._adc.channels, [0, 1])
        self.assertNotEqual(in0, in1)

    def test_connect_initializes_backend_exactly_once(self):
        class FakeADC:
            def ADS1263_init_ADC1(self, rate): return 0
            def ADS1263_SetMode(self, mode): self.mode = mode
            def module_exit(self): pass

        with patch.object(measurement_config, "module_init", return_value=0) as init, \
             patch.object(waveshare_adc, "ADS1263", return_value=FakeADC()):
            driver = ADS1263Driver()
            driver.connect()
            self.assertEqual(init.call_count, 1)
            self.assertEqual(driver._adc.mode, 0)
            driver.close()

    def test_backend_initialization_error_prevents_connection(self):
        with patch.object(measurement_config, "module_init", return_value=-1):
            driver = ADS1263Driver()
            with self.assertRaisesRegex(RuntimeError, "GPIO/SPI"):
                driver.connect()
            self.assertFalse(driver._connected)


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

    def test_panel_auto_mode_is_enabled_by_default(self):
        panel = MeasurementPanel()
        self.assertTrue(panel._auto_view_enabled)
        self.assertEqual(panel.auto_view_button.text(), "Auto: WŁ.")

    def test_panel_auto_range_for_recent_time(self):
        panel = MeasurementPanel()
        panel.in0_curve.setData([0.0, 5.0, 12.0], [1.0, 2.0, 3.0])
        panel.in1_curve.setData([0.0, 5.0, 12.0], [5.0, 4.0, 3.0])
        panel._apply_auto_view()
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 0.0, delta=1e-6)
        self.assertAlmostEqual(x_max, 20.0, delta=1e-6)

    def test_panel_auto_range_for_latest_time_over_20_seconds(self):
        panel = MeasurementPanel()
        panel.in0_curve.setData([0.0, 10.0, 35.0], [1.0, 2.0, 3.0])
        panel.in1_curve.setData([0.0, 10.0, 35.0], [5.0, 4.0, 3.0])
        panel._apply_auto_view()
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 15.0, delta=0.05)
        self.assertAlmostEqual(x_max, 35.0, delta=0.05)

    def test_manual_range_disables_auto_and_is_preserved(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(False)
        panel.plot_widget.setXRange(2.0, 7.0, padding=0)
        panel.update_plot([0.0, 100.0], [0.0, 1.0], [0.0, 1.0])
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 2.0, delta=0.05)
        self.assertAlmostEqual(x_max, 7.0, delta=0.05)
        self.assertFalse(panel._auto_view_enabled)

    def test_auto_button_restores_auto_range(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(False)
        panel.plot_widget.setXRange(2.0, 7.0, padding=0)
        panel._toggle_auto_view()
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 0.0, delta=1e-6)
        self.assertAlmostEqual(x_max, 20.0, delta=1e-6)
        self.assertTrue(panel._auto_view_enabled)

    def test_clear_plot_restores_auto_and_default_range(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(False)
        panel.plot_widget.setXRange(2.0, 7.0, padding=0)
        panel.clear_plot()
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 0.0, delta=1e-6)
        self.assertAlmostEqual(x_max, 20.0, delta=1e-6)
        self.assertTrue(panel._auto_view_enabled)

    def test_plot_background_is_dark(self):
        panel = MeasurementPanel()
        self.assertEqual(panel.plot_widget._dark_background, "#0b0f14")

    def test_buffer_keeps_full_history_even_when_auto_window_is_20s(self):
        buffer = DataBuffer()
        for offset in range(0, 61, 10):
            buffer.add_sample(float(offset), float(offset), float(offset + 1))
        times, in0, in1 = buffer.get_all_data()
        self.assertEqual(len(times), 7)
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times[-1], 60.0)
        self.assertEqual(len(in0), 7)
        self.assertEqual(len(in1), 7)

    def test_update_plot_receives_full_history_and_auto_view_is_windowed(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(True)
        times = [0.0, 10.0, 20.0, 40.0, 60.0]
        in0 = [0.0, 1.0, 2.0, 3.0, 4.0]
        in1 = [10.0, 11.0, 12.0, 13.0, 14.0]
        panel.update_plot(times, in0, in1)
        self.assertEqual(len(panel.in0_curve.getData()[0]), 5)
        self.assertEqual(len(panel.in1_curve.getData()[0]), 5)
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 40.0, delta=0.05)
        self.assertAlmostEqual(x_max, 60.0, delta=0.05)

    def test_manual_range_keeps_full_history_and_ignores_auto_updates(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(False)
        panel.plot_widget.setXRange(0.0, 60.0, padding=0)
        panel.update_plot([0.0, 20.0, 40.0, 60.0], [1.0, 2.0, 3.0, 4.0], [10.0, 11.0, 12.0, 13.0])
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 0.0, delta=0.05)
        self.assertAlmostEqual(x_max, 60.0, delta=0.05)
        self.assertEqual(len(panel.in0_curve.getData()[0]), 4)
        self.assertFalse(panel._auto_view_enabled)

    def test_auto_recovery_keeps_history_but_restores_window(self):
        panel = MeasurementPanel()
        panel._set_auto_view_enabled(False)
        panel.plot_widget.setXRange(0.0, 60.0, padding=0)
        panel.update_plot([0.0, 20.0, 40.0, 60.0], [1.0, 2.0, 3.0, 4.0], [10.0, 11.0, 12.0, 13.0])
        panel._toggle_auto_view()
        x_min, x_max = panel.plot_widget.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_min, 40.0, delta=0.05)
        self.assertAlmostEqual(x_max, 60.0, delta=0.05)
        self.assertEqual(len(panel.in0_curve.getData()[0]), 4)

    def test_csv_export_keeps_full_history_even_if_window_is_narrow(self):
        fake_path = os.path.join(tempfile.gettempdir(), "measurement_full_history.csv")
        if os.path.exists(fake_path):
            os.remove(fake_path)
        controller = MeasurementController(MeasurementPanel(), driver_factory=lambda: FakeDriver(), sample_interval_ms=10)
        try:
            for offset in range(0, 61, 10):
                controller.buffer.add_sample(float(offset), float(offset), float(offset + 1))
            controller.panel._set_auto_view_enabled(False)
            controller.panel.plot_widget.setXRange(10.0, 20.0, padding=0)
            controller.save_csv(fake_path)
            with open(fake_path, "r", encoding="utf-8") as handle:
                rows = handle.read().strip().splitlines()
            self.assertGreater(len(rows), 1)
            self.assertEqual(len(rows) - 1, len(controller.buffer.get_all_data()[0]))
        finally:
            controller.shutdown(timeout_ms=500)
            if os.path.exists(fake_path):
                os.remove(fake_path)

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
