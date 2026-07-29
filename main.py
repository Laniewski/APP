import sys

from PySide6.QtWidgets import QApplication

from app.controller import MainController
from app.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    window = MainWindow()
    controller = MainController(window)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())