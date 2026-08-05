"""Adapter sprzętowy ADS1263 dla modułu pomiarowego.

Używa sprawdzonej konfiguracji z gałęzi `main`, ale działa w nowej architekturze
modułowej i nie wykonuje importów GPIO/SPI podczas importowania aplikacji.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ADS1263Driver:
    def __init__(self, *, reference_voltage: float = 5.0) -> None:
        self.reference_voltage = float(reference_voltage)
        self._adc = None
        self._connected = False

    def connect(self) -> None:
        try:
            from modules.measurement.vendor import ADS1263 as waveshare_driver
            from modules.measurement.vendor import config
        except Exception as exc:  # pragma: no cover - zależne od środowiska
            raise RuntimeError(
                "Nie można załadować sterownika ADS1263: brakuje bibliotek GPIO/SPI."
            ) from exc

        try:
            config.module_init()
        except Exception as exc:
            raise RuntimeError(f"Nie udało się zainicjalizować GPIO/SPI ADS1263: {exc}") from exc

        try:
            self._adc = waveshare_driver.ADS1263()
            self._adc.ADS1263_init_ADC1("ADS1263_400SPS")
            self._adc.ADS1263_SetMode(0)
            self._connected = True
            logger.info("ADS1263 podłączono i zainicjalizowano.")
        except Exception as exc:
            try:
                self.close()
            except Exception:
                pass
            raise RuntimeError(f"Nie udało się zainicjalizować ADS1263: {exc}") from exc

    def _require_connected(self) -> None:
        if not self._connected or self._adc is None:
            raise RuntimeError("ADS1263 nie jest podłączony.")

    def _raw_to_voltage(self, raw_value: int) -> float:
        if raw_value & 0x80000000:
            raw_value -= 0x100000000
        return raw_value * self.reference_voltage / 0x7FFFFFFF

    def start_measurement(self) -> None:
        self._require_connected()
        self._adc.ADS1263_WriteCmd(0x08)

    def read_sample(self) -> tuple[float, float]:
        self._require_connected()
        try:
            in0 = self._adc.ADS1263_GetChannalValue(0)
            in1 = self._adc.ADS1263_GetChannalValue(1)
        except Exception as exc:
            raise RuntimeError(f"Nie udało się odczytać kanałów ADS1263: {exc}") from exc
        return self._raw_to_voltage(in0), self._raw_to_voltage(in1)

    def stop_measurement(self) -> None:
        if self._adc is not None and self._connected:
            try:
                self._adc.ADS1263_WriteCmd(0x0A)
            except Exception:
                pass

    def close(self) -> None:
        try:
            self.stop_measurement()
        except Exception:
            pass
        self._connected = False
        if self._adc is not None:
            try:
                self._adc.module_exit()
            except Exception:
                pass
            self._adc = None
