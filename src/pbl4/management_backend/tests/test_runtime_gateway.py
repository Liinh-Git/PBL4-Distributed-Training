from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import (
    DatabaseUnavailableError,
    RuntimeGateway,
)
from pbl4.management_backend.services.event_ingest import RuntimeEventIngestResult
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import CommandResult, McpEnvelope


def test_runtime_event_cursors_are_scoped_per_attempt() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    with (
        patch(
            "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
            return_value=None,
        ),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.record_event_seq("attempt-a", 125, object())
        gateway.record_event_seq("attempt-b", 1, object())

    cursor_a = gateway.get_cursor("attempt-a")
    cursor_b = gateway.get_cursor("attempt-b")
    assert cursor_a.max_seen_seq == 125
    assert cursor_a.highest_contiguous_seq is None
    assert cursor_a.gap_fenced is True
    assert cursor_b.max_seen_seq == 1
    assert cursor_b.highest_contiguous_seq == 1
    assert cursor_b.gap_fenced is False


def test_malformed_command_result_does_not_resolve_waiter() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    waiter: concurrent.futures.Future[dict] = concurrent.futures.Future()
    gateway._pending_results["cmd-1"] = waiter

    gateway.handle_command_result({"command_id": "cmd-1", "result": {}})

    assert waiter.done() is False


def test_database_failure_cannot_resolve_command_success() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    waiter: concurrent.futures.Future[dict] = concurrent.futures.Future()
    gateway._pending_results["cmd-2"] = waiter

    with patch(
        "pbl4.management_backend.db.transaction",
        side_effect=RuntimeError("database unavailable"),
    ):
        gateway.handle_command_result(
            {
                "command_id": "cmd-2",
                "target_type": "ATTEMPT",
                "target_id": "attempt-2",
                "status": "ACCEPTED",
                "result_code": "COMMAND_ACCEPTED",
                "message": "Accepted",
            }
        )

    with pytest.raises(DatabaseUnavailableError):
        waiter.result()


def test_authoritative_snapshot_requires_runtime_snapshot_and_never_defaults_worker_state() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    assert gateway.get_authoritative_snapshot("attempt-a") is None

    @contextmanager
    def transaction():
        yield object()

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"state": "RUNNING", "runtime_metadata": {}},
        ),
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.update_snapshot_projection"
        ) as update_session,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_state_snapshot(
            {
                "runtime_instance_id": "runtime-1",
                "active_job_id": "job-a",
                "active_attempt_id": "attempt-a",
                "attempt_state": "RUNNING",
                "training_strategy": "strict_bsp",
                "checkpoint_policy": "EVERY_STEP",
                "epoch": 0,
                "current_operation_id": 9,
                "current_batch_ordinal": 9,
                "model_version": 9,
                "workers": [],
                "strategy_state": {},
                "checkpoint_state": None,
                "latest_checkpoint_id": None,
                "recovery_cursor": {},
                "dataset_build_id": "build-a",
                "dataset_manifest_hash": "a" * 64,
                "last_runtime_event_seq": 9,
                "management_event_gap_count": 0,
                "captured_at": datetime.now(UTC).isoformat(),
            }
        )

    snapshot = gateway.get_authoritative_snapshot("attempt-a")
    assert snapshot is not None
    assert snapshot["authoritative_snapshot_seq"] == 9
    update_session.assert_not_called()


def test_commit_failure_does_not_advance_cursor_or_broadcast() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    cursor = gateway.get_cursor("attempt-commit-fail")
    cursor.highest_contiguous_seq = 4
    cursor.max_seen_seq = 4

    @contextmanager
    def failing_transaction():
        yield object()
        raise RuntimeError("commit failed")

    with (
        patch("pbl4.management_backend.db.transaction", failing_transaction),
        patch(
            "pbl4.management_backend.services.event_ingest.ingest_runtime_event",
            return_value=RuntimeEventIngestResult({"event_id": "evt-5"}, inserted=True),
        ),
        patch("pbl4.management_backend.services.event_ingest.broadcast_runtime_event") as broadcast,
        patch.object(gateway, "record_event_seq") as record_event_seq,
    ):
        gateway.handle_runtime_event(
            {
                "attempt_id": "attempt-commit-fail",
                "runtime_event_seq": 5,
                "event_type": "STEP_COMMITTED",
                "job_id": "job-1",
                "event_schema_version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "source_component": "Runtime",
                "severity": "INFO",
                "details": {"step": 5},
            }
        )

    assert cursor.highest_contiguous_seq == 4
    assert cursor.max_seen_seq == 4
    record_event_seq.assert_not_called()
    broadcast.assert_not_called()


