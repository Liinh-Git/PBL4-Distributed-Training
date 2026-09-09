from __future__ import annotations

from pbl4.management_backend.gateways.mcp_projection import project_command
from pbl4.management_protocol.messages import AbortAttempt, RequestCheckpoint, StartAttempt


def test_start_attempt_projection_strips_backend_only_metadata() -> None:
    request = {
        "command_id": "cmd-1",
        "job_id": "job-1",
        "attempt_id": "attempt-1",
        "execution_mode": "FRESH",
        "resolved_contract": {"dataset_build_id": "build-1"},
        "contract_hash": "hash-1",
        "resume_from_checkpoint_id": None,
        "requested_at": "2026-09-09T00:00:00+00:00",
        "note": "Backend-only operator note",
        "request_id": "api-request-1",
    }
    wire = project_command(
        "START_ATTEMPT", command_id="cmd-1", target_id="attempt-1", request=request
    )
    assert StartAttempt.from_dict(wire).to_dict() == wire
    assert "note" not in wire
    assert "request_id" not in wire


def test_abort_and_checkpoint_projection_supply_exact_job_identity() -> None:
    common = {
        "command_id": "cmd-2",
        "job_id": "job-1",
        "attempt_id": "attempt-1",
        "reason": "operator",
        "requested_at": "2026-09-09T00:00:00+00:00",
        "internal": "must-not-leak",
    }
    abort_wire = project_command(
        "ABORT_ATTEMPT", command_id="cmd-2", target_id="attempt-1", request=common
    )
    checkpoint_wire = project_command(
        "REQUEST_CHECKPOINT", command_id="cmd-2", target_id="attempt-1", request=common
    )
    assert AbortAttempt.from_dict(abort_wire).to_dict() == abort_wire
    assert RequestCheckpoint.from_dict(checkpoint_wire).to_dict() == checkpoint_wire
    assert "internal" not in abort_wire
    assert "internal" not in checkpoint_wire
