import unittest
from types import SimpleNamespace

from app.port_manager import PortManager


class PortManagerTests(unittest.TestCase):
    def test_listing_reservation_and_release(self):
        manager = PortManager(
            lambda: [SimpleNamespace(device="/dev/ttyUSB0", description="USB RS232")]
        )
        self.assertEqual(manager.list_ports()[0].device, "/dev/ttyUSB0")
        first, second = object(), object()
        self.assertTrue(manager.reserve("/dev/ttyUSB0", first))
        self.assertFalse(manager.is_available("/dev/ttyUSB0"))
        self.assertFalse(manager.reserve("/dev/ttyUSB0", second))
        manager.release("/dev/ttyUSB0", second)
        self.assertFalse(manager.is_available("/dev/ttyUSB0"))
        manager.release("/dev/ttyUSB0", first)
        self.assertTrue(manager.is_available("/dev/ttyUSB0"))


if __name__ == "__main__":
    unittest.main()
