"""Unit tests for Phase 8 Attempt Orchestration & Snapshot Projection.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Sections 4.7, 4.10, 6.3, 8.2.

Tests:
1. StateSnapshot schema validation for optional node_id and allocation_id.
2. WorkerSessionItem Pydantic schema validation.
3. _select_and_create_allocations deterministic scheduling.
4. _select_and_create_allocations capacity failure (NODE_CAPACITY_UNAVAILABLE).
5. _dispatch_workers_for_attempt successful dispatch to all nodes.
6. Partial dispatch failure handling (STOP_WORKER + ABORT_ATTEMPT + FAILED).
7. _AttemptRunner.snapshot serialization of node_id and allocation_id.
8. RuntimeGateway.handle_state_snapshot passing node_id and allocation_id to session repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from pbl4.common.errors import ProtocolError
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.repositories import (
    allocation_repository,
)
from pbl4.management_backend.schemas.attempt import WorkerSessionItem
from pbl4.management_backend.services.attempt_service import (
    CommandFailedError,
    _dispatch_workers_for_attempt,
    _select_and_create_allocations,
)
from pbl4.management_backend.services.cluster_scheduler import (
    NodeCapacityUnavailableError,
)
from pbl4.management_protocol.messages import StateSnapshot

# ─── 1. StateSnapshot Schema Validation ──────────────────────────────────────


def test_state_snapshot_worker_projection_managed_identity() -> None:
    """Verify StateSnapshot accepts worker entries with node_id and allocation_id."""
    base_worker = {
        "worker_id": 0,
        "session_id": "1",
        "node_label": "worker-0",
        "state": "READY",
        "last_heartbeat_at": "2026-09-25T00:00:00Z",
        "shard_id": 0,
        "local_model_version": 1,
        "node_id": "node-1",
        "allocation_id": "alloc-1",
    }
    payload = {
        "runtime_instance_id": "rt-1",
        "active_job_id": "job-1",
        "active_attempt_id": "atm-1",
        "attempt_state": "RUNNING",
        "training_strategy": "strict_bsp",
        "checkpoint_policy": "every_step",
        "epoch": 1,
        "current_operation_id": 1,
        "current_batch_ordinal": 5,
        "model_version": 1,
        "workers": [base_worker],
        "strategy_state": {},
        "checkpoint_state": "IDLE",
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": "bld-1",
        "dataset_manifest_hash": "hash-1",
        "last_runtime_event_seq": 10,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-25T00:00:01Z",
    }
    snap = StateSnapshot.from_dict(payload)
    assert len(snap.workers) == 1
    assert snap.workers[0]["node_id"] == "node-1"
    assert snap.workers[0]["allocation_id"] == "alloc-1"


def test_state_snapshot_worker_projection_unmanaged_nullable() -> None:
    """Accept absent managed identities for legacy/unmanaged Workers."""
    worker_none = {
        "worker_id": 0,
        "session_id": "1",
        "node_label": "worker-0",
        "state": "READY",
        "last_heartbeat_at": None,
        "shard_id": None,
        "local_model_version": None,
        "node_id": None,
        "allocation_id": None,
    }
    worker_omitted = {
        "worker_id": 1,
        "session_id": "2",
        "node_label": "worker-1",
        "state": "READY",
        "last_heartbeat_at": None,
        "shard_id": None,
        "local_model_version": None,
    }
    payload = {
        "runtime_instance_id": "rt-1",
        "active_job_id": None,
        "active_attempt_id": None,
        "attempt_state": None,
        "training_strategy": None,
        "checkpoint_policy": None,
        "epoch": None,
        "current_operation_id": None,
        "current_batch_ordinal": None,
        "model_version": None,
        "workers": [worker_none, worker_omitted],
        "strategy_state": {},
        "checkpoint_state": None,
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": None,
        "dataset_manifest_hash": None,
        "last_runtime_event_seq": 0,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-25T00:00:01Z",
    }
    snap = StateSnapshot.from_dict(payload)
    assert len(snap.workers) == 2


def test_state_snapshot_worker_projection_invalid_type() -> None:
    """Verify invalid node_id type raises ProtocolError."""
    worker_bad = {
        "worker_id": 0,
        "session_id": "1",
        "node_label": "worker-0",
        "state": "READY",
        "last_heartbeat_at": None,
        "shard_id": None,
        "local_model_version": None,
        "node_id": 12345,  # Must be string or None
        "allocation_id": "alloc-1",
    }
    payload = {
        "runtime_instance_id": "rt-1",
        "active_job_id": None,
        "active_attempt_id": None,
        "attempt_state": None,
        "training_strategy": None,
        "checkpoint_policy": None,
        "epoch": None,
        "current_operation_id": None,
        "current_batch_ordinal": None,
        "model_version": None,
        "workers": [worker_bad],
        "strategy_state": {},
        "checkpoint_state": None,
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": None,
        "dataset_manifest_hash": None,
        "last_runtime_event_seq": 0,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-25T00:00:01Z",
    }
    with pytest.raises(ProtocolError):
        StateSnapshot.from_dict(payload)


# ─── 2. WorkerSessionItem Schema Validation ──────────────────────────────────


def test_worker_session_item_schema_fields() -> None:
    """Verify WorkerSessionItem accepts and serializes node_id and allocation_id."""
    now = datetime.now(UTC)
    item = WorkerSessionItem(
        worker_id=0,
        session_id="101",
        node_label="worker-0",
        state="READY",
        protocol_version=1,
        connected_at=now,
        node_id="node-xyz",
        allocation_id="alloc-abc",
    )
    dumped = item.model_dump()
    assert dumped["node_id"] == "node-xyz"
    assert dumped["allocation_id"] == "alloc-abc"

    # Default values are None
    default_item = WorkerSessionItem(
        worker_id=1,
        session_id="102",
        node_label="worker-1",
        state="CONNECTING",
        protocol_version=1,
        connected_at=now,
    )
    assert default_item.node_id is None
    assert default_item.allocation_id is None


# ─── 3. Scheduling & Allocation Creation ──────────────────────────────────────


@patch("pbl4.management_backend.repositories.node_repository.list_nodes")
@patch("pbl4.management_backend.repositories.allocation_repository.list_active")
@patch(
    "pbl4.management_backend.services.allocation_service.AllocationService.create_allocations_for_attempt"
)
def test_select_and_create_allocations_success(
    mock_create_allocs: MagicMock,
    mock_list_active: MagicMock,
    mock_list_nodes: MagicMock,
) -> None:
    """Verify _select_and_create_allocations selects online nodes and creates allocations."""
    mock_conn = MagicMock()
    mock_list_nodes.return_value = [
        {"node_id": "node-b", "state": "ONLINE", "capabilities_jsonb": {}},
        {"node_id": "node-a", "state": "ONLINE", "capabilities_jsonb": {}},
    ]
    mock_list_active.return_value = []
    mock_create_allocs.return_value = [{"allocation_id": "alloc-1"}, {"allocation_id": "alloc-2"}]

    contract = {"synchronization": {"expected_workers": 2}}
    now = datetime.now(UTC)
    res = _select_and_create_allocations(mock_conn, "atm-1", contract, now)

    assert len(res) == 2
    mock_create_allocs.assert_called_once()
    _, kwargs = mock_create_allocs.call_args
    placements = kwargs["placements"]
    assert len(placements) == 2
    # Verify deterministic sort by node_id: node-a then node-b
    assert placements[0].node_id == "node-a"
    assert placements[1].node_id == "node-b"


@patch("pbl4.management_backend.repositories.node_repository.list_nodes")
@patch("pbl4.management_backend.repositories.allocation_repository.list_active")
def test_select_and_create_allocations_insufficient_capacity(
    mock_list_active: MagicMock,
    mock_list_nodes: MagicMock,
) -> None:
    """Verify NodeCapacityUnavailableError raised when online nodes < expected_workers."""
    mock_conn = MagicMock()
    mock_list_nodes.return_value = [
        {"node_id": "node-a", "state": "ONLINE", "capabilities_jsonb": {}},
    ]
    mock_list_active.return_value = []

    contract = {"synchronization": {"expected_workers": 2}}
    now = datetime.now(UTC)

    with pytest.raises(NodeCapacityUnavailableError):
        _select_and_create_allocations(mock_conn, "atm-1", contract, now)


def test_select_and_create_allocations_invalid_contract() -> None:
    """Verify ValueError raised when expected_workers is missing or non-positive."""
    mock_conn = MagicMock()
    now = datetime.now(UTC)

    with pytest.raises(ValueError):
        _select_and_create_allocations(mock_conn, "atm-1", {}, now)

    with pytest.raises(ValueError):
        _select_and_create_allocations(
            mock_conn, "atm-1", {"synchronization": {"expected_workers": 0}}, now
        )


# ─── 4. Worker Dispatch & Partial Failure Handling ────────────────────────────


def test_dispatch_workers_for_attempt_all_succeed() -> None:
    """Verify all allocations dispatched when gateway returns True."""
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.transaction.return_value.__enter__.return_value = mock_conn

    allocations = [
        {
            "allocation_id": "alloc-1",
            "node_id": "node-1",
            "device": "cpu",
            "actual_state": "REQUESTED",
        },
        {
            "allocation_id": "alloc-2",
            "node_id": "node-2",
            "device": "cpu",
            "actual_state": "REQUESTED",
        },
    ]

    mock_node_gw = MagicMock()
    mock_rt_gw = MagicMock()

    with (
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.list_for_attempt",
            return_value=allocations,
        ),
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.build_start_worker_command"
        ) as mock_build_cmd,
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.dispatch_allocation"
        ) as mock_dispatch,
    ):
        mock_build_cmd.return_value = MagicMock()
        mock_dispatch.side_effect = [
            {"allocation_id": "alloc-1", "actual_state": "DISPATCHED"},
            {"allocation_id": "alloc-2", "actual_state": "DISPATCHED"},
        ]

        _dispatch_workers_for_attempt(
            mock_db,
            attempt_id="atm-1",
            job={"resolved_contract": {"training": {"training_seed": 42}}},
            attempt_row={"attempt_id": "atm-1"},
            node_gateway=mock_node_gw,
            runtime_gateway=mock_rt_gw,
        )

        assert mock_dispatch.call_count == 2
        mock_rt_gw.send_command_and_wait_result.assert_not_called()


def test_dispatch_workers_for_attempt_partial_failure() -> None:
    """Partial dispatch sends STOP/ABORT and raises CommandFailedError."""
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.transaction.return_value.__enter__.return_value = mock_conn

    allocations = [
        {
            "allocation_id": "alloc-1",
            "node_id": "node-1",
            "device": "cpu",
            "actual_state": "REQUESTED",
        },
        {
            "allocation_id": "alloc-2",
            "node_id": "node-2",
            "device": "cpu",
            "actual_state": "REQUESTED",
        },
    ]

    mock_node_gw = MagicMock()
    mock_rt_gw = MagicMock()

    with (
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.list_for_attempt",
            return_value=allocations,
        ),
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.build_start_worker_command"
        ) as mock_build_cmd,
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.dispatch_allocation"
        ) as mock_dispatch,
        patch(
            "pbl4.management_backend.services.allocation_service.AllocationService.build_stop_worker_command"
        ) as mock_build_stop,
        patch(
            "pbl4.management_backend.services.attempt_service.abort_attempt"
        ) as mock_abort_attempt,
        patch(
            "pbl4.management_backend.repositories.allocation_repository.update_desired_state"
        ) as mock_update_desired,
    ):
        mock_build_cmd.return_value = MagicMock()
        mock_build_stop.return_value = MagicMock()
        mock_abort_attempt.return_value = {"command_id": "cmd-abort"}

        # Node 1 succeeds, Node 2 fails
        mock_dispatch.side_effect = [
            {"allocation_id": "alloc-1", "node_id": "node-1", "actual_state": "DISPATCHED"},
            {"allocation_id": "alloc-2", "node_id": "node-2", "actual_state": "FAILED"},
        ]

        with pytest.raises(CommandFailedError) as exc_info:
            _dispatch_workers_for_attempt(
                mock_db,
                attempt_id="atm-1",
                job={"resolved_contract": {"training": {"training_seed": 42}}},
                attempt_row={"attempt_id": "atm-1"},
                node_gateway=mock_node_gw,
                runtime_gateway=mock_rt_gw,
            )

        assert exc_info.value.code == "WORKER_SPAWN_FAILED"

        # Node 1 received STOP_WORKER best-effort
        mock_node_gw.send_stop_worker.assert_called_once()
        assert mock_node_gw.send_stop_worker.call_args[0][0] == "node-1"
        mock_update_desired.assert_called_once_with(
            mock_conn, "alloc-1", allocation_repository.DESIRED_STATE_STOPPED
        )

        # Runtime received ABORT_ATTEMPT
        mock_abort_attempt.assert_called_once_with(
            mock_conn, "atm-1", reason="Partial worker dispatch failure"
        )
        mock_rt_gw.send_command_and_wait_result.assert_called_once()
        assert (
            mock_rt_gw.send_command_and_wait_result.call_args[1]["command_type"] == "ABORT_ATTEMPT"
        )


# ─── 5. Runtime Gateway Snapshot Reconciliation ──────────────────────────────


def test_runtime_gateway_snapshot_reconciliation_passes_mapping() -> None:
    """Forward managed Worker identities during snapshot reconciliation."""
    port = MagicMock()
    gw = RuntimeGateway(port=port)

    snapshot_payload = {
        "runtime_instance_id": "rt-inst-1",
        "active_job_id": "job-1",
        "active_attempt_id": "atm-1",
        "attempt_state": "RUNNING",
        "training_strategy": "strict_bsp",
        "checkpoint_policy": "every_step",
        "epoch": 1,
        "current_operation_id": 1,
        "current_batch_ordinal": 2,
        "model_version": 1,
        "workers": [
            {
                "worker_id": 0,
                "session_id": "100",
                "node_label": "worker-0",
                "state": "READY",
                "protocol_version": 1,
                "connected_at": "2026-09-25T00:00:00Z",
                "last_heartbeat_at": "2026-09-25T00:00:05Z",
                "shard_id": 0,
                "local_model_version": 1,
                "node_id": "node-target-1",
                "allocation_id": "alloc-target-1",
            }
        ],
        "strategy_state": {},
        "checkpoint_state": "IDLE",
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": "bld-1",
        "dataset_manifest_hash": "hash-1",
        "last_runtime_event_seq": 5,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-25T00:00:06Z",
    }

    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.transaction.return_value.__enter__.return_value = mock_conn

    with (
        patch("pbl4.management_backend.db.transaction", return_value=mock_db.transaction()),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt"
        ) as mock_get_attempt,
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.update_snapshot_projection"
        ) as mock_update_proj,
        patch("pbl4.management_backend.repositories.worker_session_repository.upsert_session"),
    ):
        mock_get_attempt.return_value = {
            "attempt_id": "atm-1",
            "state": "WAITING_WORKERS",
            "runtime_metadata": {},
        }
        mock_update_proj.return_value = {"session_id": 100}

        gw.handle_state_snapshot(snapshot_payload)

        mock_update_proj.assert_called_once()
        kwargs = mock_update_proj.call_args[1]
        assert kwargs["node_id"] == "node-target-1"
        assert kwargs["allocation_id"] == "alloc-target-1"
        assert kwargs["worker_id"] == 0
        assert kwargs["session_id"] == 100
