"""Unit tests for Backend Step and Checkpoint projection (Task B5)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway


def test_model_updated_before_ack_is_waiting_parameter_applied():
    """model.updated sets WAITING_PARAMETER_APPLIED, not COMMITTED."""
    occurred_at = "2026-10-19T10:00:00+00:00"
    payload = {
        "attempt_id": "attempt-1",
        "event_type": "model.updated",
        "occurred_at": occurred_at,
        "details": {
            "step_id": 1,
            "output_model_version": 2,
            "total_sample_count": 32,
            "contributions": [],
        },
    }
    with patch("pbl4.management_backend.repositories.step_repository.update_step") as mock_update:
        RuntimeGateway._project_runtime_event(object(), payload)
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["state"] == "WAITING_PARAMETER_APPLIED"


def test_step_committed_projects_committed_and_subsequent_checkpoint_events_preserve_committed():
    """step.committed sets COMMITTED; checkpoint events do not roll back step."""
    occurred_at = "2026-10-19T10:00:01+00:00"
    step_payload = {
        "attempt_id": "attempt-1",
        "event_type": "step.committed",
        "occurred_at": occurred_at,
        "details": {
            "step_id": 1,
            "operation_id": 1,
            "output_model_version": 2,
            "total_sample_count": 32,
            "synchronization_completed_at": occurred_at,
            "committed_at": occurred_at,
        },
    }
    with patch("pbl4.management_backend.repositories.step_repository.update_step") as mock_update:
        RuntimeGateway._project_runtime_event(object(), step_payload)
        mock_update.assert_called_once()
        assert mock_update.call_args.kwargs["state"] == "COMMITTED"
        assert mock_update.call_args.kwargs["output_model_version"] == 2
        assert mock_update.call_args.kwargs["total_sample_count"] == 32

    # checkpoint.started: creates checkpoint row
    started_payload = {
        "attempt_id": "attempt-1",
        "event_type": "checkpoint.started",
        "occurred_at": occurred_at,
        "details": {
            "checkpoint_id": "ckpt-1",
            "source_operation_id": 1,
            "source_step_id": 1,
            "model_version": 2,
            "recovery_cursor": {"epoch": 1, "next_batch_ordinal": 0},
            "contract_hash": "a" * 64,
            "dataset_build_id": "ds-1",
            "dataset_manifest_hash": "b" * 64,
            "parameter_manifest_hash": "c" * 64,
            "checkpoint_policy": "periodic",
            "checkpoint_policy_version": 1,
            "created_at": occurred_at,
            "is_final": False,
        },
    }
    with (
        patch("pbl4.management_backend.repositories.checkpoint_repository.create_checkpoint") as mock_create_ckpt,
        patch("pbl4.management_backend.repositories.step_repository.update_step") as mock_step_update,
    ):
        RuntimeGateway._project_runtime_event(object(), started_payload)
        mock_create_ckpt.assert_called_once()
        assert mock_create_ckpt.call_args.kwargs["checkpoint_id"] == "ckpt-1"

    # checkpoint.failed: fails checkpoint row, does NOT update step state
    failed_payload = {
        "attempt_id": "attempt-1",
        "event_type": "checkpoint.failed",
        "occurred_at": occurred_at,
        "details": {
            "checkpoint_id": "ckpt-1",
            "is_final": False,
            "reason": "Checkpoint attempts exhausted",
        },
    }
    conn = object()
    with (
        patch("pbl4.management_backend.repositories.checkpoint_repository.fail_checkpoint") as mock_fail_ckpt,
        patch("pbl4.management_backend.repositories.step_repository.update_step") as mock_step_update,
    ):
        RuntimeGateway._project_runtime_event(conn, failed_payload)
        mock_fail_ckpt.assert_called_once_with(conn, "ckpt-1")
        mock_step_update.assert_not_called()


def test_final_checkpoint_failed_sets_warning_metadata_and_preserves_completed():
    """Final checkpoint failure records warning in attempt.runtime_metadata and attempt transitions to COMPLETED."""
    occurred_at = "2026-10-19T10:00:05+00:00"
    failed_payload = {
        "attempt_id": "attempt-1",
        "event_type": "checkpoint.failed",
        "occurred_at": occurred_at,
        "details": {
            "checkpoint_id": "ckpt-final",
            "is_final": True,
            "reason": "I/O error during final checkpoint",
        },
    }
    attempt_row = {
        "attempt_id": "attempt-1",
        "state": "RUNNING",
        "runtime_metadata": {"authoritative_snapshot_seq": 10},
    }

    conn = object()
    with (
        patch("pbl4.management_backend.repositories.checkpoint_repository.fail_checkpoint") as mock_fail_ckpt,
        patch("pbl4.management_backend.repositories.attempt_repository.get_attempt", return_value=attempt_row),
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state") as mock_update_state,
    ):
        RuntimeGateway._project_runtime_event(conn, failed_payload)
        mock_fail_ckpt.assert_called_once_with(conn, "ckpt-final")
        mock_update_state.assert_called_once()
        saved_meta = mock_update_state.call_args.kwargs["runtime_metadata"]
        assert saved_meta["final_checkpoint_failed"] is True
        assert saved_meta["final_checkpoint_id"] == "ckpt-final"
        assert saved_meta["final_checkpoint_reason"] == "I/O error during final checkpoint"
        assert saved_meta["authoritative_snapshot_seq"] == 10

    # Followed by attempt.state_changed -> COMPLETED
    completed_payload = {
        "attempt_id": "attempt-1",
        "event_type": "attempt.state_changed",
        "occurred_at": occurred_at,
        "details": {"state": "COMPLETED"},
    }
    with (
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state") as mock_update_state,
        patch("pbl4.management_backend.services.allocation_service.cleanup_allocations_for_attempt"),
    ):
        RuntimeGateway._project_runtime_event(object(), completed_payload)
        mock_update_state.assert_called_once()
        assert mock_update_state.call_args[0][2] == "COMPLETED"


def test_step_repository_update_step_monotonicity_sql():
    """Verify update_step SQL includes protection against downgrading COMMITTED steps."""
    from pbl4.management_backend.repositories import step_repository

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {"step_id": 1, "state": "COMMITTED"}

    step_repository.update_step(mock_conn, "attempt-1", 1, state="CHECKPOINTING")

    executed_sql = mock_cur.execute.call_args[0][0]
    assert "CASE WHEN state = 'COMMITTED' THEN state ELSE %s END" in executed_sql
