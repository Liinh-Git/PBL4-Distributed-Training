from __future__ import annotations

import concurrent.futures
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import (
    DatabaseUnavailableError,
    RuntimeGateway,
)
from pbl4.management_backend.services.event_ingest import RuntimeEventIngestResult


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
        gateway.handle_command_result({"command_id": "cmd-2", "state": "ACCEPTED"})

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
            "pbl4.management_backend.repositories.worker_session_repository.upsert_session"
        ) as upsert_session,
        patch("pbl4.management_backend.websocket.hub.broadcast_sync"),
    ):
        gateway.handle_state_snapshot(
            {
                "attempt_id": "attempt-a",
                "runtime_event_seq": 9,
                "attempt_state": "RUNNING",
                "workers": [{"worker_id": 0}],
            }
        )

    snapshot = gateway.get_authoritative_snapshot("attempt-a")
    assert snapshot is not None
    assert snapshot["authoritative_snapshot_seq"] == 9
    upsert_session.assert_not_called()


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
                "payload": {"step": 5},
            }
        )

    assert cursor.highest_contiguous_seq == 4
    assert cursor.max_seen_seq == 4
    record_event_seq.assert_not_called()
    broadcast.assert_not_called()
