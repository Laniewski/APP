"""Leniwa konfiguracja GPIO/SPI dla ADS1263.

To jest adaptacja oryginalnego pliku Waveshare z zachowaniem informacji o autorze
oraz licencji. Importy `RPi.GPIO` i `spidev` nie są wykonywane na poziomie
modułu, aby aplikacja mogła importować się na komputerze bez Raspberry Pi.
"""

from __future__ import annotations

import time
from typing import Any

RST_PIN = 18
CS_PIN = 22
DRDY_PIN = 17

_backend: Any = None


def _get_backend() -> Any:
    global _backend
    if _backend is not None:
        return _backend

    try:
        import spidev  # type: ignore
        import RPi.GPIO as GPIO  # type: ignore
    except Exception as exc:  # pragma: no cover - zależne od platformy
        raise RuntimeError(
            "Na tym komputerze brakuje wsparcia Raspberry Pi GPIO/SPI dla ADS1263."
        ) from exc

    class _Hardware:
        def __init__(self) -> None:
            self.GPIO = GPIO
            self.SPI = spidev.SpiDev(0, 0)

        def digital_write(self, pin: int, value: int) -> None:
            self.GPIO.output(pin, value)

        def digital_read(self, pin: int) -> int:
            return int(self.GPIO.input(pin))

        def delay_ms(self, delaytime: float) -> None:
            time.sleep(delaytime / 1000.0)

        def spi_writebyte(self, data: list[int]) -> None:
            self.SPI.writebytes(data)

        def spi_readbytes(self, count: int) -> list[int]:
            return self.SPI.readbytes(count)

        def module_init(self) -> int:
            self.GPIO.setmode(self.GPIO.BCM)
            self.GPIO.setwarnings(False)
            self.GPIO.setup(self.__class__.RST_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.__class__.CS_PIN, self.GPIO.OUT)
            self.GPIO.setup(self.__class__.DRDY_PIN, self.GPIO.IN, pull_up_down=self.GPIO.PUD_UP)
            self.SPI.max_speed_hz = 2000000
            self.SPI.mode = 0b01
            return 0

        def module_exit(self) -> None:
            try:
                self.SPI.close()
            except Exception:
                pass
            try:
                self.GPIO.output(RST_PIN, 0)
                self.GPIO.output(CS_PIN, 0)
            except Exception:
                pass
            try:
                self.GPIO.cleanup()
            except Exception:
                pass

    _backend = _Hardware()
    return _backend


def module_init() -> int:
    return _get_backend().module_init()


def module_exit() -> None:
    try:
        _get_backend().module_exit()
    except RuntimeError:
        pass


def digital_write(pin: int, value: int) -> None:
    _get_backend().digital_write(pin, value)


def digital_read(pin: int) -> int:
    return _get_backend().digital_read(pin)


def delay_ms(delaytime: float) -> None:
    _get_backend().delay_ms(delaytime)


def spi_writebyte(data: list[int]) -> None:
    _get_backend().spi_writebyte(data)


def spi_readbytes(count: int) -> list[int]:
    return _get_backend().spi_readbytes(count)
