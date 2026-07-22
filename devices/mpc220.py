"""Sterowanie kontrolerem polaryzacji Thorlabs MPC220."""

import time
from typing import Optional

import serial
import thorlabs_apt_protocol as apt


class MPC220:
    """Obsługa dwóch łopatek kontrolera polaryzacji MPC220."""

    DEST = 0x50
    SOURCE = 0x01

    PADDLE_1 = 0x01
    PADDLE_2 = 0x02
    ALL_PADDLES = 0b0011

    MIN_POSITION = 0.0
    MAX_POSITION = 10000.0

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 1.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.ser: Optional[serial.Serial] = None
        self.connected = False

    def connect(self) -> None:
        """Otwiera port i przygotowuje MPC220 do pracy."""

        if self.connected:
            return

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
            rtscts=True,
        )

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        self.send(apt.hw_no_flash_programming(self.DEST,self.SOURCE))

        self.send(
            apt.mod_set_chanenablestate(
                dest=self.DEST,
                source=self.SOURCE,
                chan_ident=self.ALL_PADDLES,
                enable_state=0x01,
            )
        )

        time.sleep(0.5)

        self.connected = True

    def disconnect(self) -> None:
        """Zamyka połączenie z MPC220."""

        if self.ser is not None:
            self.ser.close()
            self.ser = None

        self.connected = False

    def send(self, command: bytes, delay: float = 0.1) -> None:
        """Wysyła gotową ramkę APT do urządzenia."""

        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("MPC220 nie jest połączony.")

        self.ser.write(command)
        self.ser.flush()

        if delay > 0:
            time.sleep(delay)

    def move_absolute(
        self,
        paddle_number: int,
        position_degrees: float,
    ) -> None:
        """Przesuwa wybraną łopatkę do konkretnej pozycji."""

        paddle_id = self._get_paddle_id(paddle_number)
        self._validate_position(position_degrees)

        command = apt.mot_move_absolute(
            self.DEST,
            self.SOURCE,
            paddle_id,
            int(round(position_degrees)),
        )

        self.send(command)

    def move_relative(self, paddle_number: int, relative_degrees: float) -> None:
        """Przesuwa wybraną łopatkę o zadany dystans względny."""
        paddle_id = self._get_paddle_id(paddle_number)

        command = apt.mot_move_relative(
            self.DEST,
            self.SOURCE,
            paddle_id,
            int(round(relative_degrees)),
        )

        self.send(command)

    def home(self, paddle_number: int) -> None:
        """Wykonuje homing wybranej łopatki."""

        paddle_id = self._get_paddle_id(paddle_number)

        command = apt.mot_move_home(
            self.DEST,
            self.SOURCE,
            paddle_id,
        )

        self.send(command)

    def _get_paddle_id(self, paddle_number: int) -> int:
        """Zamienia numer łopatki z GUI na identyfikator APT."""

        if paddle_number == 1:
            return self.PADDLE_1

        if paddle_number == 2:
            return self.PADDLE_2

        raise ValueError(
            f"MPC220 ma tylko łopatki 1 i 2. "
            f"Otrzymano: {paddle_number}."
        )

    def _validate_position(self, position_degrees: float) -> None:
        """Sprawdza, czy podana pozycja jest bezpieczna."""

        if not self.MIN_POSITION <= position_degrees <= self.MAX_POSITION:
            raise ValueError(
                f"Pozycja musi mieścić się w zakresie "
                f"{self.MIN_POSITION}–{self.MAX_POSITION}°. "
                f"Otrzymano: {position_degrees}°."
            )
