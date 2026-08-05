import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QGroupBox

from app.application_controller import ApplicationController
from app.logger import configure_logging
from app.main_window import MainWindow
from app.port_manager import PortManager
from modules.mdt694b.controller import MDT694BController, MDT694BWorker
from modules.mdt694b.driver import MDT694BDriver
from modules.mdt694b.panel import MDT694BPanel
from modules.mpc220.controller import MPC220Controller, MPC220Worker
from modules.mpc220.driver import MPC220Driver
from modules.mpc220.panel import MPC220Panel
from modules.tc200.controller import TC200Controller, TC200Worker
from modules.tc200.driver import TC200Driver
from modules.tc200.panel import TC200Panel


class ImportAndGuiTests(unittest.TestCase):
    def test_public_modules_import(self):
        self.assertTrue(all((
            ApplicationController, TC200Controller, TC200Worker,
            TC200Driver, TC200Panel, configure_logging,
            MPC220Controller, MPC220Worker, MPC220Driver, MPC220Panel,
            MDT694BController, MDT694BWorker, MDT694BDriver, MDT694BPanel,
        )))

    def test_complete_appv2_layout_and_clear_buttons(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()

        self.assertEqual(
            window.main_splitter.orientation(),
            Qt.Orientation.Horizontal,
        )
        panels = {
            panel.title()
            for panel in window.findChildren(QGroupBox)
            if panel.title()
        }
        self.assertTrue({
            "TC200 — kontroler temperatury",
            "MDT694B — sterownik piezo",
            "MPC220 — kontroler polaryzacji",
            "ADS1263",
        }.issubset(panels))
        self.assertIsInstance(window.tc200_panel, TC200Panel)
        self.assertIsInstance(window.mpc220_panel, MPC220Panel)
        self.assertIsInstance(window.mdt694b_panel, MDT694BPanel)
        self.assertEqual(window.mdt694b_panel.mdt_voltage_input.decimals(), 2)
        self.assertFalse(hasattr(window, "mpc1_left_large_button"))

        self.assertEqual(len(window.plot_widget.listDataItems()), 2)
        self.assertNotEqual(
            window.in0_curve.opts["pen"].color(),
            window.in1_curve.opts["pen"].color(),
        )
        window.in0_curve.setData([0, 1], [1, 2])
        window.in1_curve.setData([0, 1], [3, 4])
        window.plot_clear_button.click()
        self.assertIsNone(window.in0_curve.getData()[0])
        self.assertIsNone(window.in1_curve.getData()[0])

        window.append_log("wiadomość testowa")
        self.assertIn("wiadomość testowa", window.log_output.toPlainText())
        window.log_clear_button.click()
        self.assertEqual(window.log_output.toPlainText(), "")
        window.close()
        app.processEvents()

    def test_current_tc200_module_headless_start_and_safe_shutdown(self):
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        controller = ApplicationController(window, PortManager(lambda: []))
        self.assertIs(controller.tc200.panel, window.tc200_panel)
        self.assertTrue(controller.tc200.thread.isRunning())
        self.assertTrue(controller.mpc220.thread.isRunning())
        self.assertTrue(controller.mdt694b.thread.isRunning())
        window.show()
        QTimer.singleShot(20, app.quit)
        app.exec()
        controller.shutdown()
        self.assertFalse(controller.tc200.thread.isRunning())
        self.assertFalse(controller.mpc220.thread.isRunning())
        self.assertFalse(controller.mdt694b.thread.isRunning())


if __name__ == "__main__":
    unittest.main()
