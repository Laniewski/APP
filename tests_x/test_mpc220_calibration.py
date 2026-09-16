import unittest

from modules.mpc220.calibration import (angle_to_command, calculate_target_angle,
                                        clamp_angle, raw_position_to_angle)


class MPC220CalibrationTests(unittest.TestCase):
    def test_calibration_points(self):
        self.assertEqual(angle_to_command(0), 0)
        self.assertEqual(angle_to_command(90), 753)
        self.assertAlmostEqual(raw_position_to_angle(964), 0)
        self.assertAlmostEqual(raw_position_to_angle(1717), 90)

    def test_limits_and_steps(self):
        self.assertEqual(clamp_angle(-10), 1)
        self.assertEqual(clamp_angle(200), 160)
        self.assertEqual(calculate_target_angle(3, -10), 1)
        self.assertEqual(calculate_target_angle(157, 10), 160)


if __name__ == "__main__":
    unittest.main()
