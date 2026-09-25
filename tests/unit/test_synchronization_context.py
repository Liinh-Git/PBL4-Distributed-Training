"""Unit tests for WorkUnitRef and evolved BatchAssignment."""

from dataclasses import FrozenInstanceError, replace

import pytest

from pbl4.runtime.synchronization.context import BatchAssignment, WorkUnitRef


def test_work_unit_ref_immutability_and_validation():
    unit = WorkUnitRef(shard_id=1, batch_id=2, sample_count=32)
    assert unit.shard_id == 1
    assert unit.batch_id == 2
    assert unit.sample_count == 32

    # Frozen
    with pytest.raises(FrozenInstanceError):
        unit.shard_id = 10  # type: ignore

    # Validation
    with pytest.raises(ValueError, match="shard_id and batch_id must be non-negative"):
        WorkUnitRef(-1, 0, 10)

    with pytest.raises(ValueError, match="shard_id and batch_id must be non-negative"):
        WorkUnitRef(0, -1, 10)

    with pytest.raises(ValueError, match="sample_count must be a positive integer"):
        WorkUnitRef(0, 0, 0)

    with pytest.raises(ValueError, match="sample_count must be a positive integer"):
        WorkUnitRef(0, 0, -5)

    with pytest.raises(ValueError):
        WorkUnitRef(True, 0, 10)  # type: ignore

    with pytest.raises(ValueError):
        WorkUnitRef(0, False, 10)  # type: ignore


def test_batch_assignment_multi_unit_construction():
    u1 = WorkUnitRef(0, 1, 16)
    u2 = WorkUnitRef(0, 2, 16)
    u3 = WorkUnitRef(1, 1, 32)

    # Keyword instantiation
    assignment = BatchAssignment(
        worker_id=0,
        batch_ordinal=5,
        work_units=(u1, u2, u3),
        sample_count=64,
    )
    assert assignment.worker_id == 0
    assert assignment.batch_ordinal == 5
    assert len(assignment.work_units) == 3
    assert assignment.sample_count == 64
    assert assignment.shard_id == 0
    assert assignment.batch_id == 1

    # Inferred sample_count when omitted
    assignment_inferred = BatchAssignment(
        worker_id=0,
        batch_ordinal=5,
        work_units=(u1, u2, u3),
    )
    assert assignment_inferred.sample_count == 64

    # 4 positional args: (worker_id, batch_ordinal, work_units, sample_count)
    assignment_pos4 = BatchAssignment(0, 5, (u1, u2, u3), 64)
    assert assignment_pos4 == assignment

    # 3 positional args: (worker_id, batch_ordinal, work_units)
    assignment_pos3 = BatchAssignment(0, 5, (u1, u2, u3))
    assert assignment_pos3 == assignment


def test_batch_assignment_legacy_compatibility():
    # Legacy 5 positional args: (worker_id, shard_id, batch_id, batch_ordinal, sample_count)
    legacy = BatchAssignment(0, 1, 2, 3, 16)
    assert legacy.worker_id == 0
    assert legacy.shard_id == 1
    assert legacy.batch_id == 2
    assert legacy.batch_ordinal == 3
    assert legacy.sample_count == 16
    assert len(legacy.work_units) == 1
    assert legacy.work_units[0] == WorkUnitRef(1, 2, 16)

    # Legacy keyword args
    legacy_kw = BatchAssignment(
        worker_id=0,
        shard_id=1,
        batch_id=2,
        batch_ordinal=3,
        sample_count=16,
    )
    assert legacy_kw == legacy


def test_batch_assignment_immutability():
    u = WorkUnitRef(0, 0, 16)
    assignment = BatchAssignment(worker_id=0, batch_ordinal=0, work_units=(u,))
    with pytest.raises(FrozenInstanceError):
        assignment.batch_ordinal = 1  # type: ignore

    # Dataclasses replace support
    replaced = replace(assignment, batch_ordinal=1)
    assert replaced.batch_ordinal == 1
    assert replaced.work_units == (u,)
    assert replaced.sample_count == 16


def test_batch_assignment_validation_failures():
    u1 = WorkUnitRef(0, 1, 16)
    u2 = WorkUnitRef(0, 1, 16)  # duplicate (shard_id=0, batch_id=1)

    # Empty work_units
    with pytest.raises(ValueError, match="work_units cannot be empty"):
        BatchAssignment(worker_id=0, batch_ordinal=0, work_units=())

    # Duplicate work units in same assignment
    with pytest.raises(ValueError, match="Duplicate"):
        BatchAssignment(worker_id=0, batch_ordinal=0, work_units=(u1, u2))

    # sample_count mismatch
    with pytest.raises(ValueError, match=r"sample_count.*must equal sum"):
        BatchAssignment(worker_id=0, batch_ordinal=0, work_units=(u1,), sample_count=32)

    # Invalid worker_id / batch_ordinal
    with pytest.raises(ValueError, match="Invalid assignment identity"):
        BatchAssignment(worker_id=-1, batch_ordinal=0, work_units=(u1,))

    with pytest.raises(ValueError, match="Invalid assignment identity"):
        BatchAssignment(worker_id=0, batch_ordinal=-1, work_units=(u1,))

    with pytest.raises(ValueError, match="Invalid assignment identity"):
        BatchAssignment(worker_id=True, batch_ordinal=0, work_units=(u1,))  # type: ignore
