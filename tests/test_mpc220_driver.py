import struct
import unittest

from modules.mpc220.driver import MPC220Driver
from vendor import thorlabs_apt_protocol as apt


class FakeSerial:
    def __init__(self, responses=b"", **kwargs):
        self.kwargs = kwargs
        self.buffer = bytearray(responses)
        self.writes = []
        self.is_open = True
        self.close_count = 0

    @property
    def in_waiting(self):
        return len(self.buffer)

    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def flush(self): pass

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def read(self, count):
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def close(self):
        self.close_count += 1
        self.is_open = False


def position_frame(channel=1, position=-123, message_id=0x0412,
                   destination=0x01, source=0x50):
    return struct.pack("<HHBBHi", message_id, 6, destination | 0x80,
                       source, channel, position)


class MPC220DriverTests(unittest.TestCase):
    def test_connect_frames_and_serial_settings(self):
        serial_port = FakeSerial()
        driver = MPC220Driver("COM7", serial_factory=lambda **kwargs:
                              (setattr(serial_port, "kwargs", kwargs) or serial_port))
        driver.connect()
        self.assertEqual(serial_port.kwargs["baudrate"], 115200)
        self.assertTrue(serial_port.kwargs["rtscts"])
        self.assertEqual(serial_port.writes, [
            apt.hw_no_flash_programming(0x50, 0x01),
            apt.mod_set_chanenablestate(0x50, 0x01, 0x03, 0x01),
        ])

    def test_move_absolute_frame_and_paddle_validation(self):
        serial_port = FakeSerial()
        driver = MPC220Driver("x", serial_factory=lambda **_kwargs: serial_port)
        driver.ser = serial_port
        driver.move_absolute_units(2, 753)
        self.assertEqual(serial_port.writes[-1], apt.mot_move_absolute(0x50, 1, 2, 753))
        with self.assertRaises(ValueError):
            driver.move_absolute_units(3, 0)

    def test_signed_position_and_full_frame_validation(self):
        for changes in ({}, {"message_id": 1}, {"channel": 2},
                        {"source": 0x51}, {"destination": 2}):
            serial_port = FakeSerial(position_frame(**changes))
            driver = MPC220Driver("x", timeout=0.001,
                                  serial_factory=lambda **_kwargs: serial_port)
            driver.ser = serial_port
            if changes:
                with self.assertRaises((RuntimeError, TimeoutError)):
                    driver.read_position_units(1)
            else:
                self.assertEqual(driver.read_position_units(1), -123)

    def test_incomplete_response_times_out(self):
        serial_port = FakeSerial(position_frame()[:9])
        driver = MPC220Driver("x", timeout=0.001,
                              serial_factory=lambda **_kwargs: serial_port)
        driver.ser = serial_port
        with self.assertRaises(TimeoutError):
            driver.read_position_units(1)

    def test_close_is_idempotent(self):
        serial_port = FakeSerial()
        driver = MPC220Driver("x")
        driver.ser = serial_port
        driver.close()
        driver.close()
        self.assertEqual(serial_port.close_count, 1)


if __name__ == "__main__":
    unittest.main()
