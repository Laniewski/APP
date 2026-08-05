"""Przeliczenia między stopniami aplikacji i jednostkami APT MPC220."""

MPC_MIN_ANGLE_DEG = 1.0
MPC_MAX_ANGLE_DEG = 160.0
MPC_CALIBRATION_ANGLE_DEG = 90.0
MPC_COMMAND_AT_CALIBRATION_ANGLE = 753
MPC_RAW_AT_ZERO_DEG = 964
MPC_RAW_AT_CALIBRATION_ANGLE = 1717
# Bieżące liniowe przybliżenie wyznaczono metodą nazywaną w projekcie „fi²”.
MPC_UNITS_PER_DEGREE = 753.0 / 90.0


def angle_to_command(angle_deg: float) -> int:
    """Zamienia kąt na absolutną komendę (offset komendy wynosi zero)."""
    return round(angle_deg * MPC_UNITS_PER_DEGREE)


def raw_position_to_angle(raw_position: int) -> float:
    """Zamienia surowy licznik pozycji na kąt."""
    return (raw_position - MPC_RAW_AT_ZERO_DEG) / MPC_UNITS_PER_DEGREE


def clamp_angle(angle_deg: float) -> float:
    return max(MPC_MIN_ANGLE_DEG, min(MPC_MAX_ANGLE_DEG, angle_deg))


def calculate_target_angle(current_angle_deg: float, delta_angle_deg: float) -> float:
    return clamp_angle(current_angle_deg + delta_angle_deg)
