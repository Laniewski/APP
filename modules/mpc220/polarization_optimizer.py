"""Nieblokująca maszyna stanów automatycznej optymalizacji polaryzacji."""

from __future__ import annotations

import math
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot


PIEZO_MIN_V = 80.0
PIEZO_MAX_V = 150.0
PIEZO_SPEED_V_S = 20.0
PIEZO_HALF_CYCLE_S = (PIEZO_MAX_V - PIEZO_MIN_V) / PIEZO_SPEED_V_S

COORDINATE_SPEED_DEG_S = 5.0
COORDINATE_TARGET_V = 0.40
COORDINATE_MAX_TIME_S = 40.0

ADAPTIVE_SPEED_DEG_S = 2.0
ADAPTIVE_MAX_TIME_S = 10.0
ADAPTIVE_DIRECTION_STEP_DEG = 45.0

MAXIMUM_DEPARTURE_V = 0.010
MAX_DEPARTURE_WINDOWS = 2

MPC_MIN_DEG = 1.0
MPC_MAX_DEG = 160.0
MPC_COMMAND_INTERVAL_MS = 120
MIN_WINDOW_SAMPLES = 3
PIEZO_PREPARE_DELAY_MS = 500

START_POINTS = [
    {"name": "lower_left", "p1": 25.0, "p2": 45.0,
     "directions": [(+1.0, 0.0), (0.0, +1.0), (-1.0, 0.0), (0.0, -1.0)]},
    {"name": "lower_right", "p1": 125.0, "p2": 50.0,
     "directions": [(-1.0, 0.0), (0.0, +1.0), (+1.0, 0.0), (0.0, -1.0)]},
    {"name": "upper_left", "p1": 20.0, "p2": 125.0,
     "directions": [(+1.0, 0.0), (0.0, -1.0), (-1.0, 0.0), (0.0, +1.0)]},
    {"name": "upper_right", "p1": 140.0, "p2": 140.0,
     "directions": [(-1.0, 0.0), (0.0, -1.0), (+1.0, 0.0), (0.0, +1.0)]},
    {"name": "emergency_corner", "p1": 1.0, "p2": 1.0,
     "directions": [(+1.0, 0.0), (0.0, +1.0), (-1.0, 0.0), (0.0, -1.0)]},
]


