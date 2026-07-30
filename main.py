"""Punkt wejścia aplikacji."""

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.application_controller import ApplicationController
from app.logger import configure_logging
from app.main_window import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    gui_log = configure_logging()
    window = MainWindow()
    gui_log.emitter.message.connect(window.append_log)
    controller = ApplicationController(window)
    app.aboutToQuit.connect(controller.shutdown)
    window.show()
    logging.getLogger(__name__).info("Uruchomiono aplikację")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
