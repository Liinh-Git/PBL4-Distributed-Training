from __future__ import annotations

import concurrent.futures
from datetime import UTC, datetime
from unittest.mock import patch

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
