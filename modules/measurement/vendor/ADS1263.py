"""Adaptacja oryginalnego sterownika Waveshare ADS1263.

Zachowuje oryginalny kod i konfigurację, ale importuje konfigurację GPIO/SPI
z pakietu `modules.measurement.vendor.config` zamiast z lokalnego modułu
`config.py`.
"""

from __future__ import annotations

from modules.measurement.vendor import config

ADS1263_GAIN = {
    "ADS1263_GAIN_1": 0,
    "ADS1263_GAIN_2": 1,
    "ADS1263_GAIN_4": 2,
    "ADS1263_GAIN_8": 3,
    "ADS1263_GAIN_16": 4,
    "ADS1263_GAIN_32": 5,
    "ADS1263_GAIN_64": 6,
}

ADS1263_DRATE = {
    "ADS1263_38400SPS": 0xF,
    "ADS1263_19200SPS": 0xE,
    "ADS1263_14400SPS": 0xD,
    "ADS1263_7200SPS": 0xC,
    "ADS1263_4800SPS": 0xB,
    "ADS1263_2400SPS": 0xA,
    "ADS1263_1200SPS": 0x9,
    "ADS1263_400SPS": 0x8,
    "ADS1263_100SPS": 0x7,
    "ADS1263_60SPS": 0x6,
    "ADS1263_50SPS": 0x5,
    "ADS1263_20SPS": 0x4,
    "ADS1263_16d6SPS": 0x3,
    "ADS1263_10SPS": 0x2,
    "ADS1263_5SPS": 0x1,
    "ADS1263_2d5SPS": 0x0,
}

ADS1263_DELAY = {
    "ADS1263_DELAY_0s": 0,
    "ADS1263_DELAY_8d7us": 1,
    "ADS1263_DELAY_17us": 2,
    "ADS1263_DELAY_35us": 3,
    "ADS1263_DELAY_169us": 4,
    "ADS1263_DELAY_139us": 5,
    "ADS1263_DELAY_278us": 6,
    "ADS1263_DELAY_555us": 7,
    "ADS1263_DELAY_1d1ms": 8,
    "ADS1263_DELAY_2d2ms": 9,
    "ADS1263_DELAY_4d4ms": 10,
    "ADS1263_DELAY_8d8ms": 11,
}

ADS1263_REG = {
    "REG_ID": 0,
    "REG_POWER": 1,
    "REG_INTERFACE": 2,
    "REG_MODE0": 3,
    "REG_MODE1": 4,
    "REG_MODE2": 5,
    "REG_INPMUX": 6,
    "REG_OFCAL0": 7,
    "REG_OFCAL1": 8,
    "REG_OFCAL2": 9,
    "REG_FSCAL0": 10,
    "REG_FSCAL1": 11,
    "REG_FSCAL2": 12,
    "REG_IDACMUX": 13,
    "REG_IDACMAG": 14,
    "REG_REFMUX": 15,
    "REG_TDACP": 16,
    "REG_TDACN": 17,
    "REG_GPIOCON": 18,
    "REG_GPIODIR": 19,
    "REG_GPIODAT": 20,
    "REG_ADC2CFG": 21,
    "REG_ADC2MUX": 22,
    "REG_ADC2OFC0": 23,
    "REG_ADC2OFC1": 24,
    "REG_ADC2FSC0": 25,
    "REG_ADC2FSC1": 26,
}

ADS1263_CMD = {
    "CMD_RESET": 0x06,
    "CMD_START1": 0x08,
    "CMD_STOP1": 0x0A,
    "CMD_START2": 0x0C,
    "CMD_STOP2": 0x0E,
    "CMD_RDATA1": 0x12,
    "CMD_RDATA2": 0x14,
    "CMD_SYOCAL1": 0x16,
    "CMD_SYGCAL1": 0x17,
    "CMD_SFOCAL1": 0x19,
    "CMD_SYOCAL2": 0x1B,
    "CMD_SYGCAL2": 0x1C,
    "CMD_SFOCAL2": 0x1E,
    "CMD_RREG": 0x20,
    "CMD_RREG2": 0x00,
    "CMD_WREG": 0x40,
    "CMD_WREG2": 0x00,
}


