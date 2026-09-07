"""Runtime metrics collection.

Canonical responsibility:
- Aggregates throughput, step timings, and training progress metrics.
- Formats metric payloads for RuntimeEvent emission.

Important boundary:
- Metric computation must not block the training critical path.

Status:
- Scaffold only.
"""

from __future__ import annotations


class MetricsCollector:
    """Collects and exposes training metrics for monitoring."""

    def __init__(self) -> None:
        raise NotImplementedError
