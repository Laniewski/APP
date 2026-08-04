import unittest

import serial

from modules.tc200.driver import (
    TC200ConnectionError,
    TC200Driver,
    TC200ResponseError,
    TC200TimeoutError,
)


class FakeSerial:
    def __init__(self, responses=None, **settings):
        self.responses = list(responses or [])
        self.settings = settings
        self.writes = []
        self.is_open = True
        self.closed_count = 0

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def read_until(self, terminator):
        self.last_terminator = terminator
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.is_open = False
        self.closed_count += 1


def connected_driver(*responses):
    fake = FakeSerial(responses)
    driver = TC200Driver("FAKE", serial_factory=lambda **kwargs: fake, settle_time=0)
    driver.connect()
    return driver, fake


class TC200DriverTests(unittest.TestCase):
    def test_missing_or_busy_port_has_clear_connection_error(self):
        def failing_factory(**_kwargs):
            raise serial.SerialException("port is busy")

        driver = TC200Driver("/dev/missing", serial_factory=failing_factory, settle_time=0)
        with self.assertRaisesRegex(TC200ConnectionError, "/dev/missing"):
            driver.connect()
        driver.close()

    def test_serial_settings_command_and_terminators(self):
        captured = {}

        def factory(**kwargs):
            captured.update(kwargs)
            return FakeSerial([b"tact?\r\n24.5\r\n>"])

        driver = TC200Driver("COM7", serial_factory=factory, settle_time=0)
        driver.connect()
        self.assertEqual(driver.read_temperature(), 24.5)
        self.assertEqual(captured["baudrate"], 115200)
        self.assertFalse(captured["xonxoff"])
        self.assertEqual(driver._serial.writes, [b"tact?\r"])
        self.assertEqual(driver._serial.last_terminator, b">")

    def test_response_with_echo_and_prompt_is_cleaned(self):
        driver, _ = connected_driver(b"\r\nTSET?\r\nTset = 51.2 C\r\n> ")
        self.assertEqual(driver.read_setpoint(), 51.2)

    def test_timeout_for_empty_response(self):
        driver, _ = connected_driver(b"")
        with self.assertRaises(TC200TimeoutError):
            driver.read_temperature()

    def test_timeout_without_prompt(self):
        driver, _ = connected_driver(b"tact?\r\n23.0")
        with self.assertRaises(TC200TimeoutError):
            driver.read_temperature()

    def test_empty_payload_before_prompt_is_invalid(self):
        driver, _ = connected_driver(b">")
        with self.assertRaises(TC200ResponseError):
            driver.send_command("tact?")

    def test_control_command_accepts_echo_and_prompt_only(self):
        driver, fake = connected_driver(b"ens\r\n>")
        self.assertEqual(driver.send_command("ens", allow_empty=True), "")
        self.assertEqual(fake.writes, [b"ens\r"])

    def test_device_error_is_invalid(self):
        driver, _ = connected_driver(b"Command error CMD_NOT_DEFINED\r\n>")
        with self.assertRaises(TC200ResponseError):
            driver.send_command("bad")

    def test_set_temperature_builds_command_and_reads_back(self):
        driver, fake = connected_driver(
            b"tset=37.4\r\n>",
            b"Tset = 37.4 C\r\n>",
        )
        self.assertEqual(driver.set_temperature(37.4), 37.4)
        self.assertEqual(fake.writes, [b"tset=37.4\r", b"tset?\r"])
        with self.assertRaises(ValueError):
            driver.set_temperature(201)

    def test_set_temperature_requires_matching_readback(self):
        driver, fake = connected_driver(
            b"tset=37.4\r\n>",
            b"Tset = 36.0 C\r\n>",
        )
        with self.assertRaisesRegex(
            TC200ResponseError,
            "nie potwierdził ustawionej temperatury",
        ):
            driver.set_temperature(37.4)
        self.assertEqual(fake.writes, [b"tset=37.4\r", b"tset?\r"])

    def test_heater_enable_and_disable(self):
        driver, fake = connected_driver(
            b"00\r\n>", b"ens\r\n>", b"01\r\n>",
            b"01\r\n>", b"ens\r\n>", b"00\r\n>",
        )
        self.assertTrue(driver.set_heater(True).heater_enabled)
        self.assertFalse(driver.set_heater(False).heater_enabled)
        self.assertEqual(fake.writes.count(b"ens\r"), 2)

    def test_heater_toggle_is_sent_only_once_when_not_confirmed(self):
        driver, fake = connected_driver(
            b"00\r\n>",
            b"ens\r\n>",
            b"00\r\n>",
        )
        with self.assertRaisesRegex(
            TC200ResponseError,
            "nie potwierdził zmiany stanu grzania",
        ):
            driver.set_heater(True)
        self.assertEqual(fake.writes, [b"stat?\r", b"ens\r", b"stat?\r"])
        self.assertEqual(fake.writes.count(b"ens\r"), 1)

    def test_heater_does_not_toggle_when_state_already_matches(self):
        driver, fake = connected_driver(b"01\r\n>")
        self.assertTrue(driver.set_heater(True).heater_enabled)
        self.assertEqual(fake.writes, [b"stat?\r"])

    def test_status_and_alarms(self):
        driver, _ = connected_driver(b"Status = D1\r\nTmax ERROR\r\n>")
        status = driver.read_status()
        self.assertTrue(status.heater_enabled)
        self.assertTrue(status.sensor_alarm)
        self.assertTrue(status.cycle_paused)
        self.assertTrue(status.tmax_alarm)
        self.assertEqual(status.units, "°C")

    def test_identification_rejects_other_device(self):
        driver, _ = connected_driver(b"Other Controller\r\n>")
        with self.assertRaises(TC200ResponseError):
            driver.identify()

    def test_close_is_idempotent(self):
        driver, fake = connected_driver()
        driver.close()
        driver.close()
        self.assertEqual(fake.closed_count, 1)
        self.assertFalse(driver.is_connected)


if __name__ == "__main__":
    unittest.main()
