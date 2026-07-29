"""Logika MDT694B: połączenie, napięcie, zakres i błędy."""
class MDT694B:
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None: pass
    def disconnect(self) -> None: pass
    def read_voltage(self) -> float: raise NotImplementedError
    def read_voltage_limit(self) -> float: raise NotImplementedError
    def set_voltage(self, value: float) -> None: pass
    def read_errors(self) -> list[str]: raise NotImplementedError
