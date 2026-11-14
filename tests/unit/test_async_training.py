"""Async scheduling/recovery oracles independent of socket and framework timing."""

from dataclasses import replace

import pytest

from pbl4.common.async_training import resolve_async_training
from pbl4.common.hashing import canonical_json_bytes
from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.checkpoint_serializer import TrainingCheckpointSerializer
from pbl4.runtime.synchronization.async_sgd import AsyncSGD
from pbl4.runtime.workload_pool import GlobalWorkUnitPool
from tests.test_coordinator import contribution, running


def pool(k=1, epochs=3):
    return GlobalWorkUnitPool([WorkUnitRef(0, i, i + 1) for i in range(3)], 42, epochs, k)


def test_epoch_overlap_reclaim_restore_and_tail():
    p = pool(k=2)
    a = p.assign(0, 1, 0, 0)
    b = p.assign(1, 2, 0, 0)
    assert len(a.indices) == 2 and len(b.indices) == 1
    p.complete(b, True)
    c = p.assign(1, 2, 1, 1)
    assert c.epoch == 1 and p.frontier == 0
    p.complete(c, False)
    assert not p.reclaim(0, 999)
    assert p.reclaim(0, 1)
    assert not p.reclaim(0, 1)
    restored = pool(k=2)
    restored.restore(p.snapshot())
    assert restored.snapshot() == p.snapshot()
    seen = set()
    while not restored.finished:
        assignment = restored.assign(0, 9, 4, 0)
        assert not seen.intersection(assignment.indices)
        seen.update(assignment.indices)
        restored.complete(assignment, True)
    assert restored.frontier == 3
    assert sum(restored.counts[k] for k in ("applied_units", "dropped_units")) == 9


def test_operation_ids_stay_unique_across_idle_assignments_and_reclaim():
    p = pool()
    idle = p.new_operation_id()
    assignment = p.assign(0, 1, 0, 0)
    next_idle = p.new_operation_id()
    assert p.reclaim(0, 1)
    replacement = p.assign(0, 2, 0, 1)
    assert idle < assignment.operation_id < next_idle < replacement.operation_id
    assert replacement.indices == assignment.indices
    assert p.issued == 1


@pytest.mark.parametrize(
    "name,low,high",
    [
        ("units_per_contribution", 1, 4096),
        ("staleness_threshold", 0, 1_000_000),
        ("reconnect_grace_seconds", 1, 3600),
        ("assignment_timeout_seconds", 1, 86400),
    ],
)
def test_each_setting_uses_its_own_bounds(name, low, high):
    assert resolve_async_training()["reconnect_grace_seconds"] == 60
    for valid in (low, high):
        assert resolve_async_training({name: valid})[name] == valid
    for invalid in (low - 1, high + 1, True, 1.5):
        with pytest.raises(ValueError, match=name):
            resolve_async_training({name: invalid})


@pytest.mark.parametrize(
    "field,value",
    [("issued", True), ("remaining", [0, 0]), ("applied_units", 50), ("dropped_samples", 99)],
)
def test_restore_rejects_corrupt_progress(field, value):
    p = pool()
    p.assign(0, 1, 0, 0)
    state = p.snapshot()
    state[field] = value
    with pytest.raises(ValueError):
        pool().restore(state)


@pytest.mark.parametrize(
    "value",
    [
        {"units_per_contribution": True},
        {"staleness_threshold": -1},
        {"reconnect_grace_seconds": 0},
        {"unknown": 1},
        [],
    ],
)
def test_settings_are_strict(value):
    with pytest.raises(ValueError):
        resolve_async_training(value)


def test_restore_rejects_samples_assigned_to_an_empty_outcome():
    p = pool()
    p.complete(p.assign(0, 1, 0, 0), True)
    state = p.snapshot()
    state["applied_samples"], state["dropped_samples"] = 0, state["applied_samples"]
    with pytest.raises(ValueError, match="outcome sample"):
        pool().restore(state)


def test_policy_binds_base_version_and_staleness_threshold(tmp_path):
    coordinator, _ = running(tmp_path)
    op = coordinator.open_step()
    gradient = contribution(op, 0)
    p = pool()
    assignment = p.assign(0, 1, gradient.model_version, 0)
    gradient = replace(
        gradient,
        operation_id=assignment.operation_id,
        batch_ordinal=assignment.operation_id,
        shard_id=assignment.work_units[0].shard_id,
        batch_id=assignment.work_units[0].batch_id,
        sample_count=sum(u.sample_count for u in assignment.work_units),
    )
    policy = AsyncSGD("attempt", 0.5, 2)
    assert policy.admit(gradient, assignment, 7).learning_rate == 0.5
    assert policy.admit(gradient, assignment, 9).learning_rate == 0.25
    assert policy.admit(gradient, assignment, 10).learning_rate is None
    with pytest.raises(ValueError):
        policy.admit(replace(gradient, model_version=9), assignment, 9)
    with pytest.raises(ValueError):
        policy.admit(gradient, assignment, 6)


def test_checkpoint_v1_compatibility_and_v2_progress_roundtrip(tmp_path):
    from tests.test_production_composition import _snapshot

    serializer = TrainingCheckpointSerializer()
    original = _snapshot()
    payload, metadata = serializer.serialize(original)
    assert serializer.deserialize(payload, metadata) == original
    asynchronous = replace(
        original,
        training_strategy="async_sgd",
        checkpoint_schema_version=2,
        async_progress=canonical_json_bytes(pool().snapshot()),
    )
    payload, metadata = serializer.serialize(asynchronous)
    assert serializer.deserialize(payload, metadata) == asynchronous
