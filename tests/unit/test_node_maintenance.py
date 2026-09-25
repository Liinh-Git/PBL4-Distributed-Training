from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pbl4.management_backend.app import _run_node_maintenance_once


def test_worker_start_timeout_persists_abort_and_stops_remaining_allocations() -> None:
    settings = SimpleNamespace(
        node_heartbeat_timeout_seconds=30.0,
        worker_start_timeout_seconds=60.0,
    )
    connection = MagicMock()
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = connection
    runtime_gateway = MagicMock()
    node_gateway = MagicMock()
    abort_command = {
        "command_id": "cmd-abort-timeout",
        "request_jsonb": {
            "command_id": "cmd-abort-timeout",
            "attempt_id": "attempt-timeout",
            "reason": "Worker start timeout",
        },
    }

    with (
        patch("pbl4.management_backend.db.transaction", transaction),
        patch(
            "pbl4.management_backend.services.node_service.mark_stale_nodes",
            return_value=[],
        ),
        patch(
            "pbl4.management_backend.services.allocation_service."
            "fail_timed_out_dispatched_allocations",
            return_value=["allocation-timeout"],
        ),
        patch(
            "pbl4.management_backend.services.allocation_service.get_allocation",
            return_value={"attempt_id": "attempt-timeout"},
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"attempt_id": "attempt-timeout", "state": "RUNNING"},
        ),
        patch(
            "pbl4.management_backend.services.attempt_service.abort_attempt",
            return_value=abort_command,
        ) as persist_abort,
        patch(
            "pbl4.management_backend.services.allocation_service.list_for_attempt",
            return_value=[{"allocation_id": "allocation-still-active"}],
        ),
        patch(
            "pbl4.management_backend.services.allocation_service.stop_allocation"
        ) as stop_allocation,
        patch(
            "pbl4.management_backend.gateways.runtime_gateway.get_gateway",
            return_value=runtime_gateway,
        ),
        patch(
            "pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway",
            return_value=node_gateway,
        ),
    ):
        _run_node_maintenance_once(settings)

    persist_abort.assert_called_once_with(
        connection,
        "attempt-timeout",
        reason="Worker start timeout",
    )
    runtime_gateway.send_command_and_wait_result.assert_called_once_with(
        command_type="ABORT_ATTEMPT",
        command_id="cmd-abort-timeout",
        target_id="attempt-timeout",
        payload=abort_command["request_jsonb"],
        timeout=5.0,
    )
    stop_allocation.assert_called_once_with(
        connection,
        "allocation-still-active",
        gateway=node_gateway,
        force=True,
    )
