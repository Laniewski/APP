"""Logika ADS1263: SPI, konfiguracja, start/stop i odczyt próbek."""
import sys 
from pathlib import Path


class ADS1263:
    def __init__(self) -> None:
        self.connected = False
        self.measuring = False

        self.adc = None
        self.reference_voltage = 5.0

    def connect(self) -> None:
        if self.connected:
            return

        import ADS1263 as waveshare_driver

        self.adc = waveshare_driver.ADS1263()

        result = self.adc.ADS1263_init_ADC1("ADS1263_400SPS")
        if result == -1:
            raise RuntimeError("Nie udało się uruchomić ADS1263")

        self.adc.ADS1263_SetMode(0)
        self.connected = True

    def disconnect(self) -> None:
        self.measuring = False
        self.adc = None
        self.connected = False

    def start_measurement(self) -> None:
        if not self.connected:
            self.connect()
        self.measuring = True

    def stop_measurement(self) -> None:
        self.measuring = False

    def _raw_to_voltage(self, raw_value: int) -> float:
        # Obsługa znaku 32-bitowej wartości surowej
        if raw_value & 0x80000000:
            raw_value = raw_value - 0x100000000
        return raw_value * self.reference_voltage / 0x7FFFFFFF

    def read_samples(self) -> tuple[float, float]:
        if not self.connected or self.adc is None:
            raise RuntimeError("ADS1263 nie jest podłączony.")
        if not self.measuring:
            raise RuntimeError("Pomiar nie jest uruchomiony.")

        # Odczyty na obu kanałach w jednym cyklu pomiarowym.
        raw_in0 = self.adc.ADS1263_GetChannalValue(0)
        raw_in1 = self.adc.ADS1263_GetChannalValue(1)

        voltage_in0 = self._raw_to_voltage(raw_in0)
        voltage_in1 = self._raw_to_voltage(raw_in1)
        return voltage_in0, voltage_in1
    
            
