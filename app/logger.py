"""Centralna konfiguracja standardowego logowania z bezpiecznym wyjściem do Qt."""

import logging

from PySide6.QtCore import QObject, Signal


class _LogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """Handler przekazujący sformatowany rekord do GUI przez sygnał queued."""

    def __init__(self) -> None:
        super().__init__()
        self.emitter = _LogEmitter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


def configure_logging(level: int = logging.INFO) -> QtLogHandler:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    gui_handler = QtLogHandler()
    gui_handler.setFormatter(formatter)
    root.addHandler(gui_handler)
    return gui_handler
