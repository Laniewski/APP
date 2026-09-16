"""Panel intencji użytkownika, bez komunikacji ze sprzętem."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QHBoxLayout, QWidget


class MeasurementAssistantPanel(QWidget):
    generate_requested = Signal()
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Asystent pomiaru"))
        self.request_input = QPlainTextEdit()
        self.request_input.setPlaceholderText("Opisz pomiar, który chcesz przeprowadzić...")
        self.request_input.setMaximumHeight(150)
        layout.addWidget(self.request_input)
        self.generate_button = QPushButton("Utwórz plan")
        layout.addWidget(self.generate_button)
        self.status_label = QLabel("Model niezaładowany")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        layout.addWidget(self.plan_view, 1)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("Rozpocznij")
        self.stop_button = QPushButton("Zatrzymaj")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        self.generate_button.clicked.connect(self.generate_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)

    def show_plan(self, plan, validation):
        if validation.errors:
            self.plan_view.setPlainText(
                "Błędy walidacji:\n" + "\n".join(validation.errors)
                + "\n\nOdpowiedź modelu:\n" + json.dumps(plan, ensure_ascii=False, indent=2)
            )
            self.start_button.setEnabled(False)
            return
        lines = [plan.get("title", "Plan")]
        for number, step in enumerate(plan.get("steps", []), 1):
            if isinstance(step, dict):
                lines.append(f"{number}. {step.get('description', '')}\n   {step.get('action', '')}: {step.get('args', {})}")
        if validation.missing_parameters:
            lines.append("\nBrakujące informacje:\n" + "\n".join(validation.missing_parameters))
        lines.extend(plan.get("notes", []) if isinstance(plan.get("notes"), list) else [])
        self.plan_view.setPlainText("\n".join(lines))
        self.start_button.setEnabled(validation.runnable)

    def set_busy(self, busy, runnable=False):
        self.generate_button.setEnabled(not busy)
        self.request_input.setEnabled(not busy)
        self.start_button.setEnabled(not busy and runnable)
        self.stop_button.setEnabled(busy)
