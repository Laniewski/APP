import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from modules.mdt694b.controller import MDT694BWorker
from modules.mdt694b.driver import MDT694BDriver, MDT694BError
from modules.mdt694b.panel import MDT694BPanel
from modules.measurement.controller import MeasurementWorker


class FakeSerial:
    def __init__(self, replies, **kwargs):
        self.replies = [bytearray(reply) for reply in replies]
        self.active = bytearray()
        self.writes = []
        self.is_open = True
        self.kwargs = kwargs

    @property
    def in_waiting(self): return 0
    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def flush(self): pass
    def close(self): self.is_open = False

    def write(self, data):
        self.writes.append(data)
        self.active = self.replies.pop(0)
        return len(data)

    def read(self, count):
        data = bytes(self.active[:count])
        del self.active[:count]
        return data


class MDT694BDriverTests(unittest.TestCase):
    def driver(self, replies):
        fake = FakeSerial(replies)
        driver = MDT694BDriver("COM1", timeout=0.001, settle_time=0,
                              serial_factory=lambda **_kwargs: fake)
        driver._serial = fake
        return driver, fake

    def test_parser_handles_echo_brackets_and_both_prompts(self):
        driver, _ = self.driver([b"xvoltage?\r[  1.21]\r>", b"vlimit?\r[ 150]\r*"])
        self.assertEqual(driver.read_voltage(), 1.21)
        self.assertEqual(driver.read_voltage_limit(), 150.0)

    def test_error_marker_and_missing_prompt(self):
        driver, _ = self.driver([b"xvoltage?\r!\r>"])
        with self.assertRaises(MDT694BError):
            driver.read_voltage()
        driver, _ = self.driver([b"xvoltage?\r1.0\r"])
        with self.assertRaises(TimeoutError):
            driver.read_voltage()

    def test_set_returns_device_readback_without_strict_comparison(self):
        replies = [b"xmin?\r0\r>", b"xmax?\r150.50\r>",
                   b"sysmin?\r0\r>", b"sysmax?\r150\r>",
                   b"vlimit?\r150\r>", b"xvoltage=1.000\r>",
                   b"xvoltage?\r[  1.21]\r>"]
        driver, fake = self.driver(replies)
        self.assertEqual(driver.set_voltage(1.0), 1.21)
        self.assertIn(b"xvoltage=1.000\r", fake.writes)

    def test_effective_range_and_idempotent_disconnect(self):
        replies = [b"xmin?\r1\r>", b"xmax?\r150.5\r>",
                   b"sysmin?\r0\r>", b"sysmax?\r160\r>", b"vlimit?\r2\r>"]
        driver, fake = self.driver(replies)
        self.assertEqual(driver.read_voltage_range(), (1.0, 150.0))
        driver.disconnect()
        driver.disconnect()
        self.assertFalse(fake.is_open)

    def test_voltage_range_is_cached_for_repeated_voltage_commands(self):
        replies = [b"xmin?\r0\r>", b"xmax?\r150\r>",
                   b"sysmin?\r0\r>", b"sysmax?\r150\r>", b"vlimit?\r150\r>",
                   b"xvoltage=10.000\r>", b"xvoltage?\r10\r>",
                   b"xvoltage=20.000\r>", b"xvoltage?\r20\r>"]
        driver, fake = self.driver(replies)
        driver.set_voltage(10.0)
        driver.set_voltage(20.0)
        self.assertEqual(fake.writes.count(b"xmin?\r"), 1)
        self.assertEqual(fake.writes.count(b"vlimit?\r"), 1)


class FakeRampDriver:
    def __init__(self, voltage=20.0, voltage_range=(0.0, 150.0), fail=False):
        self.voltage = voltage
        self.voltage_range = voltage_range
        self.fail = fail
        self.values = []
        self.closed = False
        self.in_command = False
        self.overlap = False

    def read_voltage_range(self):
        return self.voltage_range

    def read_voltage(self):
        return self.voltage

    def set_voltage(self, value):
        if self.in_command:
            self.overlap = True
        self.in_command = True
        try:
            if self.fail:
                raise RuntimeError("serial failure")
            self.voltage = float(value)
            self.values.append(self.voltage)
            return self.voltage
        finally:
            self.in_command = False

    def close(self):
        self.closed = True


