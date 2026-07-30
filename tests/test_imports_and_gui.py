import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.application_controller import ApplicationController
from app.logger import configure_logging
from app.main_window import MainWindow
from app.port_manager import PortManager
from modules.tc200.controller import TC200Controller, TC200Worker
from modules.tc200.driver import TC200Driver
from modules.tc200.panel import TC200Panel


class ImportAndGuiTests(unittest.TestCase):
    def test_public_modules_import(self):
        self.assertTrue(all((
            ApplicationController, TC200Controller, TC200Worker,
            TC200Driver, TC200Panel, configure_logging,
        )))

    def test_headless_start_and_shutdown(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        controller = ApplicationController(window, PortManager(lambda: []))
        window.show()
        QTimer.singleShot(20, app.quit)
        app.exec()
        controller.shutdown()
        self.assertFalse(controller.tc200.thread.isRunning())


if __name__ == "__main__":
    unittest.main()
