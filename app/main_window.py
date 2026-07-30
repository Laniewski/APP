"""Główne okno aplikacji, bez logiki komunikacji z urządzeniami."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from modules.tc200.panel import TC200Panel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("APPv2 — Sterowanie stanowiskiem laboratoryjnym")
        self.resize(1050, 700)
        self.setMinimumSize(800, 560)

        self.tc200_panel = TC200Panel()
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Logi aplikacji")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tc200_panel)
        splitter.addWidget(self.log_output)
        splitter.setSizes([430, 220])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(splitter)
        self.setCentralWidget(central)

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