def test_real_command_result_codec_maps_status_to_durable_state() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    payload = CommandResult.from_dict(
        {
            "command_id": "cmd-golden",
            "target_type": "ATTEMPT",
            "target_id": "attempt-golden",
            "status": "SUCCEEDED",
            "result_code": "NO_OP",
            "message": "Already complete.",
        }
    )
    envelope = McpEnvelope(
        message_type="COMMAND_RESULT",
        message_id="msg-result",
        correlation_id="msg-request",
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-1",
        payload=payload,
    )
    decoded = McpCodec.decode(McpCodec.encode(envelope))
    waiter: concurrent.futures.Future[dict] = concurrent.futures.Future()
    gateway._pending_results["cmd-golden"] = waiter
    with (
        patch("pbl4.management_backend.db.transaction") as transaction,
        patch(
            "pbl4.management_backend.repositories.command_repository.update_command_state",
            return_value={"command_id": "cmd-golden"},
        ) as update,
    ):
        transaction.return_value.__enter__.return_value = object()
        gateway.handle_command_result(decoded.payload.to_dict())
    assert waiter.result()["state"] == "SUCCEEDED"
    update.assert_called_once()
    assert update.call_args.kwargs["new_state"] == "SUCCEEDED"
    assert update.call_args.kwargs["result"]["result_code"] == "NO_OP"


def test_state_snapshot_rejects_legacy_sequence_aliases() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    gateway.handle_state_snapshot({"active_attempt_id": "attempt-a", "runtime_event_seq": 1})
    assert gateway.get_authoritative_snapshot("attempt-a") is None


def test_checkpoint_started_projects_synchronization_boundary() -> None:
    occurred_at = "2026-09-11T01:02:03+00:00"
    details = {
        "checkpoint_id": "checkpoint-1",
        "source_operation_id": 2,
        "source_step_id": 2,
        "model_version": 3,
        "recovery_cursor": {"epoch": 0, "next_batch_ordinal": 3},
        "contract_hash": "a" * 64,
        "dataset_build_id": "build-1",
        "dataset_manifest_hash": "b" * 64,
        "parameter_manifest_hash": "c" * 64,
        "checkpoint_policy": "after_each_model_update_blocking",
        "checkpoint_policy_version": 1,
        "created_at": occurred_at,
    }
    with (
        patch("pbl4.management_backend.repositories.checkpoint_repository.create_checkpoint"),
        patch("pbl4.management_backend.repositories.step_repository.update_step") as update_step,
    ):
        RuntimeGateway._project_runtime_event(
            object(),
            {
                "attempt_id": "attempt-1",
                "event_type": "checkpoint.started",
                "occurred_at": occurred_at,
                "details": details,
            },
        )
    assert update_step.call_args.kwargs["synchronization_completed_at"] == datetime.fromisoformat(
        occurred_at
    )


def test_attempt_state_changed_event_cleans_up_allocations() -> None:
    occurred_at = "2026-09-11T01:02:03+00:00"
    payload = {
        "attempt_id": "attempt-1",
        "event_type": "attempt.state_changed",
        "occurred_at": occurred_at,
        "details": {"state": "ABORTED", "failure_code": "USER_ABORTED", "failure_message": "User requested abort"},
    }
    with (
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state") as mock_update,
        patch("pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt") as mock_cleanup,
    ):
        RuntimeGateway._project_runtime_event(object(), payload)

        mock_update.assert_called_once()
        assert mock_update.call_args[0][1] == "attempt-1"
        assert mock_update.call_args[0][2] == "ABORTED"

        mock_cleanup.assert_called_once()
        assert mock_cleanup.call_args[0][1] == "attempt-1"
        assert mock_cleanup.call_args[1]["failure_code"] == "USER_ABORTED"



def test_snapshot_creation_uses_runtime_owned_session_metadata() -> None:
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    connected_at = "2026-09-11T01:00:00+00:00"
    heartbeat_at = "2026-09-11T01:01:00+00:00"

    @contextmanager
    def transaction():
        yield object()

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"state": "RUNNING", "runtime_metadata": {}},
        ),
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.update_snapshot_projection",
            return_value=None,
        ),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.upsert_session"
        ) as upsert,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_state_snapshot(
            {
                "runtime_instance_id": "runtime-1",
                "active_job_id": "job-1",
                "active_attempt_id": "attempt-1",
                "attempt_state": "RUNNING",
                "training_strategy": "strict_bsp",
                "checkpoint_policy": "after_each_model_update_blocking",
                "epoch": 0,
                "current_operation_id": None,
                "current_batch_ordinal": 0,
                "model_version": 0,
                "workers": [
                    {
                        "worker_id": 0,
                        "session_id": "7",
                        "node_label": "node-0",
                        "state": "READY",
                        "protocol_version": 1,
                        "connected_at": connected_at,
                        "last_heartbeat_at": heartbeat_at,
                        "shard_id": 0,
                        "local_model_version": 0,
                    }
                ],
                "strategy_state": {"type": "strict_bsp"},
                "checkpoint_state": None,
                "latest_checkpoint_id": None,
                "recovery_cursor": {"epoch": 0, "next_batch_ordinal": 0},
                "dataset_build_id": "build-1",
                "dataset_manifest_hash": "d" * 64,
                "last_runtime_event_seq": 1,
                "management_event_gap_count": 0,
                "captured_at": heartbeat_at,
            }
        )
    assert upsert.call_args.kwargs["protocol_version"] == 1
    assert upsert.call_args.kwargs["connected_at"] == datetime.fromisoformat(connected_at)


