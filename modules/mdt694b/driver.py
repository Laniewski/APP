"""Sterownik szeregowy Thorlabs MDT694B (firmware 1.10)."""

import re
import time

import serial


class MDT694BError(RuntimeError):
    pass


class MDT694BDriver:
    BAUDRATE = 115200
    TERMINATOR = b"\r"
    PROMPTS = (b">", b"*")

    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = BAUDRATE,
                 timeout: float = 1.0, serial_factory=serial.Serial,
                 settle_time: float = 0.3) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial_factory = serial_factory
        self._settle_time = settle_time
        self._serial = None
        self._last_errors = []

    @property
    def connected(self) -> bool:
        return bool(self._serial is not None and self._serial.is_open)

    def connect(self) -> None:
        if self.connected:
            return
        try:
            self._serial = self._serial_factory(
                port=self.port, baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=self.timeout,
                write_timeout=self.timeout, xonxoff=False, rtscts=False,
                dsrdtr=False,
            )
            if self._settle_time:
                time.sleep(self._settle_time)
            # Odbierz prompt startowy, ale nie zmieniaj trwałej konfiguracji.
            if self._serial.in_waiting:
                self._serial.read(self._serial.in_waiting)
            self._serial.reset_output_buffer()
            identity = self._send_command("id?")
            if "MDT694B" not in identity.upper():
                raise MDT694BError(
                    f"Urządzenie na porcie {self.port} nie jest MDT694B: {identity!r}"
                )
        except Exception:
            self.disconnect()
            raise

    def _require_connection(self):
        if not self.connected:
            raise MDT694BError("MDT694B nie jest połączony.")
        return self._serial

    def _read_response(self) -> bytes:
        connection = self._require_connection()
        deadline = time.monotonic() + self.timeout
        response = bytearray()
        while time.monotonic() < deadline:
            chunk = connection.read(1)
            if chunk:
                response.extend(chunk)
                if chunk in self.PROMPTS:
                    return bytes(response)
        if not response:
            raise TimeoutError(f"MDT694B nie odpowiedział w ciągu {self.timeout:.1f} s.")
        raise TimeoutError(f"Odpowiedź MDT694B nie zawiera promptu: {bytes(response)!r}")

    @staticmethod
    def _clean_response(raw: bytes, command: str) -> str:
        decoded = raw.decode("ascii", errors="replace")
        if not decoded or decoded[-1] not in ">*":
            raise MDT694BError(f"Nieprawidłowa odpowiedź MDT694B: {decoded!r}")
        lines = [line.strip() for line in decoded[:-1].replace("\n", "\r").split("\r")]
        lines = [line for line in lines if line]
        if lines and lines[0] == command:
            lines.pop(0)
        cleaned = "\n".join(lines)
        if "!" in cleaned:
            raise MDT694BError(f"MDT694B odrzucił komendę {command!r}: {cleaned}")
        return cleaned

    def _send_command(self, command: str) -> str:
        command = command.strip()
        if not command or "\r" in command or "\n" in command:
            raise ValueError("Komenda MDT694B musi być pojedynczą, niepustą linią.")
        connection = self._require_connection()
        try:
            connection.reset_input_buffer()
            connection.write(command.encode("ascii") + self.TERMINATOR)
            connection.flush()
            return self._clean_response(self._read_response(), command)
        except Exception as exc:
            self._last_errors.append(str(exc))
            raise

    @staticmethod
    def _extract_float(response: str) -> float:
        match = re.search(r"[-+]?\d+(?:\.\d+)?", response)
        if match is None:
            raise MDT694BError(f"Brak wartości liczbowej w odpowiedzi: {response!r}")
        return float(match.group())

    def read_voltage(self) -> float:
        return self._extract_float(self._send_command("xvoltage?"))

    def read_voltage_limit(self) -> float:
        value = self._extract_float(self._send_command("vlimit?"))
        return {0.0: 75.0, 1.0: 100.0, 2.0: 150.0}.get(value, value)

    def read_voltage_range(self) -> tuple[float, float]:
        axis_min = self._extract_float(self._send_command("xmin?"))
        axis_max = self._extract_float(self._send_command("xmax?"))
        system_min = self._extract_float(self._send_command("sysmin?"))
        system_max = self._extract_float(self._send_command("sysmax?"))
        limit = self.read_voltage_limit()
        minimum = max(axis_min, system_min)
        maximum = min(axis_max, system_max, limit)
        if minimum > maximum:
            raise MDT694BError(
                f"Nieprawidłowy efektywny zakres napięcia: {minimum}–{maximum} V."
            )
        return minimum, maximum

    def set_voltage(self, value: float) -> float:
        value = float(value)
        minimum, maximum = self.read_voltage_range()
        if not minimum <= value <= maximum:
            raise ValueError(f"Napięcie musi być w zakresie {minimum:.2f}–{maximum:.2f} V.")
        self._send_command(f"xvoltage={value:.3f}")
        return self.read_voltage()

    def read_errors(self) -> list[str]:
        return list(self._last_errors)

    def disconnect(self) -> None:
        connection, self._serial = self._serial, None
        if connection is not None:
            try:
                if connection.is_open:
                    connection.close()
            except (OSError, serial.SerialException):
                pass

    close = disconnect
