"""Bounded scalar metric accumulation, independent of management availability."""

import math
from threading import Lock


class MetricsCollector:
    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[str, tuple[int, float]] = {}

    def record(self, name: str, value: float) -> None:
        if name not in (
            "compute_ms",
            "upload_ms",
            "barrier_wait_ms",
            "aggregate_ms",
            "checkpoint_ms",
            "optimizer_ms",
            "bytes_sent",
            "bytes_received",
        ):
            raise ValueError("Unsupported Runtime metric")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Metric must be finite and nonnegative")
        with self._lock:
            count, total = self._values.get(name, (0, 0.0))
            self._values[name] = count + 1, total + value

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        with self._lock:
            return {
                name: {"count": count, "total": total, "mean": total / count}
                for name, (count, total) in self._values.items()
            }
