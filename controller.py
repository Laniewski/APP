"""
Controller łączy GUI z resztą aplikacji.
Tu przypisujemy przyciski do funkcji i później będziemy przekazywać dane
między GUI, urządzeniami, wykresem i sterowaniem systemowym.
"""
from functools import partial
from time import perf_counter
from typing import Optional

from PySide6.QtCore import QThread, QTimer, QObject, Signal, Slot
from serial.tools import list_ports

from app.mpc220_calibration import (
    angle_to_command,
    calculate_target_angle,
    clamp_angle,
    raw_position_to_angle,
)


class TC200Worker(QObject):
    request_connect = Signal()
    request_set_temperature = Signal(float)
    request_toggle_heater = Signal()

    connected = Signal()
    connection_failed = Signal(str)
    temperature_updated = Signal(float)
    heater_state = Signal(bool)
    status_text = Signal(str)
    error = Signal(str)

    def __init__(self, tc200) -> None:
        super().__init__()
        self.tc200 = tc200
        self._temperature_timer: Optional[QTimer] = None

        self.request_connect.connect(self.connect_device)
        self.request_set_temperature.connect(self.set_temperature)
        self.request_toggle_heater.connect(self.toggle_heater)

    @Slot()
    def connect_device(self) -> None:
        try:
            self.tc200.connect()
            self.status_text.emit("Połączony")
            self.connected.emit()
            self._publish_heater_state()
            self._publish_temperature()
            self._start_temperature_timer()
        except Exception as error:
            self.status_text.emit("Błąd łączenia")
            self.error.emit(f"TC200: {error}")
            self.connection_failed.emit(str(error))

    def _start_temperature_timer(self) -> None:
        if self._temperature_timer is not None:
            return

        self._temperature_timer = QTimer()
        self._temperature_timer.setInterval(500)
        self._temperature_timer.timeout.connect(self._update_temperature)
        self._temperature_timer.start()

    def _stop_temperature_timer(self) -> None:
        if self._temperature_timer is None:
            return
        self._temperature_timer.stop()
        self._temperature_timer = None

    @Slot()
    def _update_temperature(self) -> None:
        try:
            if not self.tc200.connected:
                return
            temperature = self.tc200.read_temperature()
            self.temperature_updated.emit(temperature)
        except Exception as error:
            self.status_text.emit("Błąd komunikacji")
            self.error.emit(f"TC200: Błąd odczytu temperatury: {error}")
            self._stop_temperature_timer()

    def _publish_heater_state(self) -> None:
        try:
            state = self.tc200.read_heater_state()
            self.heater_state.emit(state)
        except Exception as error:
            self.error.emit(f"TC200: Błąd odczytu stanu grzałki: {error}")

    def _publish_temperature(self) -> None:
        try:
            temperature = self.tc200.read_temperature()
            self.temperature_updated.emit(temperature)
        except Exception as error:
            self.error.emit(f"TC200: Błąd odczytu temperatury: {error}")

    @Slot(float)
    def set_temperature(self, temperature: float) -> None:
        try:
            self.tc200.set_temperature(temperature)
            self.status_text.emit("Połączony")
        except Exception as error:
            self.error.emit(f"TC200: nie udało się ustawić temperatury: {error}")

    @Slot()
    def toggle_heater(self) -> None:
        try:
            heater_enabled = self.tc200.read_heater_state()
            if heater_enabled:
                self.tc200.disable_heater()
                new_state = False
            else:
                self.tc200.enable_heater()
                new_state = True
            self.heater_state.emit(new_state)
        except Exception as error:
            self.error.emit(f"TC200: nie udało się zmienić stanu grzałki: {error}")


