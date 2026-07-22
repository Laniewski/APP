"""
WYGLĄD GUI

Tutaj tworzymy:
- przyciski,
- pola do wpisywania wartości,
- napisy,
- wykres,
- rozmieszczenie elementów.

NIE wpisujemy tutaj komunikacji ze sprzętem.

Każdy element, którego później używa controller.py, zapisujemy jako:
    self.nazwa_elementu

Przykład:
    self.tc_set_button = QPushButton("Ustaw temperaturę")

Dzięki temu controller.py może odwołać się do:
    self.window.tc_set_button
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg


class MainWindow(QMainWindow):
    """Główne okno aplikacji."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Sterowanie stanowiskiem laboratoryjnym")
        self.resize(1250, 820)

        # QWidget jest głównym obszarem wewnątrz okna.
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Główny układ pionowy całej aplikacji.
        main_layout = QVBoxLayout(central_widget)

        # Pasek górny z połączeniem i bezpiecznym zatrzymaniem.
        main_layout.addLayout(self._create_top_bar())

        # QSplitter pozwala zmieniać szerokość lewej i prawej części.
        splitter = QSplitter(Qt.Orientation.Horizontal)

        splitter.addWidget(self._create_device_column())
        splitter.addWidget(self._create_measurement_column())

        # Początkowe proporcje szerokości.
        splitter.setSizes([500, 750])

        main_layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # GÓRNY PASEK
    # ------------------------------------------------------------------

    def _create_top_bar(self) -> QHBoxLayout:
        """Tworzy górny pasek aplikacji."""

        layout = QHBoxLayout()

        self.connect_all_button = QPushButton("Połącz urządzenia")
        self.safe_stop_button = QPushButton("Bezpieczne zatrzymanie")
        self.system_status_label = QLabel("Status: niepołączony")

        self.system_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.connect_all_button)
        layout.addWidget(self.safe_stop_button)

        # addStretch() wypycha status na prawą stronę.
        layout.addStretch()

        layout.addWidget(self.system_status_label)

        return layout

    # ------------------------------------------------------------------
    # LEWA KOLUMNA: URZĄDZENIA
    # ------------------------------------------------------------------

    def _create_device_column(self) -> QWidget:
        """
        Tworzy lewą kolumnę z panelami urządzeń.

        Używamy QScrollArea, aby po dodaniu kolejnych opcji
        można było przewijać lewy panel.
        """

        content = QWidget()
        content_layout = QVBoxLayout(content)

        content_layout.addWidget(self._create_tc200_panel())
        content_layout.addWidget(self._create_mdt_panel())
        content_layout.addWidget(self._create_mpc_panel())
        content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        return scroll

    # ------------------------------------------------------------------
    # TC200
    # ------------------------------------------------------------------

    def _create_tc200_panel(self) -> QGroupBox:
        """
        Tworzy panel TC200.

        W tym miejscu dodajesz nowe kontrolki dotyczące TC200.
        Przykład:
            self.tc_error_label = QLabel("Brak błędów")
            layout.addWidget(self.tc_error_label, numer_wiersza, numer_kolumny)
        """

        group = QGroupBox("TC200 — kontroler temperatury")
        layout = QGridLayout(group)

        # Odczyt aktualnej temperatury.
        self.tc_actual_temperature_label = QLabel("-- °C")

        # Pole do wpisania temperatury zadanej.
        self.tc_setpoint_input = QDoubleSpinBox()
        self.tc_setpoint_input.setDecimals(1)
        self.tc_setpoint_input.setRange(20.0, 200.0)
        self.tc_setpoint_input.setSuffix(" °C")

        # Przycisk zapisujący temperaturę z pola powyżej.
        self.tc_set_button = QPushButton("Ustaw temperaturę")

        # Jeden przycisk zmieniający stan grzałki:
        # po włączeniu tekst zmieni się na "Wyłącz grzałkę".
        self.tc_heater_toggle_button = QPushButton("Włącz grzałkę")

        # Status tekstowy urządzenia.
        self.tc_status_label = QLabel("Niepołączony")

        self.tc_port_label = QLabel("Port:")
        self.tc_port_combo = QComboBox()
        self.tc_refresh_ports_button = QPushButton("Odśwież porty")

        layout.addWidget(self.tc_port_label, 0, 0)
        layout.addWidget(self.tc_port_combo, 0, 1)
        layout.addWidget(self.tc_refresh_ports_button, 0, 2)

        layout.addWidget(QLabel("Temperatura aktualna:"), 1, 0)
        layout.addWidget(self.tc_actual_temperature_label, 1, 1, 1, 2)

        layout.addWidget(QLabel("Temperatura zadana:"), 2, 0)
        layout.addWidget(self.tc_setpoint_input, 2, 1)
        layout.addWidget(self.tc_set_button, 2, 2)

        layout.addWidget(self.tc_heater_toggle_button, 3, 0, 1, 3)

        layout.addWidget(QLabel("Status:"), 4, 0)
        layout.addWidget(self.tc_status_label, 4, 1, 1, 2)

        return group

    # ------------------------------------------------------------------
    # MDT694B
    # ------------------------------------------------------------------

    def _create_mdt_panel(self) -> QGroupBox:
        """
        Tworzy panel MDT694B.

        Na razie:
        - odczyt napięcia,
        - wpisanie napięcia,
        - przycisk Ustaw.

        Logikę bezpiecznej zmiany napięcia dodamy w controller.py
        albo później w osobnym pliku devices/mdt694b.py.
        """

        group = QGroupBox("MDT694B — sterownik piezo")
        layout = QGridLayout(group)

        self.mdt_actual_voltage_label = QLabel("-- V")

        self.mdt_voltage_input = QDoubleSpinBox()
        self.mdt_voltage_input.setDecimals(3)

        # To jest tylko wstępny zakres GUI.
        # Później ustawimy go na podstawie zakresu odczytanego z urządzenia.
        self.mdt_voltage_input.setRange(0.0, 150.0)
        self.mdt_voltage_input.setSuffix(" V")

        self.mdt_set_button = QPushButton("Ustaw napięcie")
        self.mdt_status_label = QLabel("Niepołączony")

        layout.addWidget(QLabel("Napięcie aktualne:"), 0, 0)
        layout.addWidget(self.mdt_actual_voltage_label, 0, 1, 1, 2)

        layout.addWidget(QLabel("Napięcie zadane:"), 1, 0)
        layout.addWidget(self.mdt_voltage_input, 1, 1)
        layout.addWidget(self.mdt_set_button, 1, 2)

        layout.addWidget(QLabel("Status:"), 2, 0)
        layout.addWidget(self.mdt_status_label, 2, 1, 1, 2)

        return group

    # ------------------------------------------------------------------
    # MPC220
    # ------------------------------------------------------------------

    def _create_mpc_panel(self) -> QGroupBox:
        """
        Tworzy panel MPC220.

        Dla każdej łopatki mamy:
        1. trzy ruchy w lewo,
        2. aktualną pozycję,
        3. trzy ruchy w prawo,
        4. pole pozycji docelowej,
        5. przycisk Ustaw.
        """

        group = QGroupBox("MPC220 — kontroler polaryzacji")
        layout = QVBoxLayout(group)

        # Osobne pod-panele dla obu łopatek.
        layout.addWidget(self._create_paddle_panel(1))
        layout.addWidget(self._create_paddle_panel(2))

        self.mpc_port_label = QLabel("Port:")
        self.mpc_port_combo = QComboBox()
        self.mpc_refresh_ports_button = QPushButton("Odśwież porty")
        self.mpc_home_button = QPushButton("Home obu łopatek")
        self.mpc_status_label = QLabel("Status: niepołączony")

        port_layout = QHBoxLayout()
        port_layout.addWidget(self.mpc_port_label)
        port_layout.addWidget(self.mpc_port_combo)
        port_layout.addWidget(self.mpc_refresh_ports_button)

        layout.addLayout(port_layout)
        layout.addWidget(self.mpc_home_button)
        layout.addWidget(self.mpc_status_label)

        return group

    def _create_paddle_panel(self, paddle_number: int) -> QGroupBox:
        """
        Tworzy GUI jednej łopatki MPC220.

        Ważne:
        nazwy elementów są ustawiane dynamicznie przez setattr().

        Dla paddle 1 powstaną np.:
            self.mpc1_left_large_button
            self.mpc1_position_label
            self.mpc1_target_input
            self.mpc1_set_button

        Dla paddle 2 analogicznie z prefiksem mpc2_.
        """

        group = QGroupBox(f"Łopatka {paddle_number}")
        layout = QVBoxLayout(group)

        # --------------------------
        # Górny rząd: ruch względny
        # --------------------------

        move_layout = QHBoxLayout()

        left_large = QPushButton("<<<")
        left_medium = QPushButton("<<")
        left_small = QPushButton("<")

        position_label = QLabel("-- °")
        position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        position_label.setMinimumWidth(80)

        right_small = QPushButton(">")
        right_medium = QPushButton(">>")
        right_large = QPushButton(">>>")

        move_layout.addWidget(left_large)
        move_layout.addWidget(left_medium)
        move_layout.addWidget(left_small)
        move_layout.addWidget(position_label)
        move_layout.addWidget(right_small)
        move_layout.addWidget(right_medium)
        move_layout.addWidget(right_large)

        # --------------------------
        # Dolny rząd: pozycja docelowa
        # --------------------------

        target_layout = QHBoxLayout()

        target_layout.addWidget(QLabel("Pozycja docelowa:"))

        target_input = QDoubleSpinBox()
        target_input.setDecimals(2)
        target_input.setRange(0.0, 10000.0)
        target_input.setSuffix(" °")

        set_button = QPushButton("Ustaw")

        target_layout.addWidget(target_input)
        target_layout.addWidget(set_button)

        layout.addLayout(move_layout)
        layout.addLayout(target_layout)

        # Udostępniamy kontrolki controller.py.
        setattr(self, f"mpc{paddle_number}_left_large_button", left_large)
        setattr(self, f"mpc{paddle_number}_left_medium_button", left_medium)
        setattr(self, f"mpc{paddle_number}_left_small_button", left_small)

        setattr(self, f"mpc{paddle_number}_position_label", position_label)

        setattr(self, f"mpc{paddle_number}_right_small_button", right_small)
        setattr(self, f"mpc{paddle_number}_right_medium_button", right_medium)
        setattr(self, f"mpc{paddle_number}_right_large_button", right_large)

        setattr(self, f"mpc{paddle_number}_target_input", target_input)
        setattr(self, f"mpc{paddle_number}_set_button", set_button)

        return group

    # ------------------------------------------------------------------
    # PRAWA KOLUMNA: WYKRES I LOGI
    # ------------------------------------------------------------------

    def _create_measurement_column(self) -> QWidget:
        """Tworzy prawą część aplikacji."""

        widget = QWidget()
        layout = QVBoxLayout(widget)

        layout.addWidget(self._create_plot_panel(), stretch=3)
        layout.addWidget(self._create_log_panel(), stretch=1)

        return widget

    def _create_plot_panel(self) -> QGroupBox:
        """
        Tworzy panel wykresu ADS1263.

        Tutaj tylko budujemy wygląd.
        Dane do wykresu będziemy dodawać później w controller.py.
        """

        group = QGroupBox("ADS1263 — wykres pomiaru")
        layout = QVBoxLayout(group)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("bottom", "Czas", units="s")
        self.plot_widget.setLabel("left", "Napięcie", units="V")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)

        self.plot_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout.addWidget(self.plot_widget)

        # Przyciski sterujące pomiarem.
        button_layout = QHBoxLayout()

        self.measurement_start_button = QPushButton("Rozpocznij pomiar")
        self.measurement_stop_button = QPushButton("Zatrzymaj pomiar")
        self.plot_clear_button = QPushButton("Wyczyść wykres")
        self.save_txt_button = QPushButton("Zapisz do TXT")

        button_layout.addWidget(self.measurement_start_button)
        button_layout.addWidget(self.measurement_stop_button)
        button_layout.addWidget(self.plot_clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.save_txt_button)

        layout.addLayout(button_layout)

        # Ręczne ustawianie zakresów osi.
        scale_layout = QGridLayout()

        self.x_min_input = QDoubleSpinBox()
        self.x_max_input = QDoubleSpinBox()
        self.y_min_input = QDoubleSpinBox()
        self.y_max_input = QDoubleSpinBox()

        for field in (
            self.x_min_input,
            self.x_max_input,
            self.y_min_input,
            self.y_max_input,
        ):
            field.setDecimals(3)
            field.setRange(-1_000_000.0, 1_000_000.0)

        self.x_min_input.setValue(0.0)
        self.x_max_input.setValue(30.0)
        self.y_min_input.setValue(-1.0)
        self.y_max_input.setValue(1.0)

        self.apply_scale_button = QPushButton("Zastosuj skalę")
        self.auto_scale_button = QPushButton("Auto")

        scale_layout.addWidget(QLabel("X min:"), 0, 0)
        scale_layout.addWidget(self.x_min_input, 0, 1)
        scale_layout.addWidget(QLabel("X max:"), 0, 2)
        scale_layout.addWidget(self.x_max_input, 0, 3)

        scale_layout.addWidget(QLabel("Y min:"), 1, 0)
        scale_layout.addWidget(self.y_min_input, 1, 1)
        scale_layout.addWidget(QLabel("Y max:"), 1, 2)
        scale_layout.addWidget(self.y_max_input, 1, 3)

        scale_layout.addWidget(self.apply_scale_button, 2, 0, 1, 3)
        scale_layout.addWidget(self.auto_scale_button, 2, 3)

        layout.addLayout(scale_layout)

        return group

    def _create_log_panel(self) -> QGroupBox:
        """Tworzy pole logów."""

        group = QGroupBox("Logi")
        layout = QVBoxLayout(group)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText(
            "Tutaj pojawią się informacje, odpowiedzi urządzeń i błędy."
        )

        self.clear_log_button = QPushButton("Wyczyść log")

        layout.addWidget(self.log_output)
        layout.addWidget(self.clear_log_button)

        return group
