"""Unit tests for Runtime Training Metrics aggregation and golden oracle (Plan V3 Minimal)."""

import math
import numpy as np
import pytest

from pbl4.runtime.contribution import Contribution
from pbl4.runtime.coordinator import (
    _accumulate_epoch_contributions,
    _compute_epoch_metrics_payload,
)


def _make_contribution(
    worker_id: int,
    sample_count: int,
    loss: float | None,
    correct_count: int | None,
    step_id: int = 1,
) -> Contribution:
    return Contribution.from_gradient(
        np.array([1.0, 2.0], dtype=np.float32),
        attempt_id="att-1",
        session_id=worker_id + 1,
        worker_id=worker_id,
        operation_id=step_id,
        step_id=step_id,
        model_version=step_id - 1,
        shard_id=0,
        batch_id=0,
        batch_ordinal=0,
        sample_count=sample_count,
        parameter_manifest_hash="hash",
        tensor_id=0,
        loss=loss,
        correct_count=correct_count,
    )


def _new_accumulator():
    return {
        "sample_count": 0,
        "weighted_loss_sum": 0.0,
        "correct_count": 0,
        "valid": True,
    }


def test_golden_metrics_oracle():
    """Golden: workers [0, 1, 2] with samples [4, 7, 5], total = 16.
    losses: [1.0, 2.0, 4.0] -> loss = (4*1 + 7*2 + 5*4)/16 = 38/16 = 2.375
    correct counts: [1, 5, 2] -> accuracy = 100 * (1+5+2)/16 = 800/16 = 50.0%
    Payload must contain EXACTLY 4 fields.
    """
    acc = _new_accumulator()
    c1 = _make_contribution(0, 4, 1.0, 1)
    c2 = _make_contribution(1, 7, 2.0, 5)
    c3 = _make_contribution(2, 5, 4.0, 2)

    _accumulate_epoch_contributions(acc, [c1, c2, c3])
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)

    assert set(payload.keys()) == {"epoch_index", "sample_count", "training_loss", "training_accuracy"}
    assert payload["epoch_index"] == 0
    assert payload["sample_count"] == 16
    assert payload["training_loss"] == pytest.approx(2.375)
    assert payload["training_accuracy"] == pytest.approx(50.0)


def test_multi_step_epoch_accumulation():
    """Two consecutive committed steps in epoch, each with full worker cohort."""
    acc = _new_accumulator()

    # Step 1: W0 (20, 0.8, 16), W1 (30, 1.2, 18), W2 (10, 0.5, 9) -> weighted loss: 57.0, correct: 43
    s1 = [
        _make_contribution(0, 20, 0.8, 16, step_id=1),
        _make_contribution(1, 30, 1.2, 18, step_id=1),
        _make_contribution(2, 10, 0.5, 9, step_id=1),
    ]
    _accumulate_epoch_contributions(acc, s1)

    # Step 2: W0 (15, 0.4, 12), W1 (20, 0.6, 14), W2 (5, 0.4, 4) -> weighted loss: 20.0, correct: 30
    s2 = [
        _make_contribution(0, 15, 0.4, 12, step_id=2),
        _make_contribution(1, 20, 0.6, 14, step_id=2),
        _make_contribution(2, 5, 0.4, 4, step_id=2),
    ]
    _accumulate_epoch_contributions(acc, s2)

    payload = _compute_epoch_metrics_payload(acc, epoch_index=1)
    assert payload["epoch_index"] == 1
    assert payload["sample_count"] == 100
    assert payload["training_loss"] == pytest.approx(0.77)
    assert payload["training_accuracy"] == pytest.approx(73.0)


def test_metrics_missing_loss_yields_both_none():
    """If loss is missing from any worker contribution, BOTH metrics must be None."""
    acc = _new_accumulator()
    c1 = _make_contribution(0, 4, None, 1)
    c2 = _make_contribution(1, 7, 2.0, 5)
    c3 = _make_contribution(2, 5, 4.0, 2)

    _accumulate_epoch_contributions(acc, [c1, c2, c3])
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)

    assert payload["sample_count"] == 16
    assert payload["training_loss"] is None
    assert payload["training_accuracy"] is None


def test_metrics_missing_correct_count_yields_both_none():
    """If correct_count is missing from any worker contribution, BOTH metrics must be None."""
    acc = _new_accumulator()
    c1 = _make_contribution(0, 4, 1.0, 1)
    c2 = _make_contribution(1, 7, 2.0, None)
    c3 = _make_contribution(2, 5, 4.0, 2)

    _accumulate_epoch_contributions(acc, [c1, c2, c3])
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)

    assert payload["sample_count"] == 16
    assert payload["training_loss"] is None
    assert payload["training_accuracy"] is None


def test_metrics_invalid_loss_nan_yields_both_none():
    """If loss is NaN or infinite, Contribution rejects it, and duck-typed invalid input invalidates accumulator."""
    with pytest.raises(ValueError, match="loss must be finite"):
        _make_contribution(0, 4, float("nan"), 1)

    # Duck-typed object bypassing constructor
    class FakeContrib:
        sample_count = 4
        loss = float("nan")
        correct_count = 1

    acc = _new_accumulator()
    _accumulate_epoch_contributions(acc, [FakeContrib()])
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)
    assert payload["training_loss"] is None
    assert payload["training_accuracy"] is None


def test_metrics_invalid_correct_count_out_of_bounds_yields_both_none():
    """If correct_count > sample_count, Contribution rejects it, and duck-typed invalid input invalidates accumulator."""
    with pytest.raises(ValueError, match="correct_count must be an integer"):
        _make_contribution(0, 4, 1.0, 5)

    # Duck-typed object bypassing constructor
    class FakeContrib:
        sample_count = 4
        loss = 1.0
        correct_count = 5

    acc = _new_accumulator()
    _accumulate_epoch_contributions(acc, [FakeContrib()])
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)
    assert payload["training_loss"] is None
    assert payload["training_accuracy"] is None


def test_metrics_empty_or_zero_samples():
    acc = _new_accumulator()
    payload = _compute_epoch_metrics_payload(acc, epoch_index=0)
    assert set(payload.keys()) == {"epoch_index", "sample_count", "training_loss", "training_accuracy"}
    assert payload["sample_count"] == 0
    assert payload["training_loss"] is None
    assert payload["training_accuracy"] is None
