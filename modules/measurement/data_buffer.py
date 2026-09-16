"""Bufor danych pomiarowych z czasem względnym od początku pomiaru."""

from __future__ import annotations

import time


class DataBuffer:
    def __init__(self) -> None:
        self.measurement_records: list[dict[str, float | None]] = []
        self._start_time = time.perf_counter()

    def add_sample(self, timestamp: float, in0: float, in1: float) -> None:
        """Zachowuje kompatybilność z dotychczasowym API dla IN0/IN1."""
        self.add_record(timestamp, {"in0_v": float(in0), "in1_v": float(in1)})

    def add_record(
        self,
        timestamp: float,
        values: dict[str, float | None],
    ) -> dict[str, float | None]:
        sample_time = float(timestamp)
        if not self.measurement_records:
            self._start_time = sample_time
        relative_time = max(0.0, sample_time - self._start_time)
        record: dict[str, float | None] = {"time_s": relative_time}
        record.update(values)
        self.measurement_records.append(record)
        return record

    def clear(self) -> None:
        self.measurement_records.clear()
        self._start_time = time.perf_counter()

    def get_records(self) -> list[dict[str, float | None]]:
        return self.measurement_records

    def get_visible_data(self, window_seconds: float = 20.0) -> tuple[list[float], list[float], list[float]]:
        if window_seconds <= 0:
            return [], [], []

        if not self.measurement_records:
            return [], [], []

        latest_time = float(self.measurement_records[-1]["time_s"])
        window_start = max(0.0, latest_time - float(window_seconds))
        filtered = [
            (record["time_s"], record["in0_v"], record["in1_v"])
            for record in self.measurement_records
            if window_start <= float(record["time_s"]) <= latest_time
        ]
        if not filtered:
            return [], [], []
        times, in0, in1 = zip(*filtered)
        return list(times), list(in0), list(in1)

    def get_all_data(self) -> tuple[list[float], list[float], list[float]]:
        return (
            [float(record["time_s"]) for record in self.measurement_records],
            [float(record["in0_v"]) for record in self.measurement_records],
            [float(record["in1_v"]) for record in self.measurement_records],
        )
