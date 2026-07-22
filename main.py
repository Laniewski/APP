"""Punkt startowy aplikacji. Tutaj tylko tworzymy obiekty i uruchamiamy GUI."""
import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow
from controller import MainController
from devices.tc200 import TC200
from devices.mdt694b import MDT694B
from devices.mpc220 import MPC220
from devices.ads1263 import ADS1263
from app.plot_manager import PlotManager
from app.system_control import SystemControl
from app.logger import AppLogger


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()

    tc200 = TC200()
    mdt694b = MDT694B()
    mpc220 = MPC220()
    ads1263 = ADS1263()

    logger = AppLogger(window)
    plot_manager = PlotManager(window)
    system_control = SystemControl(tc200, mdt694b, mpc220, ads1263, logger)

    window.controller = MainController(
        window, tc200, mdt694b, mpc220, ads1263,
        plot_manager, system_control, logger,
    )

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
