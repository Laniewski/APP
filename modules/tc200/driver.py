"""Niezależna od Qt komunikacja szeregowa z Thorlabs TC200."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

import serial


class TC200Error(RuntimeError):
    pass


class TC200ConnectionError(TC200Error):
    pass


class TC200TimeoutError(TC200Error):
    pass


class TC200ResponseError(TC200Error):
    pass


@dataclass(frozen=True)
class TC200Status:
    raw: int
    heater_enabled: bool
    cycle_mode: bool
    sensor: str
    units: str
    sensor_alarm: bool
    cycle_paused: bool
    tmax_alarm: bool

    @property
    def alarms(self) -> tuple[str, ...]:
        result = []
        if self.sensor_alarm:
            result.append("Alarm czujnika temperatury")
        if self.tmax_alarm:
            result.append("Przekroczono limit TMAX")
        return tuple(result)


class TC200Driver:
    BAUDRATE = 115200
    COMMAND_TERMINATOR = b"\r"
    RESPONSE_TERMINATOR = b">"
    MIN_TEMPERATURE = 20.0
    MAX_TEMPERATURE = 200.0

    def __init__(
        self,
        port: str,
        timeout: float = 1.0,
        serial_factory: Callable[..., object] = serial.Serial,
        settle_time: float = 0.3,
    ) -> None:
        self.port = port
        self.timeout = timeout
        self._serial_factory = serial_factory
        self._settle_time = settle_time
        self._serial = None

    @property
    def is_connected(self) -> bool:
        return bool(self._serial is not None and self._serial.is_open)

    def connect(self) -> None:
        if self.is_connected:
            return
        try:
            self._serial = self._serial_factory(
                port=self.port,
                baudrate=self.BAUDRATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            if self._settle_time:
                time.sleep(self._settle_time)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except (OSError, serial.SerialException) as exc:
            self.close()
            raise TC200ConnectionError(
                f"Nie można otworzyć portu {self.port}: {exc}"
            ) from exc

    def identify(self) -> str:
        identity = self.send_command("*idn?")
        if "tc200" not in identity.lower():
            raise TC200ResponseError(
                f"Urządzenie na porcie {self.port} nie identyfikuje się jako TC200."
            )
        return identity

    def send_command(self, command: str) -> str:
        connection = self._require_connection()
        normalized = command.strip().lower()
        if not normalized or "\r" in normalized or "\n" in normalized:
            raise ValueError("Komenda TC200 musi być pojedynczą, niepustą linią.")
        payload = normalized.encode("ascii") + self.COMMAND_TERMINATOR
        try:
            connection.reset_input_buffer()
            connection.write(payload)
            connection.flush()
            raw = connection.read_until(self.RESPONSE_TERMINATOR)
        except (OSError, serial.SerialException) as exc:
            raise TC200ConnectionError(f"Błąd portu {self.port}: {exc}") from exc
        if not raw or self.RESPONSE_TERMINATOR not in raw:
            raise TC200TimeoutError(
                f"TC200 nie odpowiedział na {normalized!r} w ciągu {self.timeout:.1f} s."
            )
        response = self._clean_response(raw, normalized)
        if not response:
            raise TC200ResponseError(f"Pusta odpowiedź na komendę {normalized!r}.")
        lowered = response.lower()
        if "command error" in lowered or "cmd_" in lowered or lowered.startswith("error"):
            raise TC200ResponseError(f"TC200 odrzucił komendę {normalized!r}: {response}")
        return response

    @classmethod
    def _clean_response(cls, raw: bytes, command: str) -> str:
        decoded = raw.decode("ascii", errors="replace").replace("\x00", "")
        before_prompt = decoded.rsplit(">", 1)[0]
        lines = [line.strip() for line in before_prompt.replace("\r", "\n").split("\n")]
        lines = [line for line in lines if line and line.lower() != command.lower()]
        return "\n".join(lines).strip()

    @staticmethod
    def _parse_float(response: str) -> float:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", response)
        if match is None:
            raise TC200ResponseError(f"Brak wartości liczbowej w odpowiedzi: {response!r}")
        return float(match.group(0))

    def read_temperature(self) -> float:
        return self._parse_float(self.send_command("tact?"))

    def read_setpoint(self) -> float:
        return self._parse_float(self.send_command("tset?"))

    def set_temperature(self, value: float) -> float:
        value = float(value)
        if not self.MIN_TEMPERATURE <= value <= self.MAX_TEMPERATURE:
            raise ValueError("Temperatura musi być w zakresie 20,0–200,0°C.")
        self.send_command(f"tset={value:.1f}")
        return self.read_setpoint()

    def read_status(self) -> TC200Status:
        response = self.send_command("stat?")
        match = re.search(r"(?<![0-9A-Za-z])(?:0x)?([0-9A-Fa-f]{1,2})(?![0-9A-Za-z])", response)
        if match is None:
            raise TC200ResponseError(f"Nieprawidłowy status TC200: {response!r}")
        value = int(match.group(1), 16)
        sensor_bits = (value >> 2) & 0b11
        unit_bits = (value >> 4) & 0b11
        sensors = {0: "TH10K", 1: "PTC100", 2: "PTC1000"}
        units = {0: "K", 1: "°C", 2: "°F"}
        return TC200Status(
            raw=value,
            heater_enabled=bool(value & 0x01),
            cycle_mode=bool(value & 0x02),
            sensor=sensors.get(sensor_bits, "Nieznany"),
            units=units.get(unit_bits, "Nieznane"),
            sensor_alarm=bool(value & 0x40),
            cycle_paused=bool(value & 0x80),
            tmax_alarm="tmax error" in response.lower(),
        )

    def set_heater(self, enabled: bool) -> TC200Status:
        status = self.read_status()
        if status.heater_enabled != bool(enabled):
            self.send_command("ens")
            status = self.read_status()
        return status

    def close(self) -> None:
        connection, self._serial = self._serial, None
        if connection is not None:
            try:
                if connection.is_open:
                    connection.close()
            except (OSError, serial.SerialException):
                pass

    disconnect = close

    def _require_connection(self):
        if not self.is_connected:
            raise TC200ConnectionError("TC200 nie jest połączony.")
        return self._serial

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_args) -> None:
        self.close()