class ADS1263:
    DATA_READY_ATTEMPTS = 400000

    def __init__(self) -> None:
        self.rst_pin = config.RST_PIN
        self.cs_pin = config.CS_PIN
        self.drdy_pin = config.DRDY_PIN
        self.ScanMode = 1

    def ADS1263_reset(self) -> None:
        config.digital_write(self.rst_pin, 1)
        config.delay_ms(200)
        config.digital_write(self.rst_pin, 0)
        config.delay_ms(200)
        config.digital_write(self.rst_pin, 1)
        config.delay_ms(200)

    def ADS1263_WriteCmd(self, reg: int) -> None:
        config.digital_write(self.cs_pin, 0)
        config.spi_writebyte([reg])
        config.digital_write(self.cs_pin, 1)

    def ADS1263_WriteReg(self, reg: int, data: int) -> None:
        config.digital_write(self.cs_pin, 0)
        config.spi_writebyte([ADS1263_CMD["CMD_WREG"] | reg, 0x00, data])
        config.digital_write(self.cs_pin, 1)

    def ADS1263_ReadData(self, reg: int) -> list[int]:
        config.digital_write(self.cs_pin, 0)
        config.spi_writebyte([ADS1263_CMD["CMD_RREG"] | reg, 0x00])
        data = config.spi_readbytes(1)
        config.digital_write(self.cs_pin, 1)
        return data

    def ADS1263_CheckSum(self, val: int, byt: int) -> int:
        s = 0
        mask = 0xFF
        while val:
            s += val & mask
            val >>= 8
        s += 0x9B
        return (s & 0xFF) ^ byt

    def ADS1263_WaitDRDY(self) -> None:
        i = 0
        while True:
            i += 1
            if config.digital_read(self.drdy_pin) == 0:
                return
            if i >= self.DATA_READY_ATTEMPTS:
                raise TimeoutError("Przekroczono limit oczekiwania na DRDY ADS1263.")

    def ADS1263_ReadChipID(self) -> int:
        chip_id = self.ADS1263_ReadData(ADS1263_REG["REG_ID"])
        return chip_id[0] >> 5

    def ADS1263_SetMode(self, mode: int) -> None:
        self.ScanMode = mode

    def ADS1263_ConfigADC(self, gain: int, drate: int) -> None:
        # Konfiguracja sprawdzona sprzętowo w sterowniku z gałęzi main.
        mode2 = 0x80 | ((gain & 0x07) << 4) | (drate & 0x0F)
        self.ADS1263_WriteReg(ADS1263_REG["REG_MODE2"], mode2)
        self.ADS1263_WriteReg(ADS1263_REG["REG_REFMUX"], 0x24)
        self.ADS1263_WriteReg(ADS1263_REG["REG_MODE0"], ADS1263_DELAY["ADS1263_DELAY_35us"])
        self.ADS1263_WriteReg(ADS1263_REG["REG_MODE1"], 0x84)
        # Status i checksum są częścią ramki RDATA1 używanej poniżej.
        self.ADS1263_WriteReg(ADS1263_REG["REG_INTERFACE"], 0x05)

    def ADS1263_SetChannal(self, channel: int) -> None:
        if not 0 <= channel <= 9:
            raise ValueError("Kanał single-ended ADS1263 musi być w zakresie 0–9.")
        mux = (channel << 4) | 0x0A
        self.ADS1263_WriteReg(ADS1263_REG["REG_INPMUX"], mux)

    def ADS1263_init_ADC1(self, rate_name: str = "ADS1263_400SPS") -> int:
        self.ADS1263_reset()
        chip_id = self.ADS1263_ReadChipID()
        if chip_id != 0x01:
            raise RuntimeError(
                f"Nieprawidłowy Chip ID ADS1263: oczekiwano 0x01, odczytano {chip_id:#04x}."
            )
        self.ADS1263_WriteCmd(ADS1263_CMD["CMD_STOP1"])
        self.ADS1263_ConfigADC(ADS1263_GAIN["ADS1263_GAIN_1"], ADS1263_DRATE[rate_name])
        self.ADS1263_WriteCmd(ADS1263_CMD["CMD_START1"])
        return 0

    def ADS1263_Read_ADC_Data(self) -> int:
        config.digital_write(self.cs_pin, 0)
        try:
            for _ in range(self.DATA_READY_ATTEMPTS):
                config.spi_writebyte([ADS1263_CMD["CMD_RDATA1"]])
                status = config.spi_readbytes(1)
                if len(status) != 1:
                    raise RuntimeError("Niepełny status odpowiedzi ADC1.")
                if status[0] & 0x40:
                    break
            else:
                raise TimeoutError("Timeout oczekiwania na dane ADC1 ADS1263.")

            frame = config.spi_readbytes(5)
            if len(frame) != 5:
                raise RuntimeError(
                    f"Niepełna ramka ADC1: oczekiwano 5 bajtów, otrzymano {len(frame)}."
                )
            raw = (
                ((frame[0] << 24) & 0xFF000000)
                | ((frame[1] << 16) & 0x00FF0000)
                | ((frame[2] << 8) & 0x0000FF00)
                | (frame[3] & 0x000000FF)
            )
            if self.ADS1263_CheckSum(raw, frame[4]) != 0:
                raise RuntimeError("Błędna checksum ramki ADC1 ADS1263.")
            return raw
        finally:
            config.digital_write(self.cs_pin, 1)

    def ADS1263_GetChannalValue(self, channel: int) -> int:
        if self.ScanMode != 0:
            raise RuntimeError("ADS1263 nie pracuje w trybie single-ended.")
        self.ADS1263_SetChannal(channel)
        self.ADS1263_WaitDRDY()
        return self.ADS1263_Read_ADC_Data()

    def module_exit(self) -> None:
        try:
            config.module_exit()
        except Exception:
            pass
