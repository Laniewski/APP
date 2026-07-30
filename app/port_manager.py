"""Skanowanie i rezerwowanie portów szeregowych."""

from dataclasses import dataclass
from threading import Lock

from serial.tools import list_ports as serial_list_ports


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str


class PortManager:
    def __init__(self, port_provider=None) -> None:
        self._port_provider = port_provider or serial_list_ports.comports
        self._reservations: dict[str, object] = {}
        self._lock = Lock()

    def list_ports(self) -> list[PortInfo]:
        return [
            PortInfo(port.device, port.description or "Nieznane urządzenie")
            for port in self._port_provider()
        ]

    def reserve(self, port: str, owner: object) -> bool:
        with self._lock:
            current = self._reservations.get(port)
            if current is not None and current is not owner:
                return False
            self._reservations[port] = owner
            return True

    def release(self, port: str, owner: object) -> None:
        with self._lock:
            if self._reservations.get(port) is owner:
                del self._reservations[port]

    def is_available(self, port: str) -> bool:
        with self._lock:
            return port not in self._reservations
