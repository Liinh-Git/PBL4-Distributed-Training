"""Weighted FP32 aggregation of a frozen selection, without membership policy."""

from dataclasses import dataclass

import numpy as np

from pbl4.runtime.synchronization.update_plan import UpdatePlan


@dataclass(frozen=True, slots=True)
class AggregatedGradient:
    plan: UpdatePlan
    parameter_manifest_hash: str
    _values: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "_values", bytes(self._values))

    @property
    def gradient(self) -> np.ndarray:
        return np.frombuffer(self._values, dtype=np.float32)


class GradientAggregator:
    def aggregate(self, plan: UpdatePlan) -> AggregatedGradient:
        selected = plan.contributions
        if not selected or plan.total_sample_count <= 0:
            raise ValueError("Empty sample selection")
        first = selected[0]
        shape = first.gradient.shape
        # Accumulate in FP64 to avoid overflowing sample_count * FP32 gradient.
        total = np.zeros(shape, dtype=np.float64)
        for c in selected:
            if (
                c.parameter_manifest_hash != first.parameter_manifest_hash
                or c.gradient.shape != shape
                or c.gradient.dtype != np.float32
                or type(c.sample_count) is not int
                or c.sample_count <= 0
            ):
                raise ValueError("Incompatible gradient selection")
            total += c.gradient.astype(np.float64) * c.sample_count
        with np.errstate(over="raise", invalid="raise"):
            values = (total / plan.total_sample_count).astype(np.float32)
        if not np.isfinite(values).all():
            raise ValueError("Nonfinite aggregate")
        return AggregatedGradient(plan, first.parameter_manifest_hash, values.tobytes())
