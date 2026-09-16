import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from modules.mpc220.panel import MPC220Panel
from modules.mpc220.polarization_optimizer import (
    MPC_MAX_DEG,
    MPC_MIN_DEG,
    START_POINTS,
    PolarizationOptimizer,
    differential_amplitude,
    percentile,
)


class PolarizationOptimizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_objective_uses_percentile_span_of_full_difference_window(self):
        samples = [(value, 0.0) for value in range(21)]
        self.assertAlmostEqual(percentile(list(range(21)), 5), 1.0)
        self.assertAlmostEqual(percentile(list(range(21)), 95), 19.0)
        self.assertAlmostEqual(differential_amplitude(samples), 9.0)

    def test_multistart_order_ranges_and_inward_first_directions(self):
        self.assertEqual([point["name"] for point in START_POINTS], [
            "lower_left", "lower_right", "upper_left", "upper_right",
            "emergency_corner",
        ])
        self.assertEqual([point["directions"][0] for point in START_POINTS], [
            (+1.0, 0.0), (-1.0, 0.0), (+1.0, 0.0), (-1.0, 0.0),
            (+1.0, 0.0),
        ])
        for point in START_POINTS:
            self.assertLessEqual(MPC_MIN_DEG, point["p1"])
            self.assertLessEqual(point["p1"], MPC_MAX_DEG)
            self.assertLessEqual(MPC_MIN_DEG, point["p2"])
            self.assertLessEqual(point["p2"], MPC_MAX_DEG)

    def test_button_is_between_port_controls_and_paddle_panels(self):
        panel = MPC220Panel()
        layout = panel.layout()
        self.assertIs(layout.itemAt(1).widget(), panel.optimization_button)
        self.assertEqual(layout.itemAt(3).widget().title(), "Łopatka 1")
        self.assertTrue(panel.optimization_button.isEnabled())
        self.assertFalse(panel.optimization_status.isVisible())

    def test_progress_stays_hidden_but_errors_are_visible(self):
        panel = MPC220Panel()
        panel.show_optimization_progress({"phase": "Coordinate"})
        self.assertTrue(panel.optimization_status.isHidden())
        panel.show_optimization_error("Brak: aktywny pomiar ADS1263.")
        self.assertFalse(panel.optimization_status.isHidden())
        self.assertEqual(
            panel.optimization_status.text(),
            "Brak: aktywny pomiar ADS1263.",
        )

    def test_result_contains_best_point_and_both_times(self):
        optimizer = PolarizationOptimizer(
            lambda p1, p2: (p1, p2),
            lambda: (12.0, 34.0),
            lambda p1, p2: (p1, p2),
        )
        results = []
        optimizer.finished.connect(results.append)
        optimizer._active = True
        optimizer._started_at = 100.0
        optimizer._global_best = None
        optimizer._best_measurement_time_s = None
        optimizer.window_log = []
        with patch(
            "modules.mpc220.polarization_optimizer.time.monotonic",
            side_effect=[131.4, 138.2],
        ):
            optimizer._remember_best(0.432, (126.4, 52.7))
            optimizer._complete("SUCCESS")

        result = results[0]
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["best_amplitude_v"], 0.432)
        self.assertEqual(result["best_p1_deg"], 126.4)
        self.assertEqual(result["best_p2_deg"], 52.7)
        self.assertAlmostEqual(result["best_measurement_time_s"], 31.4)
        self.assertAlmostEqual(result["total_time_s"], 38.2)


if __name__ == "__main__":
    unittest.main()
