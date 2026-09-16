"""Deklaratywny katalog wielkości, które aplikacja może rejestrować."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeasurementChannel:
    key: str
    label: str
    unit: str
    default_enabled: bool


MEASUREMENT_CHANNELS = (
    MeasurementChannel("in0_v", "Detektor IN0", "V", True),
    MeasurementChannel("in1_v", "Detektor IN1", "V", True),
    MeasurementChannel("temperature_c", "Temperatura TC200", "°C", False),
    MeasurementChannel("piezo_voltage_v", "Napięcie piezo", "V", False),
    MeasurementChannel("paddle_1_angle_deg", "Kąt łopatki MPC220 1", "°", False),
    MeasurementChannel("paddle_2_angle_deg", "Kąt łopatki MPC220 2", "°", False),
)
