from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import (
    RuntimeGateway,
    RuntimeUnavailableError,
)


def _build_snapshot(
    *,
    instance_id: str,
    active_attempt_id: str | None = None,
    last_runtime_event_seq: int = 0,
) -> dict:
    return {
        "runtime_instance_id": instance_id,
        "active_job_id": "job-1" if active_attempt_id else None,
        "active_attempt_id": active_attempt_id,
        "attempt_state": "RUNNING" if active_attempt_id else None,
        "training_strategy": "strict_bsp" if active_attempt_id else None,
        "checkpoint_policy": "EVERY_STEP" if active_attempt_id else None,
        "epoch": 0 if active_attempt_id else None,
        "current_operation_id": 0 if active_attempt_id else None,
        "current_batch_ordinal": 0 if active_attempt_id else None,
        "model_version": 0 if active_attempt_id else None,
        "workers": [],
        "strategy_state": {},
        "checkpoint_state": None,
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": "build-1" if active_attempt_id else None,
        "dataset_manifest_hash": ("0" * 64) if active_attempt_id else None,
        "last_runtime_event_seq": last_runtime_event_seq,
        "management_event_gap_count": 0,
        "captured_at": datetime.now(UTC).isoformat(),
    }


def test_runtime_instance_change_clears_old_context_and_resets_cursor() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    # 1. Connected to initial instance runtime-1
    gateway.handle_hello_ack({"runtime_instance_id": "runtime-1"})
    assert gateway.runtime_instance_id == "runtime-1"

    # Seed attempt-1 with events up to seq 25
    cursor1 = gateway.get_cursor("attempt-1")
    cursor1.max_seen_seq = 25
    cursor1.highest_contiguous_seq = 25
    cursor1.authoritative_snapshot_seq = 20
    gateway._attempt_snapshots["attempt-1"] = {"state": "RUNNING", "epoch": 2}

    # Add a pending command waiter
    waiter: concurrent.futures.Future[dict] = concurrent.futures.Future()
    gateway._pending_results["cmd-old"] = waiter

    # 2. Runtime restarts with runtime-2, snapshot indicates attempt-1 at seq 0
    port.snapshot_to_return = _build_snapshot(
        instance_id="runtime-2",
        active_attempt_id="attempt-1",
        last_runtime_event_seq=0,
    )

    with (
        patch("pbl4.management_backend.db.transaction"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"state": "RUNNING", "runtime_metadata": {}},
        ),
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_hello_ack({"runtime_instance_id": "runtime-2"})

    assert gateway.runtime_instance_id == "runtime-2"

    # Pending command waiter must be aborted with RuntimeUnavailableError
    assert waiter.done() is True
    with pytest.raises(RuntimeUnavailableError):
        waiter.result()
    assert len(gateway._pending_results) == 0

    # Cursor for attempt-1 must be cleanly reset to snapshot seq 0 (not 25)
    new_cursor = gateway.get_cursor("attempt-1")
    assert new_cursor.authoritative_snapshot_seq == 0
    assert new_cursor.highest_contiguous_seq == 0
    assert new_cursor.max_seen_seq == 0


def test_runtime_instance_change_with_idle_snapshot() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    # Initial session
    gateway.handle_hello_ack({"runtime_instance_id": "runtime-1"})
    cursor1 = gateway.get_cursor("attempt-1")
    cursor1.max_seen_seq = 25
    gateway._attempt_snapshots["attempt-1"] = {"state": "RUNNING"}

    # Restart with runtime-2 without active attempt
    port.snapshot_to_return = _build_snapshot(
        instance_id="runtime-2",
        active_attempt_id=None,
    )

    gateway.handle_hello_ack({"runtime_instance_id": "runtime-2"})

    assert gateway.runtime_instance_id == "runtime-2"
    assert len(gateway._attempt_snapshots) == 0
    assert len(gateway._attempt_cursors) == 0
    assert gateway.get_snapshot()["active_attempt_id"] is None