def _valid_snapshot_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "runtime_instance_id": "runtime-1",
        "active_job_id": "job-1",
        "active_attempt_id": "attempt-1",
        "attempt_state": "RUNNING",
        "training_strategy": "strict_bsp",
        "checkpoint_policy": "after_each_model_update_blocking",
        "epoch": 0,
        "current_operation_id": None,
        "current_batch_ordinal": 0,
        "model_version": 0,
        "workers": [],
        "strategy_state": {"type": "strict_bsp"},
        "checkpoint_state": None,
        "latest_checkpoint_id": None,
        "recovery_cursor": {"epoch": 0, "next_batch_ordinal": 0},
        "dataset_build_id": "build-1",
        "dataset_manifest_hash": "d" * 64,
        "last_runtime_event_seq": 10,
        "management_event_gap_count": 0,
        "captured_at": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


def test_state_snapshot_unknown_attempt_does_not_update_cache_or_broadcast() -> None:
    """Verify unknown attempt in STATE_SNAPSHOT rejects reconciliation and never broadcasts."""
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    transaction = MagicMock()

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value=None,
        ),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.handle_state_snapshot(_valid_snapshot_dict(active_attempt_id="unknown-attempt-999"))

    # Invariants:
    # 1. No snapshot cache entry created for unknown attempt
    assert gateway.get_authoritative_snapshot("unknown-attempt-999") is None
    # 2. Cursor not advanced as authoritative
    cursor = gateway.get_cursor("unknown-attempt-999")
    assert cursor.authoritative_snapshot_seq is None
    # 3. Never broadcast to websocket
    mock_broadcast.assert_not_called()


def test_state_snapshot_db_outage_preserves_live_telemetry_and_broadcasts() -> None:
    """Verify DB operational failure during STATE_SNAPSHOT maintains live telemetry."""
    import psycopg

    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    transaction = MagicMock()
    transaction.side_effect = psycopg.OperationalError("Database down")

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.handle_state_snapshot(
            _valid_snapshot_dict(
                active_attempt_id="attempt-db-fail",
                last_runtime_event_seq=10,
            )
        )

    # Invariants for degraded mode (DB down != training down):
    # 1. Authoritative snapshot seq recorded in memory
    snap = gateway.get_authoritative_snapshot("attempt-db-fail")
    assert snap is not None
    assert snap["attempt_id"] == "attempt-db-fail"
    assert snap["authoritative_snapshot_seq"] == 10
    assert snap["stale"] is False

    # 2. Live cursor advances
    cursor = gateway.get_cursor("attempt-db-fail")
    assert cursor.authoritative_snapshot_seq == 10
    assert cursor.highest_contiguous_seq == 10
    assert cursor.max_seen_seq == 10
    assert cursor.stale is False

    # 3. Broadcast to websocket succeeded
    mock_broadcast.assert_called_once()
    args, _ = mock_broadcast.call_args
    assert args[0] == "attempt-db-fail"
    assert args[1]["kind"] == "SNAPSHOT"
    assert args[1]["runtime_event_seq"] == 10


def test_state_snapshot_pool_timeout_preserves_live_telemetry() -> None:
    """Verify that connection pool timeout maintains degraded live telemetry."""
    import psycopg_pool

    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    transaction = MagicMock()
    transaction.side_effect = psycopg_pool.PoolTimeout("Pool exhausted")

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.handle_state_snapshot(
            _valid_snapshot_dict(
                active_attempt_id="attempt-pool-timeout",
                epoch=1,
                current_batch_ordinal=5,
                model_version=1,
                last_runtime_event_seq=25,
            )
        )

    snap = gateway.get_authoritative_snapshot("attempt-pool-timeout")
    assert snap is not None
    assert snap["authoritative_snapshot_seq"] == 25
    mock_broadcast.assert_called_once()


def test_state_snapshot_runtime_error_treated_as_programming_error() -> None:
    """Verify that generic RuntimeError is NOT treated as DB outage and rejects snapshot."""
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    transaction = MagicMock()
    transaction.side_effect = RuntimeError("Some internal bug")

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.handle_state_snapshot(_valid_snapshot_dict(active_attempt_id="attempt-runtime-err"))

    assert gateway.get_authoritative_snapshot("attempt-runtime-err") is None
    mock_broadcast.assert_not_called()


def test_state_snapshot_programming_error_does_not_broadcast() -> None:
    """Verify that programming/data-integrity error during STATE_SNAPSHOT aborts."""
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True))
    transaction = MagicMock()

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"state": "RUNNING", "runtime_metadata": {}},
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state",
            side_effect=TypeError("Unexpected type in update"),
        ),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        gateway.handle_state_snapshot(_valid_snapshot_dict(active_attempt_id="attempt-bug"))

    # Invariants:
    assert gateway.get_authoritative_snapshot("attempt-bug") is None
    mock_broadcast.assert_not_called()
