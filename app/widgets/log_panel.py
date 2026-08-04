"""Panel logów aplikacji."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QPlainTextEdit, QPushButton, QVBoxLayout


class LogPanel(QGroupBox):
    """Panel logów przechowujący tekst oraz przycisk czyszczenia."""

    def __init__(self) -> None:
        super().__init__("Logi")
        layout = QVBoxLayout(self)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setSizePolicy(
            self.log_output.sizePolicy().Policy.Expanding,
            self.log_output.sizePolicy().Policy.Expanding,
        )
        self.log_clear_button = QPushButton("Wyczyść log")
        self.log_clear_button.clicked.connect(self.clear_log)

        layout.addWidget(self.log_output)
        layout.addWidget(
            self.log_clear_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)

    def clear_log(self) -> None:
        self.log_output.clear()
