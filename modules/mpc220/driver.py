"""Niskopoziomowy sterownik MPC220, operujący wyłącznie jednostkami APT."""

import struct
import time

import serial

from vendor import thorlabs_apt_protocol as apt


class MPC220Driver:
    DEST = 0x50
    SOURCE = 0x01
    PADDLE_1 = 0x01
    PADDLE_2 = 0x02
    ALL_PADDLES = 0x03
    POSITION_RESPONSE_ID = 0x0412
    POSITION_RESPONSE_LENGTH = 12
    RESPONSE_DESTINATION = SOURCE
    RESPONSE_SOURCE = DEST
    POSITION_STABLE_SAMPLES = 3
    POSITION_POLL_INTERVAL = 0.1
    MOVEMENT_TIMEOUT = 15.0

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0,
                 serial_factory=serial.Serial) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial_factory = serial_factory
        self.ser = None

    @property
    def connected(self) -> bool:
        return bool(self.ser is not None and self.ser.is_open)

    def connect(self) -> None:
        if self.connected:
            return
        try:
            self.ser = self._serial_factory(
                port=self.port, baudrate=self.baudrate, timeout=self.timeout,
                write_timeout=self.timeout, rtscts=True,
            )
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.send(apt.hw_no_flash_programming(self.DEST, self.SOURCE))
            self.send(apt.mod_set_chanenablestate(
                dest=self.DEST, source=self.SOURCE,
                chan_ident=self.ALL_PADDLES, enable_state=0x01,
            ))
            time.sleep(0.5)
        except Exception:
            self.close()
            raise

    def send(self, command: bytes, delay: float = 0.1) -> None:
        self._prepare_for_command()
        self._write(command)
        if delay:
            time.sleep(delay)

    def move_absolute_units(self, paddle_number: int, position_units: int) -> None:
        paddle_id = self._get_paddle_id(paddle_number)
        if not isinstance(position_units, int):
            raise TypeError("Pozycja MPC220 musi być liczbą całkowitą.")
        if not -(2**31) <= position_units <= 2**31 - 1:
            raise ValueError("Pozycja MPC220 nie mieści się w zakresie int32.")
        self.send(apt.mot_move_absolute(
            self.DEST, self.SOURCE, paddle_id, position_units
        ))

    move_absolute = move_absolute_units

    def read_position_units(self, paddle_number: int) -> int:
        paddle_id = self._get_paddle_id(paddle_number)
        self._prepare_for_command()
        self._write(apt.mot_req_poscounter(self.DEST, self.SOURCE, paddle_id))
        return struct.unpack_from("<i", self._read_position_frame(paddle_id), 8)[0]

    def wait_until_stopped(self, paddle_number: int,
                           timeout: float = MOVEMENT_TIMEOUT) -> None:
        self._get_paddle_id(paddle_number)
        deadline = time.monotonic() + timeout
        previous = None
        stable = 0
        while time.monotonic() < deadline:
            current = self.read_position_units(paddle_number)
            stable = stable + 1 if current == previous else 1
            if stable >= self.POSITION_STABLE_SAMPLES:
                return
            previous = current
            time.sleep(self.POSITION_POLL_INTERVAL)
        raise TimeoutError(
            f"Timeout oczekiwania na zakończenie ruchu łopatki {paddle_number}."
        )

    def home_paddle(self, paddle_number: int) -> None:
        paddle_id = self._get_paddle_id(paddle_number)
        self.send(apt.mot_move_home(self.DEST, self.SOURCE, paddle_id))
        self.wait_until_stopped(paddle_number)

    def home_all(self) -> None:
        for paddle_number in (1, 2):
            self.home_paddle(paddle_number)

    def home(self, paddle_number=None) -> None:
        self.home_all() if paddle_number is None else self.home_paddle(paddle_number)

    def _get_paddle_id(self, paddle_number: int) -> int:
        if paddle_number == 1:
            return self.PADDLE_1
        if paddle_number == 2:
            return self.PADDLE_2
        raise ValueError(f"MPC220 ma tylko łopatki 1 i 2. Otrzymano: {paddle_number}.")

    def _prepare_for_command(self) -> None:
        connection = self._require_connection()
        connection.reset_input_buffer()

    def _write(self, command: bytes) -> None:
        connection = self._require_connection()
        connection.write(command)
        connection.flush()

    def _require_connection(self):
        if not self.connected:
            raise RuntimeError("MPC220 nie jest połączony.")
        return self.ser

    def _read_position_frame(self, expected_paddle_id: int) -> bytes:
        connection = self._require_connection()
        deadline = time.monotonic() + self.timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            waiting = connection.in_waiting
            chunk = connection.read(waiting if waiting else 1)
            if chunk:
                buffer.extend(chunk)
            while len(buffer) >= 6:
                message_id, data_length = struct.unpack_from("<HH", buffer)
                long_form = bool(buffer[4] & 0x80)
                if (message_id != self.POSITION_RESPONSE_ID or not long_form
                        or data_length != 6):
                    del buffer[0]
                    continue
                frame_length = 6 + data_length
                if len(buffer) < frame_length:
                    break
                frame = bytes(buffer[:frame_length])
                destination = frame[4] & 0x7F
                source = frame[5]
                channel = struct.unpack_from("<H", frame, 6)[0]
                if destination != self.RESPONSE_DESTINATION:
                    raise RuntimeError("Nieoczekiwany adres docelowy odpowiedzi.")
                if source != self.RESPONSE_SOURCE:
                    raise RuntimeError("Nieoczekiwane źródło odpowiedzi.")
                if channel != expected_paddle_id:
                    raise RuntimeError("Odpowiedź pozycji dotyczy innej łopatki.")
                return frame
        raise TimeoutError("Timeout oczekiwania na pełną odpowiedź pozycji MPC220.")

    def close(self) -> None:
        connection, self.ser = self.ser, None
        if connection is not None:
            try:
                if connection.is_open:
                    connection.close()
            except (OSError, serial.SerialException):
                pass

    disconnect = close
