"""Wspólne funkcje do obsługi portów szeregowych."""
from serial.tools import list_ports


def scan_serial_ports():
    """Zwraca listę portów szeregowych dostępnych w systemie."""
    ports = list_ports.comports()
    return list(ports)