def test_runtime_instance_unchanged_preserves_context_on_reconnect() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    # Initial connection
    gateway.handle_hello_ack({"runtime_instance_id": "runtime-1"})
    cursor1 = gateway.get_cursor("attempt-1")
    cursor1.max_seen_seq = 15
    cursor1.highest_contiguous_seq = 15
    cursor1.authoritative_snapshot_seq = 10
    gateway._attempt_snapshots["attempt-1"] = {"state": "RUNNING", "epoch": 1}

    # Simulate network disconnect
    gateway.on_disconnect()
    assert gateway.get_cursor("attempt-1").stale is True

    # Reconnect to the SAME instance runtime-1
    port.snapshot_to_return = _build_snapshot(
        instance_id="runtime-1",
        active_attempt_id="attempt-1",
        last_runtime_event_seq=15,
    )

    with (
        patch("pbl4.management_backend.db.transaction"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"state": "RUNNING", "runtime_metadata": {}},
        ),
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_hello_ack({"runtime_instance_id": "runtime-1"})

    # Context and cursor are preserved
    assert "attempt-1" in gateway._attempt_snapshots
    cursor = gateway.get_cursor("attempt-1")
    assert cursor.stale is False
    assert cursor.max_seen_seq == 15


def test_runtime_disconnect_aborts_active_attempt_and_cleans_allocations() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    active_attempt = {
        "attempt_id": "attempt-active-1",
        "job_id": "job-1",
        "state": "RUNNING",
    }

    with (
        patch("pbl4.management_backend.db.transaction"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_active_attempt",
            return_value=active_attempt,
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state"
        ) as mock_update_state,
        patch(
            "pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt"
        ) as mock_cleanup,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.on_disconnect()

        mock_update_state.assert_called_once()
        args, kwargs = mock_update_state.call_args
        assert args[1] == "attempt-active-1"
        assert kwargs["new_state"] == "ABORTED"
        assert kwargs["failure_code"] == "RUNTIME_DISCONNECTED"

        mock_cleanup.assert_called_once()
        c_args, _ = mock_cleanup.call_args
        assert c_args[1] == "attempt-active-1"

        mock_broadcast.assert_called_once()
        b_args, _ = mock_broadcast.call_args
        assert b_args[0] == "attempt-active-1"
        assert b_args[1]["payload"]["state"] == "ABORTED"
        assert b_args[1]["payload"]["failure_code"] == "RUNTIME_DISCONNECTED"


def test_runtime_instance_change_aborts_active_attempt() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    gateway.handle_hello_ack({"runtime_instance_id": "runtime-1"})

    active_attempt = {
        "attempt_id": "attempt-active-1",
        "job_id": "job-1",
        "state": "RUNNING",
    }

    port.snapshot_to_return = _build_snapshot(
        instance_id="runtime-2",
        active_attempt_id=None,
    )

    with (
        patch("pbl4.management_backend.db.transaction"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_active_attempt",
            return_value=active_attempt,
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state"
        ) as mock_update_state,
        patch(
            "pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt"
        ) as mock_cleanup,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_hello_ack({"runtime_instance_id": "runtime-2"})

        assert mock_update_state.call_count >= 1
        assert mock_cleanup.call_count >= 1


def test_idle_snapshot_aborts_stale_active_attempt_in_db() -> None:
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    active_attempt = {
        "attempt_id": "attempt-stale-1",
        "job_id": "job-1",
        "state": "RUNNING",
    }

    idle_snapshot = _build_snapshot(
        instance_id="runtime-1",
        active_attempt_id=None,
    )

    with (
        patch("pbl4.management_backend.db.transaction"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_active_attempt",
            return_value=active_attempt,
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state"
        ) as mock_update_state,
        patch(
            "pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt"
        ) as mock_cleanup,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_state_snapshot(idle_snapshot)

        mock_update_state.assert_called_once()
        args, kwargs = mock_update_state.call_args
        assert args[1] == "attempt-stale-1"
        assert kwargs["new_state"] == "ABORTED"
        assert kwargs["failure_code"] == "RUNTIME_INSTANCE_IDLE"

        mock_cleanup.assert_called_once()


def test_abort_attempt_force_aborts_when_runtime_returns_attempt_not_active() -> None:
    from pbl4.management_backend.services import attempt_service

    gw = attempt_service.get_gateway()
    db_mock = MagicMock()

    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"attempt_id": "att_stale_1", "job_id": "job_1", "state": "RUNNING"},
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.create_command",
            return_value={
                "command_id": "cmd_abort_1",
                "state": "PENDING",
                "command_type": "ABORT_ATTEMPT",
                "target_type": "ATTEMPT",
                "request": {"command_id": "cmd_abort_1", "attempt_id": "att_stale_1"},
            },
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.get_command",
            return_value={
                "command_id": "cmd_abort_1",
                "state": "SUCCEEDED",
                "command_state": "SUCCEEDED",
                "command_type": "ABORT_ATTEMPT",
                "target_type": "ATTEMPT",
            },
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.update_command_state",
        ) as mock_cmd_update,
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state",
        ) as mock_attempt_update,
        patch(
            "pbl4.management_backend.services.attempt_service.AllocationService.cleanup_allocations_for_attempt",
        ) as mock_cleanup,
        patch(
            "pbl4.management_backend.services.idempotency.acquire_or_get_record",
            return_value=(None, "NEW"),
        ),
        patch(
            "pbl4.management_backend.services.idempotency.complete_record",
        ) as mock_complete_record,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
        patch.object(
            gw,
            "send_command_and_wait_result",
            return_value={
                "command_id": "cmd_abort_1",
                "state": "REJECTED",
                "result": {
                    "code": "ATTEMPT_NOT_ACTIVE",
                    "result_code": "ATTEMPT_NOT_ACTIVE",
                    "message": "Attempt is not active on this Runtime.",
                },
            },
        ),
    ):
        res = attempt_service.execute_abort_attempt(
            db_mock,
            attempt_id="att_stale_1",
            reason="force clean",
            idempotency_key="key_abort_stale_1",
        )

        assert res["command_state"] == "SUCCEEDED"
        mock_attempt_update.assert_called_once()
        assert mock_attempt_update.call_args[0][1] == "att_stale_1"
        assert mock_attempt_update.call_args[1]["new_state"] == "ABORTED"
        assert (
            mock_attempt_update.call_args[1]["failure_code"]
            == "OPERATOR_ABORTED_STALE_ATTEMPT"
        )

        mock_cmd_update.assert_called_once()
        assert mock_cmd_update.call_args[1]["new_state"] == "SUCCEEDED"

        mock_cleanup.assert_called_once()
        mock_complete_record.assert_called_once()
        assert mock_complete_record.call_args[1]["response_status_code"] == 202
        mock_broadcast.assert_called_once()


