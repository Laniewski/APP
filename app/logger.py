"""Logi w GUI. Później można dodać zapis do pliku."""
from datetime import datetime

class AppLogger:
    def __init__(self, window) -> None:
        self.window = window

    def info(self, message: str) -> None: self._write("INFO", message)
    def warning(self, message: str) -> None: self._write("WARNING", message)
    def error(self, message: str) -> None: self._write("ERROR", message)
    def clear(self) -> None: self.window.log_output.clear()

    def _write(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.window.log_output.appendPlainText(f"[{timestamp}] [{level}] {message}")
