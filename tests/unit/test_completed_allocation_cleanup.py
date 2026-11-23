"""Committed stop intents survive unavailable Agents and Backend restarts."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pbl4.management_backend.app import _run_node_maintenance_once
from pbl4.management_backend.services.allocation_service import AllocationService


@pytest.mark.parametrize("connected", [False, True])
def test_completion_persists_intent_without_network_or_false_failure(connected):
    conn = MagicMock()
    gateway = MagicMock()
    gateway.is_node_connected.return_value = connected
    allocation = {"allocation_id": "allocation", "node_id": "node", "actual_state": "STARTED"}
    with (
        patch("pbl4.management_backend.services.allocation_service.allocation_repository") as repo,
        patch(
            "pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway",
            return_value=gateway,
        ),
    ):
        repo.DESIRED_STATE_STOPPED = "STOPPED"
        repo.ACTUAL_STATE_REQUESTED = "REQUESTED"
        repo.list_for_attempt.return_value = [allocation]
        AllocationService.cleanup_allocations_for_attempt(conn, "attempt", completed=True)
        repo.update_desired_state.assert_called_once_with(conn, "allocation", "STOPPED")
        repo.terminal_update.assert_not_called()
        gateway.send_stop_worker.assert_not_called()


@pytest.mark.parametrize("connected", [False, True])
def test_maintenance_retries_only_completed_committed_intents(connected):
    conn = MagicMock()
    gateway = MagicMock()
    gateway.is_node_connected.return_value = connected
    in_transaction = []

    @contextmanager
    def transaction():
        in_transaction.append(True)
        try:
            yield conn
        finally:
            in_transaction.pop()

    def send(*args, **kwargs):
        assert not in_transaction
        assert kwargs["command"].allocation_id == "done"
        return False  # Failed transmission must leave the durable intent intact.

    gateway.send_stop_worker.side_effect = send

    def allocation(identity, desired="STOPPED"):
        return {
            "allocation_id": identity,
            "attempt_id": identity,
            "node_id": "node",
            "actual_state": "STARTED",
            "desired_state": desired,
        }

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch("pbl4.management_backend.services.node_service.mark_stale_nodes"),
        patch(
            "pbl4.management_backend.services.allocation_service.fail_timed_out_dispatched_allocations",
            return_value=[],
        ),
        patch(
            "pbl4.management_backend.repositories.allocation_repository.list_active",
            return_value=[
                allocation("done"),
                allocation("running"),
                allocation("no-intent", "RUNNING"),
            ],
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            side_effect=lambda c, a: {"state": "COMPLETED" if a == "done" else "RUNNING"},
        ),
        patch(
            "pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway",
            return_value=gateway,
        ),
        patch("pbl4.management_backend.gateways.runtime_gateway.get_gateway"),
    ):
        settings = SimpleNamespace(
            node_heartbeat_timeout_seconds=30, worker_start_timeout_seconds=30
        )
        _run_node_maintenance_once(settings)
        _run_node_maintenance_once(settings)  # Also represents another Backend instance/cycle.
        assert gateway.send_stop_worker.call_count == (2 if connected else 0)


def test_stop_intent_is_not_reclassified_as_worker_start_timeout():
    with (
        patch(
            "pbl4.management_backend.repositories.allocation_repository.list_active",
            return_value=[{"actual_state": "DISPATCHED", "desired_state": "STOPPED"}],
        ),
        patch(
            "pbl4.management_backend.repositories.allocation_repository.terminal_update"
        ) as terminal,
    ):
        assert (
            AllocationService.fail_timed_out_dispatched_allocations(MagicMock(), timeout_seconds=1)
            == []
        )
        terminal.assert_not_called()


@pytest.mark.parametrize("state", ["COMPLETED", "FAILED", "ABORTED"])
def test_event_and_snapshot_projection_select_completion_cleanup(state):
    from datetime import UTC, datetime

    from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway

    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.update_attempt_state",
            return_value={"state": state},
        ),
        patch(
            "pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt"
        ) as cleanup,
    ):
        RuntimeGateway._project_attempt_state_transition(
            MagicMock(), "attempt", state, occurred_at=datetime.now(UTC)
        )
        assert cleanup.call_args.kwargs["completed"] is (state == "COMPLETED")