class MPC220Worker(QObject):
    """Wykonuje komunikację MPC220 poza głównym wątkiem GUI.

    Sygnały wejściowe opisują operacje użytkownika w stopniach. Worker pobiera
    pozycję z urządzenia, używa centralnych funkcji kalibracyjnych i dopiero
    potem przekazuje do warstwy urządzenia całkowite jednostki APT. Dzięki temu
    wszystkie potencjalnie blokujące odczyty szeregowe odbywają się w QThread.
    """

    request_connect = Signal()
    request_set_angle = Signal(int, float)
    request_adjust_angle = Signal(int, float)
    request_refresh_position = Signal(int)
    request_refresh_all_positions = Signal()
    request_home_all = Signal()

    connected = Signal()
    connection_failed = Signal(str)
    status_text = Signal(str)
    error = Signal(str)
    position_updated = Signal(int, float)
    movement_started = Signal(int)
    movement_finished = Signal(int, float)
    busy_changed = Signal(bool)
    operation_info = Signal(str)

    def __init__(self, mpc220) -> None:
        super().__init__()
        self.mpc220 = mpc220

        self.request_connect.connect(self.connect_device)
        self.request_set_angle.connect(self.set_angle)
        self.request_adjust_angle.connect(self.adjust_angle)
        self.request_refresh_position.connect(self.refresh_position)
        self.request_refresh_all_positions.connect(self.refresh_all_positions)
        self.request_home_all.connect(self.home_all)

    @Slot()
    def connect_device(self) -> None:
        """Łączy urządzenie i publikuje pozycje obu łopatek."""
        try:
            self.mpc220.connect()
            self.status_text.emit("Połączony")
            self.connected.emit()
            self.refresh_all_positions()
        except Exception as error:
            self.status_text.emit("Błąd łączenia")
            self.error.emit(f"MPC220: {error}")
            self.connection_failed.emit(str(error))

    @Slot(int, float)
    def set_angle(self, paddle_number: int, angle_deg: float) -> None:
        """Ustawia kąt absolutny, a następnie publikuje odczyt z urządzenia.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.
            angle_deg: Docelowy kąt w stopniach z pola GUI.
        """
        target_angle = clamp_angle(angle_deg)
        if target_angle != angle_deg:
            self.operation_info.emit(
                f"MPC220: cel ograniczono do {target_angle:.1f}°."
            )
        self._move_to_angle(paddle_number, target_angle)

    @Slot(int, float)
    def adjust_angle(self, paddle_number: int, delta_angle_deg: float) -> None:
        """Zmienia kąt względem aktualnego odczytu, używając ruchu absolutnego.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.
            delta_angle_deg: Krok w stopniach, np. ``-10.0`` albo ``+5.0``.

        Najpierw odczytujemy licznik MPC220, ponieważ etykieta GUI nie jest
        źródłem prawdy. Dopiero z tego odczytu wyliczamy cel, a urządzenie
        dostaje ``move_absolute_units`` zamiast ``mot_move_relative``.
        """
        try:
            raw_position = self.mpc220.read_position_units(paddle_number)
            current_angle = raw_position_to_angle(raw_position)
            target_angle = calculate_target_angle(current_angle, delta_angle_deg)
            self.operation_info.emit(
                f"MPC220: łopatka {paddle_number}, aktualny kąt="
                f"{current_angle:.2f}°, krok={delta_angle_deg:+.2f}°."
            )
            if target_angle != current_angle + delta_angle_deg:
                self.operation_info.emit(
                    f"MPC220: cel ograniczono do {target_angle:.1f}°."
                )
            self._move_to_angle(paddle_number, target_angle)
        except Exception as error:
            self.error.emit(
                f"MPC220: nie udało się zmienić kąta łopatki "
                f"{paddle_number}: {error}"
            )

    def _move_to_angle(self, paddle_number: int, target_angle: float) -> None:
        """Wysyła absolutny cel, czeka na ruch i odczytuje rzeczywistą pozycję."""
        self.busy_changed.emit(True)
        self.movement_started.emit(paddle_number)
        try:
            target_units = angle_to_command(target_angle)
            self.operation_info.emit(
                f"MPC220: łopatka {paddle_number}, cel={target_angle:.2f}°, "
                f"command={target_units}."
            )
            self.mpc220.move_absolute_units(paddle_number, target_units)
            self.mpc220.wait_until_stopped(paddle_number)
            raw_position = self.mpc220.read_position_units(paddle_number)
            actual_angle = raw_position_to_angle(raw_position)
            displayed_angle = clamp_angle(actual_angle)
            self.position_updated.emit(paddle_number, displayed_angle)
            self.movement_finished.emit(paddle_number, displayed_angle)
            self.operation_info.emit(
                f"MPC220: łopatka {paddle_number} zakończyła ruch, "
                f"raw={raw_position}, kąt={actual_angle:.2f}°."
            )
        except Exception as error:
            self.error.emit(
                f"MPC220: nie udało się ustawić łopatki {paddle_number}: {error}"
            )
        finally:
            self.busy_changed.emit(False)

    @Slot(int)
    def refresh_position(self, paddle_number: int) -> None:
        """Odczytuje jedną łopatkę i emituje jej kąt do GUI."""
        try:
            raw_position = self.mpc220.read_position_units(paddle_number)
            angle = raw_position_to_angle(raw_position)
            self.position_updated.emit(paddle_number, clamp_angle(angle))
            self.operation_info.emit(
                f"MPC220: łopatka {paddle_number}, odczyt raw={raw_position}, "
                f"kąt={angle:.2f}°."
            )
        except Exception as error:
            self.error.emit(
                f"MPC220: nie udało się odczytać pozycji łopatki "
                f"{paddle_number}: {error}"
            )

    @Slot()
    def refresh_all_positions(self) -> None:
        """Odczytuje obie łopatki po kolei, bez blokowania GUI."""
        for paddle_number in (1, 2):
            self.refresh_position(paddle_number)

    @Slot()
    def home_all(self) -> None:
        """Wykonuje homing obu łopatek i publikuje oba odczyty."""
        self.busy_changed.emit(True)
        try:
            self.mpc220.home_all()
            self.refresh_all_positions()
        except Exception as error:
            self.error.emit(f"MPC220: nie udało się wykonać homingu: {error}")
        finally:
            self.busy_changed.emit(False)


