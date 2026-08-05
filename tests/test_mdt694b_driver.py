import unittest

from modules.mdt694b.driver import MDT694BDriver, MDT694BError


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


if __name__ == "__main__":
    unittest.main()
