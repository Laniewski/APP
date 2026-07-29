"""Minimalny sterownik kontrolera temperatury TC200."""

import re

import serial


class TC200Error(RuntimeError):
    """Błąd komunikacji ze sterownikiem TC200."""


class TC200:
    """Obsługuje podstawową komunikację szeregową z TC200."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 1.0,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection: serial.Serial | None = None

    @property
    def is_connected(self) -> bool:
        """Informuje, czy port szeregowy jest obecnie otwarty."""
        return (
            self.serial_connection is not None
            and self.serial_connection.is_open
        )

    def connect(self) -> None:
        """Otwiera połączenie szeregowe z TC200."""
        if self.is_connected:
            return

        self.serial_connection = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

        self.serial_connection.reset_input_buffer()

    def read_current_temperature(self) -> float:
        """Odczytuje aktualną temperaturę z TC200 w stopniach Celsjusza."""
        if not self.is_connected:
            raise TC200Error("TC200 nie jest połączony.")

        connection = self.serial_connection

        if connection is None:
            raise TC200Error("Brak połączenia szeregowego.")

        connection.reset_input_buffer()
        connection.write(b"tact?\r")
        connection.flush()

        raw_response = connection.read_until(b">")

        if b">" not in raw_response:
            raise TC200Error(
                "TC200 nie odpowiedział przed upływem limitu czasu."
            )

        response = raw_response.decode(
            "ascii",
            errors="replace",
        )

        numbers = re.findall(
            r"[-+]?\d+(?:\.\d+)?",
            response,
        )

        if not numbers:
            raise TC200Error(
                f"Nie udało się odczytać temperatury. "
                f"Odpowiedź TC200: {response!r}"
            )

        return float(numbers[-1])

    def close(self) -> None:
        """Zamyka połączenie z TC200."""
        if self.serial_connection is not None:
            if self.serial_connection.is_open:
                self.serial_connection.close()

            self.serial_connection = None