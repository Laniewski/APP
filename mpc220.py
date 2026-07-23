"""Sterowanie kontrolerem polaryzacji Thorlabs MPC220."""

import time
import struct
from typing import Optional

import serial
import thorlabs_apt_protocol as apt


class MPC220:
    """Niskopoziomowa obsługa dwóch łopatek kontrolera MPC220.

    Ta klasa świadomie nie zna jednostki stopni. GUI i kontroler pracują
    w stopniach, natomiast tutaj wszystkie pozycje są całkowitymi jednostkami
    APT. Dzięki temu odpowiedzialność za kalibrację pozostaje poza transportem
    szeregowym i nie można przypadkowo wysłać stopni jako pozycji urządzenia.
    """

    DEST = 0x50
    SOURCE = 0x01

    PADDLE_1 = 0x01
    PADDLE_2 = 0x02
    ALL_PADDLES = 0b0011

    POSITION_RESPONSE_ID = 0x0412
    POSITION_RESPONSE_LENGTH = 12
    RESPONSE_DESTINATION = 0x01
    RESPONSE_SOURCE = DEST
    POSITION_STABLE_SAMPLES = 3
    POSITION_POLL_INTERVAL = 0.1
    MOVEMENT_TIMEOUT = 15.0

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

        self.send(apt.hw_no_flash_programming(self.DEST, self.SOURCE))

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

        # Clear stale serial input bytes before sending a new command.
        # To avoid old responses pozostawionych w buforze blokujących kolejne polecenia.
        try:
            self.ser.reset_input_buffer()
        except serial.SerialException:
            pass

        self.ser.write(command)
        self.ser.flush()

        if delay > 0:
            time.sleep(delay)

    def move_absolute_units(
        self,
        paddle_number: int,
        position_units: int,
    ) -> None:
        """Wysyła absolutną pozycję w jednostkach wewnętrznych APT.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.
            position_units: Całkowita pozycja MPC220, bez przeliczenia na
                stopnie w tej warstwie.

        Zwraca:
            ``None`` po zapisaniu ramki do portu.

        Wyjątki:
            ``RuntimeError`` przy zamkniętym porcie oraz ``ValueError`` dla
            nieprawidłowego numeru łopatki lub pozycji poza int32.
        """

        paddle_id = self._get_paddle_id(paddle_number)
        if not isinstance(position_units, int):
            raise TypeError("Pozycja MPC220 musi być liczbą całkowitą.")
        if not -(2**31) <= position_units <= 2**31 - 1:
            raise ValueError("Pozycja MPC220 nie mieści się w zakresie int32.")

        command = apt.mot_move_absolute(
            self.DEST,
            self.SOURCE,
            paddle_id,
            position_units,
        )

        self.send(command)

    def read_position_units(self, paddle_number: int) -> int:
        """Odczytuje surową pozycję łopatki z ``MOT_GET_POSCOUNTER``.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.

        Zwraca:
            Signed int32 little-endian z odpowiedzi urządzenia, w jednostkach
            wewnętrznego licznika MPC220.

        Wyjątki:
            ``RuntimeError`` przy braku odpowiedzi, błędnej długości ramki lub
            zamkniętym porcie. ``ValueError`` dla złego numeru łopatki.

        Przed zwróceniem wartości parser sprawdza identyfikator 0x0412,
        format long-frame, kierunek odpowiedzi i identyfikator kanału.
        """
        paddle_id = self._get_paddle_id(paddle_number)
        command = apt.mot_req_poscounter(self.DEST, self.SOURCE, paddle_id)
        self._prepare_for_command()
        self._write(command)
        response = self._read_position_frame(paddle_id)
        return struct.unpack_from("<i", response, 8)[0]

    def wait_until_stopped(
        self,
        paddle_number: int,
        timeout: float = MOVEMENT_TIMEOUT,
    ) -> None:
        """Czeka na ustabilizowanie pozycji po rozpoczęciu ruchu.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.
            timeout: Maksymalny czas oczekiwania w sekundach.

        Zwraca:
            ``None`` po trzech kolejnych identycznych odczytach.

        Wyjątki:
            ``TimeoutError`` gdy ruch nie ustabilizuje się w limicie, a także
            wyjątki komunikacji z ``read_position_units``.

        MPC220 nie udostępnia w obecnym lokalnym module wygodnego, gotowego
        sygnału zakończenia ruchu. Zamiast bezterminowego sleepu odczytujemy
        pozycję okresowo i wymagamy kilku kolejnych równych próbek. Timeout
        gwarantuje, że worker i GUI nie będą czekać w nieskończoność.
        """
        self._get_paddle_id(paddle_number)
        deadline = time.monotonic() + timeout
        previous_position: Optional[int] = None
        stable_samples = 0

        while time.monotonic() < deadline:
            current_position = self.read_position_units(paddle_number)
            if current_position == previous_position:
                stable_samples += 1
            else:
                stable_samples = 1

            if stable_samples >= self.POSITION_STABLE_SAMPLES:
                return

            previous_position = current_position
            time.sleep(self.POSITION_POLL_INTERVAL)

        raise TimeoutError(
            f"Timeout oczekiwania na zakończenie ruchu łopatki {paddle_number}."
        )

    def home_paddle(self, paddle_number: int) -> None:
        """Wykonuje homing jednej łopatki i czeka na stabilizację.

        Parametry:
            paddle_number: Numer łopatki 1 albo 2.

        Zwraca:
            ``None`` po wysłaniu homingu i zakończeniu oczekiwania.

        Wyjątki:
            Wyjątki portu, walidacji kanału, odczytu pozycji i timeoutu ruchu.
        """
        paddle_id = self._get_paddle_id(paddle_number)
        self.send(apt.mot_move_home(self.DEST, self.SOURCE, paddle_id))
        self.wait_until_stopped(paddle_number)

    def home_all(self) -> None:
        """Wykonuje homing obu łopatek kolejno.

        Zwraca:
            ``None`` po zakończeniu homingu łopatki 1 i 2.

        Wyjątki:
            Przekazuje wyjątek pierwszej operacji, która nie zakończy się
            poprawnie. Kolejność jest jawna, aby nie przeciążać jednocześnie
            kontrolera dwoma komendami ruchu.
        """
        for paddle_number in (1, 2):
            self.home_paddle(paddle_number)

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

    def _prepare_for_command(self) -> None:
        """Usuwa stare bajty, aby odpowiedź dotyczyła bieżącego żądania."""
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("MPC220 nie jest połączony.")
        try:
            self.ser.reset_input_buffer()
        except serial.SerialException as error:
            raise RuntimeError("Nie udało się wyczyścić bufora MPC220.") from error

    def _write(self, command: bytes) -> None:
        """Zapisuje ramkę APT i czeka na opróżnienie bufora nadawczego."""
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("MPC220 nie jest połączony.")
        self.ser.write(command)
        self.ser.flush()

    def _read_position_frame(self, expected_paddle_id: int) -> bytes:
        """Odbiera i waliduje jedną ramkę ``MOT_GET_POSCOUNTER``.

        Parser jest celowo lokalny dla tego komunikatu. Usuwa nieznane lub
        niepełne dane z początku bufora, respektuje długość long-frame i czeka
        do ``self.timeout`` zamiast zakładać, że jeden ``read`` zwróci całość.
        """
        if self.ser is None or not self.ser.is_open:
            raise RuntimeError("MPC220 nie jest połączony.")

        deadline = time.monotonic() + self.timeout
        buffer = bytearray()
        while time.monotonic() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                buffer.extend(self.ser.read(waiting))
            else:
                buffer.extend(self.ser.read(1))

            while len(buffer) >= 6:
                message_id, data_length = struct.unpack_from("<HH", buffer)
                long_form = bool(buffer[4] & 0x80)

                if message_id != self.POSITION_RESPONSE_ID or not long_form:
                    del buffer[0]
                    continue
                if data_length != 6:
                    del buffer[0]
                    continue

                frame_length = data_length + 6
                if len(buffer) < frame_length:
                    break

                frame = bytes(buffer[:frame_length])
                del buffer[:frame_length]
                destination = frame[4] & 0x7F
                source = frame[5]
                channel_id = struct.unpack_from("<H", frame, 6)[0]
                if destination != self.RESPONSE_DESTINATION:
                    raise RuntimeError(
                        f"Nieoczekiwany adres docelowy odpowiedzi: {destination:#04x}."
                    )
                if source != self.RESPONSE_SOURCE:
                    raise RuntimeError(
                        f"Nieoczekiwane źródło odpowiedzi: {source:#04x}."
                    )
                if channel_id != expected_paddle_id:
                    raise RuntimeError(
                        "Odpowiedź pozycji dotyczy innej łopatki: "
                        f"oczekiwano {expected_paddle_id:#04x}, "
                        f"otrzymano {channel_id:#04x}."
                    )
                return frame

        raise TimeoutError("Timeout oczekiwania na pełną odpowiedź pozycji MPC220.")