class MainController:
    MPC_SMALL_STEP = 1.0
    MPC_MEDIUM_STEP = 5.0
    MPC_LARGE_STEP = 10.0

    def __init__(self, window, tc200, mdt694b, mpc220, ads1263,
                 plot_manager, system_control, logger) -> None:
        self.window = window
        self.tc200 = tc200
        self.mdt694b = mdt694b
        self.mpc220 = mpc220
        self.ads1263 = ads1263
        self.plot_manager = plot_manager
        self.system_control = system_control
        self.logger = logger

        self.measurement_timer = QTimer(self.window)
        self.measurement_timer.setInterval(100)
        self.measurement_timer.timeout.connect(self._read_measurement_sample)

        self.measurement_start_time = 0.0
        self.pending_connections = 0

        self._connect_signals()
        self._setup_workers()
        self.refresh_serial_ports()

    def _connect_signals(self) -> None:
        """Mapa: przycisk -> funkcja."""
        self.window.connect_all_button.clicked.connect(self.connect_all_devices)
        self.window.safe_stop_button.clicked.connect(self.safe_stop)

        self.window.tc_set_button.clicked.connect(self.set_tc_temperature)
        self.window.tc_heater_toggle_button.clicked.connect(self.toggle_tc_heater)
        self.window.tc_refresh_ports_button.clicked.connect(self.refresh_serial_ports)

        self.window.mdt_set_button.clicked.connect(self.set_mdt_voltage)
        self.window.mpc_refresh_ports_button.clicked.connect(self.refresh_serial_ports)
        self.window.mpc_refresh_positions_button.clicked.connect(
            self.refresh_mpc_positions
        )

        self.window.mpc1_left_large_button.clicked.connect(partial(self.adjust_mpc_angle, 1, -self.MPC_LARGE_STEP))
        self.window.mpc1_left_medium_button.clicked.connect(partial(self.adjust_mpc_angle, 1, -self.MPC_MEDIUM_STEP))
        self.window.mpc1_left_small_button.clicked.connect(partial(self.adjust_mpc_angle, 1, -self.MPC_SMALL_STEP))
        self.window.mpc1_right_small_button.clicked.connect(partial(self.adjust_mpc_angle, 1, self.MPC_SMALL_STEP))
        self.window.mpc1_right_medium_button.clicked.connect(partial(self.adjust_mpc_angle, 1, self.MPC_MEDIUM_STEP))
        self.window.mpc1_right_large_button.clicked.connect(partial(self.adjust_mpc_angle, 1, self.MPC_LARGE_STEP))
        self.window.mpc1_set_button.clicked.connect(partial(self.set_mpc_angle, 1))

        self.window.mpc2_left_large_button.clicked.connect(partial(self.adjust_mpc_angle, 2, -self.MPC_LARGE_STEP))
        self.window.mpc2_left_medium_button.clicked.connect(partial(self.adjust_mpc_angle, 2, -self.MPC_MEDIUM_STEP))
        self.window.mpc2_left_small_button.clicked.connect(partial(self.adjust_mpc_angle, 2, -self.MPC_SMALL_STEP))
        self.window.mpc2_right_small_button.clicked.connect(partial(self.adjust_mpc_angle, 2, self.MPC_SMALL_STEP))
        self.window.mpc2_right_medium_button.clicked.connect(partial(self.adjust_mpc_angle, 2, self.MPC_MEDIUM_STEP))
        self.window.mpc2_right_large_button.clicked.connect(partial(self.adjust_mpc_angle, 2, self.MPC_LARGE_STEP))
        self.window.mpc2_set_button.clicked.connect(partial(self.set_mpc_angle, 2))

        self.window.mpc_home_button.clicked.connect(self.home_mpc)

        self.window.measurement_start_button.clicked.connect(self.start_measurement)
        self.window.measurement_stop_button.clicked.connect(self.stop_measurement)
        self.window.plot_clear_button.clicked.connect(self.clear_plot)
        self.window.save_txt_button.clicked.connect(self.save_measurement)
        self.window.apply_scale_button.clicked.connect(self.plot_manager.apply_manual_scale)
        self.window.auto_scale_button.clicked.connect(self.plot_manager.enable_auto_scale)
        self.window.clear_log_button.clicked.connect(self.logger.clear)

    def _setup_workers(self) -> None:
        self.tc200_thread = QThread(self.window)
        self.tc200_worker = TC200Worker(self.tc200)
        self.tc200_worker.moveToThread(self.tc200_thread)
        self.tc200_worker.connected.connect(self._on_tc200_connected)
        self.tc200_worker.connection_failed.connect(self._on_tc200_connection_failed)
        self.tc200_worker.temperature_updated.connect(self._on_tc200_temperature_updated)
        self.tc200_worker.heater_state.connect(self._update_tc_heater_button)
        self.tc200_worker.status_text.connect(self.window.tc_status_label.setText)
        self.tc200_worker.error.connect(self._on_tc200_error)
        self.tc200_worker.connected.connect(self._on_device_connection_finished)
        self.tc200_worker.connection_failed.connect(self._on_device_connection_finished)
        self.tc200_thread.start()

        self.mpc220_thread = QThread(self.window)
        self.mpc220_worker = MPC220Worker(self.mpc220)
        self.mpc220_worker.moveToThread(self.mpc220_thread)
        self.mpc220_worker.connected.connect(self._on_mpc220_connected)
        self.mpc220_worker.connection_failed.connect(self._on_mpc220_connection_failed)
        self.mpc220_worker.status_text.connect(self.window.mpc_status_label.setText)
        self.mpc220_worker.error.connect(self._on_mpc220_error)
        self.mpc220_worker.position_updated.connect(self._on_mpc_position_updated)
        self.mpc220_worker.movement_started.connect(self._on_mpc_movement_started)
        self.mpc220_worker.movement_finished.connect(self._on_mpc_movement_finished)
        self.mpc220_worker.busy_changed.connect(self._set_mpc_controls_enabled)
        self.mpc220_worker.operation_info.connect(self.logger.info)
        self.mpc220_worker.connected.connect(self._on_device_connection_finished)
        self.mpc220_worker.connection_failed.connect(self._on_device_connection_finished)
        self.mpc220_thread.start()

    def refresh_serial_ports(self) -> None:
        """Wykrywa dostępne porty szeregowe i aktualizuje comboboxy."""
        tc_selection = self._selected_port(self.window.tc_port_combo)
        mpc_selection = self._selected_port(self.window.mpc_port_combo)
        available_ports = list_ports.comports()

        if not available_ports:
            self._set_combo_to_no_ports(self.window.tc_port_combo)
            self._set_combo_to_no_ports(self.window.mpc_port_combo)
            self.logger.warning("Brak dostępnych portów szeregowych.")
            return

        self._fill_port_combo(self.window.tc_port_combo, available_ports, tc_selection)
        self._fill_port_combo(self.window.mpc_port_combo, available_ports, mpc_selection)

    def _selected_port(self, combo) -> Optional[str]:
        current_data = combo.currentData()
        if isinstance(current_data, str):
            return current_data
        return None

    def _set_combo_to_no_ports(self, combo) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Brak dostępnych portów", None)
        combo.setEnabled(False)
        combo.blockSignals(False)

    def _fill_port_combo(self, combo, ports, selected_device) -> None:
        combo.blockSignals(True)
        combo.clear()
        for port in ports:
            description = port.description or "Nieznane urządzenie"
            combo.addItem(f"{port.device} — {description}", port.device)

        combo.setEnabled(True)
        if selected_device and selected_device in [port.device for port in ports]:
            index = next(
                (idx for idx, port in enumerate(ports) if port.device == selected_device),
                0,
            )
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _validate_port_selection(self) -> bool:
        tc_port = self._selected_port(self.window.tc_port_combo)
        mpc_port = self._selected_port(self.window.mpc_port_combo)

        if tc_port is None:
            self.logger.error("Wybierz port dla TC200 przed połączeniem.")
            return False
        if mpc_port is None:
            self.logger.error("Wybierz port dla MPC220 przed połączeniem.")
            return False
        if tc_port == mpc_port:
            self.logger.error("TC200 i MPC220 nie mogą korzystać z tego samego portu.")
            return False

        self.tc200.port = tc_port
        self.mpc220.port = mpc_port
        return True

    def connect_all_devices(self) -> None:
        if not self._validate_port_selection():
            return

        self.window.connect_all_button.setEnabled(False)
        self.window.connect_all_button.setText("Łączenie...")
        self.window.tc_status_label.setText("Łączenie...")
        self.window.mpc_status_label.setText("Łączenie...")
        self.pending_connections = 2

        self.tc200_worker.request_connect.emit()
        self.mpc220_worker.request_connect.emit()

    def _on_tc200_connected(self) -> None:
        self.logger.info("Połączono z TC200")

    def _on_tc200_connection_failed(self, message: str) -> None:
        self.logger.error(f"Błąd połączenia TC200: {message}")

    def _on_tc200_temperature_updated(self, temperature: float) -> None:
        self.window.tc_actual_temperature_label.setText(f"{temperature:.1f} C")

    def _update_tc_heater_button(self, heater_enabled: bool) -> None:
        self.window.tc_heater_toggle_button.setText(
            "Wyłącz grzałkę" if heater_enabled else "Włącz grzałkę"
        )

    def _on_tc200_error(self, message: str) -> None:
        self.logger.error(message)

    def _on_mpc220_connected(self) -> None:
        self.logger.info(f"MPC220: połączono z portem {self.mpc220.port}")

    def _on_mpc220_connection_failed(self, message: str) -> None:
        self.logger.error(f"Błąd połączenia MPC220: {message}")

    def _on_mpc220_error(self, message: str) -> None:
        self.window.mpc_status_label.setText("Błąd komunikacji")
        self.logger.error(message)

    def _on_mpc_position_updated(
        self,
        paddle_number: int,
        angle_deg: float,
    ) -> None:
        """Wyświetla wyłącznie kąt obliczony z ostatniego odczytu urządzenia."""
        position_label = getattr(self.window, f"mpc{paddle_number}_position_label")
        position_label.setText(f"{angle_deg:.1f}°")

    def _on_mpc_movement_started(self, paddle_number: int) -> None:
        """Pokazuje operatorowi, która łopatka jest aktualnie sterowana."""
        self.window.mpc_status_label.setText(f"Ruch łopatki {paddle_number}...")

    def _on_mpc_movement_finished(
        self,
        paddle_number: int,
        angle_deg: float,
    ) -> None:
        """Przywraca status po udanym ruchu; pozycję ustawia osobny sygnał."""
        self.window.mpc_status_label.setText("Połączony")
        self.logger.info(
            f"MPC220: łopatka {paddle_number}, potwierdzony kąt={angle_deg:.2f}°."
        )

    def _set_mpc_controls_enabled(self, enabled: bool) -> None:
        """Blokuje tylko sterowanie MPC220 podczas operacji w workerze."""
        controls = [self.window.mpc_home_button, self.window.mpc_refresh_positions_button]
        for paddle_number in (1, 2):
            controls.extend(
                getattr(self.window, f"mpc{paddle_number}_{suffix}")
                for suffix in (
                    "left_large_button",
                    "left_medium_button",
                    "left_small_button",
                    "right_small_button",
                    "right_medium_button",
                    "right_large_button",
                    "set_button",
                )
            )
        for control in controls:
            control.setEnabled(enabled)

    def _on_device_connection_finished(self) -> None:
        self.pending_connections -= 1
        if self.pending_connections > 0:
            return

        self.window.connect_all_button.setEnabled(True)
        self.window.connect_all_button.setText("Połącz urządzenia")
        if self.tc200.connected and self.mpc220.connected:
            self.window.system_status_label.setText("Status: połączono wszystkie urządzenia")
        elif self.tc200.connected or self.mpc220.connected:
            self.window.system_status_label.setText("Status: połączono częściowo")
        else:
            self.window.system_status_label.setText("Status: błąd połączenia")

    def safe_stop(self) -> None:
        self.measurement_timer.stop()
        self.ads1263.stop_measurement()
        self.logger.info("Bezpieczne zatrzymanie wykonane.")
        if hasattr(self.system_control, "safe_stop"):
            self.system_control.safe_stop()

    def set_tc_temperature(self) -> None:
        temperature = self.window.tc_setpoint_input.value()
        self.tc200_worker.request_set_temperature.emit(temperature)
        self.logger.info(f"TC200: ustawianie temperatury {temperature:.1f} C")

    def toggle_tc_heater(self) -> None:
        self.tc200_worker.request_toggle_heater.emit()

    def set_mdt_voltage(self) -> None:
        self.logger.info("MDT694B: ustawianie napięcia (funkcja jeszcze niezaimplementowana).")

    def adjust_mpc_angle(self, paddle_number: int, step_degrees: float) -> None:
        """Zleca workerowi względną zmianę kąta realizowaną absolutnym ruchem."""
        self.mpc220_worker.request_adjust_angle.emit(paddle_number, step_degrees)

    def refresh_mpc_positions(self) -> None:
        """Zleca workerowi odczyt pozycji obu łopatek."""
        self.mpc220_worker.request_refresh_all_positions.emit()

    def set_mpc_angle(self, paddle_number: int) -> None:
        try:
            if paddle_number == 1:
                angle = self.window.mpc1_target_input.value()
            elif paddle_number == 2:
                angle = self.window.mpc2_target_input.value()
            else:
                raise ValueError(f"Nieprawidlowy numer lopatki: {paddle_number}")

            self.logger.info(f"MPC220: ustawiam łopatkę {paddle_number} na {angle:.2f}°.")
            self.mpc220_worker.request_set_angle.emit(paddle_number, angle)
        except Exception as error:
            self.logger.error(f"MPC220: nie udało się ustawić łopatki {paddle_number}: {error}")

    def home_mpc(self) -> None:
        """Zleca workerowi homing obu łopatek."""
        self.mpc220_worker.request_home_all.emit()

    def start_measurement(self) -> None:
        if self.measurement_timer.isActive():
            return

        try:
            self.ads1263.start_measurement()
            self.measurement_start_time = perf_counter()
            self.measurement_timer.start()
            self.logger.info("Rozpoczeto pomiar ADS1263")
        except Exception as error:
            self.logger.error(f"Błąd odczytu ADS1263: {error}")

    def _read_measurement_sample(self) -> None:
        try:
            voltage_in0, voltage_in1 = self.ads1263.read_samples()
            elapsed_time = perf_counter() - self.measurement_start_time
            self.plot_manager.add_sample(elapsed_time, voltage_in0, voltage_in1)
        except Exception as error:
            self.measurement_timer.stop()
            self.window.system_status_label.setText("Status: błąd pomiaru")
            self.logger.error(f"Błąd odczytu ADS1263: {error}")

    def stop_measurement(self) -> None:
        self.measurement_timer.stop()
        self.ads1263.stop_measurement()
        self.logger.info("Zatrzymano pomiar ADS1263.")

    def clear_plot(self) -> None:
        self.plot_manager.clear_plot()
        if self.measurement_timer.isActive():
            self.measurement_start_time = perf_counter()
        else:
            self.measurement_start_time = 0.0

    def save_measurement(self) -> None:
        self.logger.info("Zapis pomiaru do pliku jest jeszcze niezaimplementowany.")

    def __del__(self) -> None:
        if hasattr(self, "tc200_thread"):
            self.tc200_thread.quit()
            self.tc200_thread.wait()
        if hasattr(self, "mpc220_thread"):
            self.mpc220_thread.quit()
            self.mpc220_thread.wait()