def percentile(values: list[float], percent: float) -> float:
    """Liniowo interpolowany percentyl, bez zależności od NumPy."""
    if not values:
        raise ValueError("Nie można policzyć percentyla pustego zbioru.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def differential_amplitude(samples: list[tuple[float, float]]) -> float:
    differences = [in0 - in1 for in0, in1 in samples]
    return (percentile(differences, 95.0) - percentile(differences, 5.0)) / 2.0


class PolarizationOptimizer(QObject):
    """Koordynuje ciągły ruch MPC, półcykle piezo i istniejące próbki ADS."""

    progress = Signal(dict)
    finished = Signal(dict)
    error = Signal(str)
    piezo_set_requested = Signal(float)
    piezo_ramp_requested = Signal(float, float)
    piezo_stop_requested = Signal()

    def __init__(
        self,
        move: Callable[[float, float], tuple[float, float]],
        read_position: Callable[[], tuple[float, float]],
        move_and_wait: Callable[[float, float], tuple[float, float]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._move = move
        self._read_position = read_position
        self._move_and_wait = move_and_wait
        self._timer: QTimer | None = None
        self._active = False
        self._cancelled = False
        self._samples: list[tuple[float, float]] = []
        self.window_log: list[dict] = []

    @property
    def active(self) -> bool:
        return self._active

    @Slot()
    def start(self) -> None:
        if self._active:
            return
        try:
            self._active = True
            self._cancelled = False
            self._started_at = time.monotonic()
            self._start_index = 0
            self._window_id = 0
            self._piezo_direction = +1
            self._global_best = None
            self._best_measurement_time_s = None
            self.window_log.clear()
            self._emit_progress("Przygotowanie")
            self._prepare_start()
        except Exception as exc:
            self._fail(exc)

    @Slot()
    def cancel(self) -> None:
        if not self._active:
            return
        self._cancelled = True
        self._stop_timer()
        self.piezo_stop_requested.emit()
        self._complete("CANCELLED")

    @Slot(float, float)
    def add_sample(self, in0: float, in1: float) -> None:
        if self._active and hasattr(self, "_window_started_at"):
            self._samples.append((float(in0), float(in1)))

    def _prepare_start(self) -> None:
        if self._cancelled:
            return
        if self._start_index >= len(START_POINTS):
            self._finish_not_found()
            return
        point = START_POINTS[self._start_index]
        self._emit_progress("Zmiana punktu startowego")
        self._position = self._move_and_wait(point["p1"], point["p2"])
        self._direction_index = 0
        self._direction = point["directions"][0]
        self._phase = "Coordinate"
        self._phase_started_at = time.monotonic()
        self._previous_score = None
        self._departure_windows = 0
        self._adaptive_turn_sign = 1.0
        self.piezo_set_requested.emit(PIEZO_MIN_V)
        QTimer.singleShot(PIEZO_PREPARE_DELAY_MS, self._begin_window)

    def _begin_window(self) -> None:
        if not self._active or self._cancelled:
            return
        try:
            self._position = self._read_position()
            self._window_start_position = self._position
            self._trajectory_origin = self._position
            self._window_started_at = time.monotonic()
            self._trajectory_started_at = self._window_started_at
            self._samples = []
            target = PIEZO_MAX_V if self._piezo_direction > 0 else PIEZO_MIN_V
            self.piezo_ramp_requested.emit(target, PIEZO_SPEED_V_S)
            self._timer = QTimer(self)
            self._timer.setInterval(MPC_COMMAND_INTERVAL_MS)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            self._emit_progress(self._phase)
        except Exception as exc:
            self._fail(exc)

    @Slot()
    def _tick(self) -> None:
        if self._cancelled:
            self.cancel()
            return
        try:
            now = time.monotonic()
            elapsed = now - self._window_started_at
            trajectory_elapsed = now - self._trajectory_started_at
            speed = self._phase_speed()
            p1 = self._trajectory_origin[0] + self._direction[0] * speed * trajectory_elapsed
            p2 = self._trajectory_origin[1] + self._direction[1] * speed * trajectory_elapsed
            target = (self._clamp(p1), self._clamp(p2))
            hit_boundary = target != (p1, p2)
            self._position = self._move(*target)
            if hit_boundary:
                if self._phase == "Coordinate":
                    self._next_coordinate_direction()
                else:
                    self._reflect_to_interior(target)
                self._trajectory_origin = target
                self._trajectory_started_at = now
            if elapsed >= PIEZO_HALF_CYCLE_S:
                self._finish_window()
        except Exception as exc:
            self._fail(exc)

    def _finish_window(self) -> None:
        self._stop_timer()
        end_position = self._read_position()
        start_position = self._window_start_position
        mean_position = (
            (start_position[0] + end_position[0]) / 2.0,
            (start_position[1] + end_position[1]) / 2.0,
        )
        score = None
        if len(self._samples) >= MIN_WINDOW_SAMPLES:
            score = differential_amplitude(self._samples)
            self._remember_best(score, mean_position)
        self._window_id += 1
        entry = {
            "timestamp": time.time(), "phase": self._phase,
            "start_index": self._start_index + 1,
            "start_name": START_POINTS[self._start_index]["name"],
            "window_id": self._window_id, "speed_deg_s": self._phase_speed(),
            "piezo_direction": self._piezo_direction,
            "p1_start": start_position[0], "p1_end": end_position[0],
            "p1_mean": mean_position[0], "p2_start": start_position[1],
            "p2_end": end_position[1], "p2_mean": mean_position[1],
            "A_D": score, "best_A_D": self._best_score(),
            "sample_count": len(self._samples),
        }
        self.window_log.append(entry)
        self._piezo_direction *= -1
        self._position = end_position
        self._emit_progress(self._phase, score)
        if self._phase == "Coordinate":
            self._after_coordinate(score)
        else:
            self._after_adaptive(score)

    def _after_coordinate(self, score: float | None) -> None:
        if score is not None and score >= COORDINATE_TARGET_V:
            self._phase = "Adaptive"
            self._phase_started_at = time.monotonic()
            self._previous_score = score
            self._departure_windows = 0
            self._begin_window()
            return
        if score is not None and self._previous_score is not None and score < self._previous_score:
            self._next_coordinate_direction()
        if score is not None:
            self._previous_score = score
        if time.monotonic() - self._phase_started_at >= COORDINATE_MAX_TIME_S:
            self._next_start()
        else:
            self._begin_window()

    def _after_adaptive(self, score: float | None) -> None:
        best = self._best_score()
        if score is not None and best is not None and best - score > MAXIMUM_DEPARTURE_V:
            self._departure_windows += 1
        else:
            self._departure_windows = 0
        if self._departure_windows >= MAX_DEPARTURE_WINDOWS:
            self._return_to_best_and_complete("SUCCESS")
            return
        if score is not None and self._previous_score is not None and score < self._previous_score:
            self._rotate_adaptive_direction()
        if score is not None:
            self._previous_score = score
        if time.monotonic() - self._phase_started_at >= ADAPTIVE_MAX_TIME_S:
            self._next_start()
        else:
            self._begin_window()

    def _next_coordinate_direction(self) -> None:
        directions = START_POINTS[self._start_index]["directions"]
        self._direction_index = (self._direction_index + 1) % len(directions)
        self._direction = directions[self._direction_index]

    def _rotate_adaptive_direction(self) -> None:
        angle = math.radians(ADAPTIVE_DIRECTION_STEP_DEG * self._adaptive_turn_sign)
        x, y = self._direction
        self._direction = (
            x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
        )
        self._adaptive_turn_sign *= -1.0

    def _reflect_to_interior(self, position: tuple[float, float]) -> None:
        x, y = self._direction
        if position[0] <= MPC_MIN_DEG and x < 0 or position[0] >= MPC_MAX_DEG and x > 0:
            x = -x
        if position[1] <= MPC_MIN_DEG and y < 0 or position[1] >= MPC_MAX_DEG and y > 0:
            y = -y
        self._direction = (x, y)

    def _next_start(self) -> None:
        self.piezo_stop_requested.emit()
        self._start_index += 1
        self._prepare_start()

    def _remember_best(self, score: float, position: tuple[float, float]) -> None:
        if self._global_best is None or score > self._global_best[0]:
            self._global_best = (score, position[0], position[1])
            self._best_measurement_time_s = time.monotonic() - self._started_at

    def _return_to_best_and_complete(self, status: str) -> None:
        if self._global_best is not None:
            _, p1, p2 = self._global_best
            self._position = self._move_and_wait(p1, p2)
        self._complete(status)

    def _finish_not_found(self) -> None:
        self._return_to_best_and_complete("NOT_FOUND")

    def _complete(self, status: str) -> None:
        self._stop_timer()
        self.piezo_stop_requested.emit()
        self._active = False
        total_time_s = time.monotonic() - self._started_at
        result = {
            "status": status,
            "best_amplitude_v": self._global_best[0] if self._global_best else None,
            "best_p1_deg": self._global_best[1] if self._global_best else None,
            "best_p2_deg": self._global_best[2] if self._global_best else None,
            "best_measurement_time_s": self._best_measurement_time_s,
            "total_time_s": total_time_s,
            # Dotychczasowe nazwy pozostają dla zgodności z istniejącym API.
            "elapsed_s": total_time_s,
            "A_D": self._global_best[0] if self._global_best else None,
            "p1": self._global_best[1] if self._global_best else None,
            "p2": self._global_best[2] if self._global_best else None,
            "windows": list(self.window_log),
        }
        self.finished.emit(result)

    def _fail(self, exc: Exception) -> None:
        self._stop_timer()
        self.piezo_stop_requested.emit()
        self._active = False
        self.error.emit(str(exc))

    def _emit_progress(self, phase: str, score: float | None = None) -> None:
        self.progress.emit({
            "phase": phase, "start_index": self._start_index + 1,
            "start_count": len(START_POINTS), "A_D": score,
            "best_A_D": self._best_score(),
        })

    def _phase_speed(self) -> float:
        return COORDINATE_SPEED_DEG_S if self._phase == "Coordinate" else ADAPTIVE_SPEED_DEG_S

    def _best_score(self) -> float | None:
        return self._global_best[0] if self._global_best else None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(MPC_MIN_DEG, min(MPC_MAX_DEG, value))

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
