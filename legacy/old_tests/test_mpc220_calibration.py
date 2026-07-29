"""Testy jednostkowe niezależnych przeliczeń MPC220."""

import unittest

from app.mpc220_calibration import (
    angle_to_command,
    calculate_target_angle,
    raw_position_to_angle,
)


class MPC220CalibrationTests(unittest.TestCase):
    """Sprawdza aktualną kalibrację dwupunktową i ograniczenia GUI."""

    def test_angle_to_command_uses_calibration_points(self) -> None:
        """Kąty kalibracyjne dają oczekiwane jednostki absolutne."""
        self.assertEqual(angle_to_command(0.0), 0)
        self.assertEqual(angle_to_command(90.0), 753)

    def test_raw_position_to_angle_uses_counter_offset(self) -> None:
        """Surowe punkty 964 i 1717 odpowiadają 0 i 90 stopniom."""
        self.assertAlmostEqual(raw_position_to_angle(964), 0.0)
        self.assertAlmostEqual(raw_position_to_angle(1717), 90.0)

    def test_target_angle_is_clamped_to_gui_range(self) -> None:
        """Zmiana krokowa nie wychodzi poza zakres 1-160 stopni."""
        self.assertEqual(calculate_target_angle(45.0, 5.0), 50.0)
        self.assertEqual(calculate_target_angle(158.0, 5.0), 160.0)
        self.assertEqual(calculate_target_angle(3.0, -5.0), 1.0)


if __name__ == "__main__":
    unittest.main()
