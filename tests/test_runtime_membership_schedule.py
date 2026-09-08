"""Session ownership, accepted storage and deterministic physical scheduling."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.synchronization.context import BatchAssignment
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry


def test_session_lifecycle_and_fixed_membership():
    registry = WorkerRegistry("attempt", 2)
    registry.register(10, 0, 0)
    registry.register(11, 0, 1)
    with pytest.raises(ValueError):
        registry.register(12, 0, 0)
    with pytest.raises(ValueError):
        registry.freeze_membership()
    for w, session in ((0, 10), (1, 11)):
        for state in (
            SessionState.REGISTERING,
            SessionState.PROVISIONING,
            SessionState.SHARD_READY,
            SessionState.MODEL_SYNCING,
            SessionState.READY,
        ):
            registry.transition(w, session, state, 1)
    assert [m.session_id for m in registry.freeze_membership()] == [10, 11]
    registry.heartbeat(0, 10, 5)
    assert registry.snapshot()[0].last_heartbeat_at == 5
    registry.transition(0, 10, SessionState.DISCONNECTED, 6)
    with pytest.raises(ValueError):
        registry.register(12, 7, 0)
    with pytest.raises(ValueError):
        registry.heartbeat(0, 10, 7)


def test_registration_race_assigns_one_rank_once():
    registry = WorkerRegistry("attempt", 1)

    def connect(session):
        try:
            return registry.register(session, 0, 0)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(connect, [1, 2]))
    assert sum(s is not None for s in sessions) == 1
    assert len(registry.snapshot()) == 1


def test_pre_run_reconnect_requires_new_session():
    registry = WorkerRegistry("attempt", 1)
    registry.register(1, 0)
    registry.transition(0, 1, SessionState.DISCONNECTED, 1)
    with pytest.raises(ValueError):
        registry.register(1, 2)
    registry.register(2, 2)
    with pytest.raises(ValueError):
        registry.heartbeat(0, 1, 3)
    with pytest.raises(ValueError):
        registry.transition(0, 2, SessionState.READY, 3)


def test_epoch_permutation_resume_no_repeat_or_skip():
    batches = tuple(
        BatchAssignment(w, w, batch_id, batch_id, w + 1) for w in range(3) for batch_id in range(7)
    )
    scheduler = BatchScheduler(batches, -100, 3)
    cursor = RecoveryCursor(0, 0)
    seen = []
    for epoch in range(3):
        epoch_ids = []
        for ordinal in range(7):
            assert cursor == RecoveryCursor(epoch, ordinal)
            assigned = scheduler.assignments(cursor)
            assert len({a.batch_id for a in assigned}) == 1
            assert [a.sample_count for a in assigned] == [1, 2, 3]
            epoch_ids.append(assigned[0].batch_id)
            # A new scheduler recreates the assignment exactly from the saved cursor.
            assert BatchScheduler(batches, -100, 3).assignments(cursor) == assigned
            seen.append(assigned)
            cursor = scheduler.next_cursor(cursor)
        assert sorted(epoch_ids) == list(range(7))
    assert cursor == RecoveryCursor(3, 0)
    with pytest.raises(StopIteration):
        scheduler.assignments(cursor)
    assert seen[:7] != seen[7:14]


def test_invalid_physical_batch_selection():
    with pytest.raises(ValueError):
        BatchScheduler((), 1, 1)
    with pytest.raises(ValueError):
        BatchScheduler((BatchAssignment(0, 0, 0, 0, 1),) * 2, 1, 1)
    with pytest.raises(ValueError):
        BatchScheduler((BatchAssignment(0, 0, 0, 0, 1), BatchAssignment(1, 1, 1, 0, 1)), 1, 1)