def test_abort_attempt_force_aborts_when_runtime_unavailable() -> None:
    from pbl4.management_backend.services import attempt_service

    gw = attempt_service.get_gateway()
    db_mock = MagicMock()

    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={
                "attempt_id": "att_stale_2",
                "job_id": "job_1",
                "state": "WAITING_WORKERS",
            },
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.create_command",
            return_value={
                "command_id": "cmd_abort_2",
                "state": "PENDING",
                "command_type": "ABORT_ATTEMPT",
                "target_type": "ATTEMPT",
                "request": {"command_id": "cmd_abort_2", "attempt_id": "att_stale_2"},
            },
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.get_command",
            return_value={
                "command_id": "cmd_abort_2",
                "state": "SUCCEEDED",
                "command_state": "SUCCEEDED",
                "command_type": "ABORT_ATTEMPT",
                "target_type": "ATTEMPT",
            },
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.update_command_state",
        ) as mock_cmd_update,
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state",
        ) as mock_attempt_update,
        patch(
            "pbl4.management_backend.services.attempt_service.AllocationService.cleanup_allocations_for_attempt",
        ) as mock_cleanup,
        patch(
            "pbl4.management_backend.services.idempotency.acquire_or_get_record",
            return_value=(None, "NEW"),
        ),
        patch(
            "pbl4.management_backend.services.idempotency.complete_record",
        ) as mock_complete_record,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
        patch.object(
            gw,
            "send_command_and_wait_result",
            side_effect=RuntimeUnavailableError("Runtime disconnected"),
        ),
    ):
        res = attempt_service.execute_abort_attempt(
            db_mock,
            attempt_id="att_stale_2",
            reason="runtime dead",
            idempotency_key="key_abort_stale_2",
        )

        assert res["command_state"] == "SUCCEEDED"
        mock_attempt_update.assert_called_once()
        assert mock_attempt_update.call_args[0][1] == "att_stale_2"
        assert mock_attempt_update.call_args[1]["new_state"] == "ABORTED"
        assert (
            mock_attempt_update.call_args[1]["failure_code"]
            == "OPERATOR_ABORTED_DISCONNECTED_RUNTIME"
        )

        mock_cmd_update.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_complete_record.assert_called_once()
        assert mock_complete_record.call_args[1]["response_status_code"] == 202
        mock_broadcast.assert_called_once()