class MDT694BRampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def worker(self, voltage=20.0, voltage_range=(0.0, 150.0), fail=False):
        driver = FakeRampDriver(voltage, voltage_range, fail)
        worker = MDT694BWorker(ramp_interval_ms=50)
        worker._driver = driver
        worker._voltage_range = voltage_range
        worker._current_voltage = voltage
        return worker, driver

    def test_default_ramp_rate_in_panel_is_10_v_per_s(self):
        panel = MDT694BPanel()
        self.assertEqual(panel.mdt_ramp_rate_input.value(), 10.0)

    def test_increasing_ramp_uses_elapsed_time_and_hits_exact_target(self):
        worker, driver = self.worker(voltage=20.0)
        with patch("modules.mdt694b.controller.time.monotonic", side_effect=[100.0, 100.37, 106.1]):
            worker.start_ramp(80.0, 10.0)
            worker._ramp_tick()
            worker._ramp_tick()
        self.assertAlmostEqual(driver.values[0], 23.7)
        self.assertEqual(driver.values[-1], 80.0)
        self.assertIsNone(worker._ramp_timer)

    def test_decreasing_ramp(self):
        worker, driver = self.worker(voltage=80.0)
        with patch("modules.mdt694b.controller.time.monotonic", side_effect=[10.0, 12.25, 15.1]):
            worker.start_ramp(30.0, 10.0)
            worker._ramp_tick()
            worker._ramp_tick()
        self.assertAlmostEqual(driver.values[0], 57.5)
        self.assertEqual(driver.values[-1], 30.0)

    def test_user_stop_leaves_current_voltage_unchanged(self):
        worker, driver = self.worker(voltage=20.0)
        states = []
        worker.ramp_active_changed.connect(states.append)
        with patch("modules.mdt694b.controller.time.monotonic", side_effect=[1.0, 1.5]):
            worker.start_ramp(80.0, 10.0)
            worker._ramp_tick()
        voltage_at_stop = driver.voltage
        worker.stop_ramp()
        self.assertEqual(driver.voltage, voltage_at_stop)
        self.assertEqual(states[-1], False)
        self.assertIsNone(worker._ramp_timer)

    def test_disconnect_stops_ramp_without_zeroing_voltage(self):
        worker, driver = self.worker(voltage=20.0)
        with patch("modules.mdt694b.controller.time.monotonic", return_value=1.0):
            worker.start_ramp(80.0, 10.0)
        worker.disconnect_device()
        self.assertIsNone(worker._ramp_timer)
        self.assertEqual(driver.voltage, 20.0)
        self.assertTrue(driver.closed)

    def test_invalid_rates_and_out_of_range_target_are_rejected(self):
        for rate in (0.0, -1.0, float("nan"), float("inf")):
            worker, driver = self.worker(voltage_range=(10.0, 100.0))
            errors = []
            worker.command_error.connect(errors.append)
            worker.start_ramp(50.0, rate)
            self.assertTrue(errors)
            self.assertFalse(driver.values)
        worker, driver = self.worker(voltage_range=(10.0, 100.0))
        errors = []
        worker.command_error.connect(errors.append)
        worker.start_ramp(101.0, 10.0)
        self.assertTrue(errors)
        self.assertFalse(driver.values)

    def test_ramp_clamps_to_range_and_commands_do_not_overlap(self):
        worker, driver = self.worker(voltage=90.0, voltage_range=(0.0, 100.0))
        with patch("modules.mdt694b.controller.time.monotonic", side_effect=[0.0, 10.0]):
            worker.start_ramp(100.0, 50.0)
            worker._ramp_tick()
        self.assertEqual(driver.values, [100.0])
        self.assertFalse(driver.overlap)

    def test_communication_error_stops_ramp_and_disconnects(self):
        worker, driver = self.worker(fail=True)
        errors = []
        worker.error.connect(errors.append)
        with patch("modules.mdt694b.controller.time.monotonic", side_effect=[0.0, 0.1]):
            worker.start_ramp(30.0, 10.0)
            worker._ramp_tick()
        self.assertIsNone(worker._ramp_timer)
        self.assertTrue(driver.closed)
        self.assertTrue(errors)

    def test_ramp_and_ads_sampling_can_remain_active_together(self):
        class FakeMeasurementDriver:
            def connect(self): pass
            def start_measurement(self): pass
            def read_sample(self): return 1.0, 2.0
            def stop_measurement(self): pass
            def close(self): pass

        measurement = MeasurementWorker(FakeMeasurementDriver, sample_interval_ms=10)
        samples = []
        measurement.sample_ready.connect(lambda *sample: samples.append(sample))
        ramp, _ = self.worker(voltage=20.0)
        try:
            measurement.start_measurement()
            with patch("modules.mdt694b.controller.time.monotonic", return_value=0.0):
                ramp.start_ramp(30.0, 10.0)
            measurement._read_once()
            self.assertTrue(measurement._running)
            self.assertTrue(measurement._timer.isActive())
            self.assertTrue(ramp._ramp_timer.isActive())
            self.assertEqual(len(samples), 1)
        finally:
            measurement.stop_measurement()
            ramp.stop_ramp()


if __name__ == "__main__":
    unittest.main()
