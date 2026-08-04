"""Bufor danych pomiarowych z czasem względnym od początku pomiaru."""

from __future__ import annotations

import time


class DataBuffer:
    def __init__(self) -> None:
        self.times: list[float] = []
        self.in0_values: list[float] = []
        self.in1_values: list[float] = []
        self._start_time = time.perf_counter()

    def add_sample(self, timestamp: float, in0: float, in1: float) -> None:
        sample_time = float(timestamp)
        if not self.times:
            self._start_time = sample_time
        relative_time = max(0.0, sample_time - self._start_time)
        self.times.append(relative_time)
        self.in0_values.append(float(in0))
        self.in1_values.append(float(in1))

    def clear(self) -> None:
        self.times.clear()
        self.in0_values.clear()
        self.in1_values.clear()
        self._start_time = time.perf_counter()

    def get_visible_data(self, window_seconds: float = 20.0) -> tuple[list[float], list[float], list[float]]:
        if window_seconds <= 0:
            return [], [], []
        boundary = float(window_seconds)
        filtered = [
            (t, i0, i1)
            for t, i0, i1 in zip(self.times, self.in0_values, self.in1_values)
            if t >= 0.0 and t <= boundary
        ]
        if not filtered:
            return [], [], []
        times, in0, in1 = zip(*filtered)
        return list(times), list(in0), list(in1)

    def get_all_data(self) -> tuple[list[float], list[float], list[float]]:
        return self.times, self.in0_values, self.in1_values
