import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.port_manager import PortInfo, PortManager
from modules.mpc220.controller import MPC220Controller, MPC220Worker
from modules.mpc220.panel import MPC220Panel


class FakeDriver:
    instances = []

    def __init__(self, port):
        self.port = port
        self.positions = {1: 964, 2: 1717}
        self.moves = []
        self.closed = False
        self.__class__.instances.append(self)

    def connect(self): pass
    def close(self): self.closed = True
    def read_position_units(self, paddle): return self.positions[paddle]
    def wait_until_stopped(self, paddle): pass

    def move_absolute_units(self, paddle, units):
        self.moves.append((paddle, units))
        self.positions[paddle] = 964 + units


class MPC220ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_connect_publishes_both_positions_and_adjust_reads_driver(self):
        worker = MPC220Worker(FakeDriver)
        positions, busy = [], []
        worker.position_updated.connect(lambda p, a: positions.append((p, a)))
        worker.busy_changed.connect(busy.append)
        worker.connect_device("COM1")
        self.assertEqual(positions, [(1, 1.0), (2, 90.0)])
        worker._driver.positions[1] = 964 + 8 * 159
        worker.adjust_angle(1, 10)
        self.assertEqual(worker._driver.moves[-1], (1, 1339))
        self.assertEqual(busy[-1], False)

    def test_port_conflict_disconnect_release_and_shutdown(self):
        manager = PortManager(lambda: [])
        tc_owner = object()
        self.assertTrue(manager.reserve("COM1", tc_owner))
        panel = MPC220Panel()
        controller = MPC220Controller(panel, manager,
                                      lambda: MPC220Worker(FakeDriver))
        controller.connect("COM1")
        self.assertIsNone(controller._port)
        manager.release("COM1", tc_owner)
        controller.connect("COM1")
        self.assertEqual(controller._port, "COM1")
        controller._on_disconnected()
        self.assertTrue(manager.is_available("COM1"))
        controller.shutdown()
        self.assertFalse(controller.thread.isRunning())


if __name__ == "__main__":
    unittest.main()
