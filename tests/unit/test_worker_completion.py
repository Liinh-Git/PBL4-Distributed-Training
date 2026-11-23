"""Completion notification parks the Worker; process lifetime belongs to Agent."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from pbl4.protocol.messages import Stop
from pbl4.worker.config import WorkerConfig
from pbl4.worker.process import WorkerProcess


@pytest.fixture
def worker():
    config = WorkerConfig(
        attempt_id="attempt", allocation_id="allocation", node_id="node", worker_join_token="token"
    )
    with (
        patch("pbl4.worker.process.build_model"),
        patch("pbl4.worker.process.PyTorchAdapter"),
        patch.object(WorkerProcess, "_new_client"),
    ):
        value = WorkerProcess(
            config, initialization_seed=42, model_id="small_cnn", connect_timeout_seconds=0.01
        )
    value._client.training_strategy = "async_sgd"
    return value


def complete(worker):
    worker._on_message(
        Stop.from_dict(
            {
                "whether_reconnect_allowed": False,
                "attempt_state": "COMPLETED",
                "reason_code": "ATTEMPT_COMPLETED",
                "reason": "done",
            }
        ),
        0,
    )


def test_completed_worker_waits_beyond_reconnect_budget(worker):
    notified = threading.Event()

    def connect():
        complete(worker)
        notified.set()
        return MagicMock(training_strategy="async_sgd")

    worker._client.connect.side_effect = connect
    task = threading.Thread(target=worker.run)
    task.start()
    try:
        assert notified.wait(2)
        task.join(0.2)
        assert task.is_alive()
        assert not worker._stop.is_set()
        assert not worker._failed.is_set()
        worker._client.connect.assert_called_once()
        worker._client.send_heartbeat.assert_not_called()
        worker._on_disconnect()
        assert not worker._connection_lost.is_set()
    finally:
        worker._stop.set()  # Test teardown only; production Agent terminates the OS process.
        task.join(3)
    assert not task.is_alive()


def test_completion_discards_queued_work_and_late_errors(worker):
    complete(worker)
    callback = MagicMock()
    worker._enqueue(worker._client, callback)
    assert worker._jobs.empty()
    worker._on_message(MagicMock(), 0)
    worker._compute(MagicMock(), 0)
    worker._client.send_gradient.assert_not_called()


@pytest.mark.parametrize("state", ["FAILED", "ABORTED"])
def test_failed_and_aborted_keep_existing_exit_behavior(worker, state):
    worker._on_message(
        Stop.from_dict(
            {
                "whether_reconnect_allowed": False,
                "attempt_state": state,
                "reason_code": "ATTEMPT_FAILED",
                "reason": "failed",
            }
        ),
        0,
    )
    assert worker._stop.is_set()
    assert worker._failed.is_set()
    assert not worker._completed.is_set()


def test_completion_during_compute_discards_result(worker):
    from types import SimpleNamespace

    from pbl4.common.work_unit import WorkUnitRef

    worker._client.session_id = 1
    worker._client.worker_id = 0
    worker._client.attempt_id = "attempt"
    worker._loop = MagicMock()
    worker._loop.compute.side_effect = lambda assignment: (complete(worker), MagicMock())[1]
    message = SimpleNamespace(
        attempt_id="attempt",
        step_id=1,
        model_version=0,
        batch_ordinal=0,
        work_units=(WorkUnitRef(0, 0, 2),),
        expected_sample_count=2,
        epoch=0,
    )
    worker._compute(message, 1)
    worker._loop.compute.assert_called_once()
    worker._client.send_gradient.assert_not_called()
    assert worker._completed.is_set()
    assert not worker._failed.is_set()
