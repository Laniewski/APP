"""Panel intencji użytkownika, bez komunikacji ze sprzętem."""

import json

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QComboBox, QApplication, QSizePolicy


class MeasurementAssistantPanel(QWidget):
    generate_requested = Signal()
    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self.execution_enabled = False
        self._json_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Asystent pomiaru"))
        self.execution_label = QLabel()
        self.execution_label.setWordWrap(True)
        layout.addWidget(self.execution_label)
        self.set_execution_enabled(False)
        self.examples = QComboBox()
        self.examples.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.examples.setMinimumContentsLength(12)
        self.examples.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.examples.addItem("Przykłady")
        self.examples.addItems([
            "Ustaw temperaturę na 40 stopni Celsjusza, następnie ustaw piezo na 30 V i rozpocznij pomiar.",
            "Ustaw piezo na 15 V, rozpocznij pomiar, poczekaj 5 sekund i zatrzymaj pomiar.",
            "Ustaw pierwszą łopatkę polaryzacji na 30 stopni.",
            "Ustaw temperaturę na 35 stopni i poczekaj aż się ustabilizuje.",
            "Rozpocznij pomiar.", "Ustaw piezo, a potem rozpocznij pomiar.",
        ])
        self.examples.activated.connect(self._insert_example)
        layout.addWidget(self.examples)
        self.request_input = QPlainTextEdit()
        self.request_input.setPlaceholderText("Opisz pomiar, który chcesz przeprowadzić...")
        self.request_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.request_input, 1)
        self.generate_button = QPushButton("Utwórz plan")
        layout.addWidget(self.generate_button)
        self.status_label = QLabel("Model niezaładowany")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.model_status_label = QLabel("Status modelu: niezaładowany")
        self.model_status_label.setWordWrap(True)
        layout.addWidget(self.model_status_label)
        self.result_label = QLabel("Test planowania: oczekiwanie")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        self.metrics_label = QLabel("Metryki modelu: —")
        self.metrics_label.setWordWrap(True)
        layout.addWidget(self.metrics_label)
        self.copy_button = QPushButton("Kopiuj JSON")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._json_text))
        layout.addWidget(self.copy_button)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.plan_view, 3)
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

    def set_execution_enabled(self, enabled):
        self.execution_enabled = enabled
        self.execution_label.setText(
            "Tryb wykonania AI jest włączony — sprawdź plan przed rozpoczęciem." if enabled else
            "Tryb wykonania AI jest wyłączony — testowanie planowania bez sterowania sprzętem.")
        if hasattr(self, "start_button"):
            self.start_button.setEnabled(False)

    def _insert_example(self, index):
        if index > 0:
            self.request_input.setPlainText(self.examples.itemText(index))

    def show_metrics(self, metrics):
        def display(key, suffix):
            value = metrics.get(key)
            return f"{value:.1f} {suffix}" if isinstance(value, (int, float)) else "—"
        self.metrics_label.setText("Metryki modelu\nCzas: " + display("elapsed_s", "s")
                                   + "\nPrędkość: " + display("tokens_per_s", "tok/s")
                                   + "\nTokeny: " + str(metrics.get("completion_tokens", "—")))

    def show_plan(self, plan, validation, raw_response=None):
        self._json_text = json.dumps(plan, ensure_ascii=False, indent=2) if isinstance(plan, dict) else (raw_response or "null")
        self.copy_button.setEnabled(True)
        self.result_label.setText("Plan odrzucony" if validation.errors else
                                  "Plan z brakami" if validation.missing_parameters else "Poprawny plan")
        lines = [str(plan.get("title", "Plan"))] if isinstance(plan, dict) else []
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        for number, step in enumerate(steps if isinstance(steps, list) else [], 1):
            if isinstance(step, dict):
                lines.append(f"{number}. {step.get('description', '')}")
        if validation.missing_parameters:
            lines.append("\nBrakujące informacje:\n" + "\n".join(validation.missing_parameters))
        if validation.errors:
            lines.append("\nBłędy walidacji:\n" + "\n".join(validation.errors))
        if isinstance(plan, dict) and isinstance(plan.get("notes"), list):
            lines.extend(str(note) for note in plan["notes"])
        self.plan_view.setPlainText("\n".join(lines))
        self.start_button.setEnabled(self.execution_enabled and validation.runnable)

    def set_busy(self, busy, runnable=False):
        self.generate_button.setEnabled(not busy)
        self.request_input.setEnabled(not busy)
        self.examples.setEnabled(not busy)
        self.start_button.setEnabled(self.execution_enabled and not busy and runnable)
        self.stop_button.setEnabled(busy)
