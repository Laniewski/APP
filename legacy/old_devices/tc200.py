"""Logika TC200: połączenie, komendy, temperatury, enable/disable, limity i błędy."""

import re
import time

import serial

class TC200:
    def __init__(self, port: str = "/dev/ttyUSB1", baudrate :int = 115200,timeout: float = 1.0) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        
        self.serial_connection = None
        self.connected = False

    def connect(self) -> None:
        if self.connected:
            return
        
        self.serial_connection = serial.Serial(
            port = self.port,
            baudrate= self.baudrate,
            bytesize= serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits= serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout= self.timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        
        time.sleep(0.3)
        
        self.serial_connection.reset_input_buffer()
        self.serial_connection.reset_output_buffer()
        
        self.connected = True
        
    def disconnect(self) -> None:
        if self.serial_connection is not None:
            try:
                if self.serial_connection.is_open:
                    self.serial_connection.close()
            except serial.SerialException:
                pass
        self.serial_connection = None
        self.connected = False
    
    def _require_connection(self):
        if (
            self.serial_connection is None
            or not self.serial_connection.is_open
        ):
            raise RuntimeError("TC200 nie jest połaczont.")
        
        return self.serial_connection
        
    def _send_command(self, command: str) -> str:
        
        connection = self._require_connection()
        
        command= command.strip().lower()
        
        connection.reset_input_buffer()
        message = command + "\r"
        connection.write(message.encode("ascii"))
        connection.flush()

        response = connection.read_until(b">")
        if not response:
            raise TimeoutError(
                f"TC200 nie odpowiedział na komendę {command!r} w czasie {self.timeout:.1f} s."
            )
        decoded = response.decode("ascii", errors="replace")
        if ">" not in decoded:
            raise RuntimeError(
                f"Nieprawidłowa odpowiedź TC200 na komendę {command!r}: {decoded!r}"
            )
        return decoded.strip()
        
    @staticmethod
    def _extract_float(response: str) -> float:
            match = re.search(r"[-+]?\d+(?:\.\d)?", response)
            
            if match is None:
                raise RuntimeError(f"Nie znaleziono wartości w odpowiedzie TC200: {response!r}")
                
            return float(match.group())
        
    def read_temperature(self) -> float: 
    
        response = self._send_command("tact?")
        return self._extract_float(response)
    
    def read_setpoint(self) -> float: 
    
        response = self._send_command("tset?")
        return self._extract_float(response)
    
    def set_temperature(self, value: float) -> None: 
        value = float(value)
        
        if not 20.0 <= value <= 200.0:
            raise ValueError("Temperatura musi być w zakresie 20.0-200.0 C")
            
        self._send_command(f"tset={value:.1f}")
        
    def _read_status_value(self) -> int:
        response = self._send_command("stat?")
        
        match = re.search(r"(?:0x)?([0-9a-fA-F]{1,2})",response)
        
        if match is None:
            raise RuntimeError(f"Nie udało się odczytać statusu TC200: {response!r}")
        
        return int(match.group(1), 16)
        
    def enable_heater(self) -> None:
        if not self.read_heater_state():
            self._send_command("ens")
        
    def disable_heater(self) -> None:
        if self.read_heater_state():
            self._send_command("ens")
            
    def read_heater_state(self) -> bool:
        status = self._read_status_value()
        return bool(status & 0b00000001)
        
    def read_limits(self) -> tuple[float, float]: raise NotImplementedError
    def read_errors(self) -> list[str]: raise NotImplementedError
