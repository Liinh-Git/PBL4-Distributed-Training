"""Explicit mappings from durable Backend command JSON to canonical MCP/1 DTOs."""

from __future__ import annotations

from typing import Any

from pbl4.common.errors import ProtocolError
from pbl4.management_protocol.messages import AbortAttempt, RequestCheckpoint, StartAttempt


def project_command(
    command_type: str,
    *,
    command_id: str,
    target_id: str,
    request: dict[str, Any] | None,
) -> dict[str, object]:
    """Project persistence shape to an exact wire payload; never leak extra JSON fields."""
    source = request or {}
    if source.get("command_id", command_id) != command_id:
        raise ProtocolError("Durable command_id does not match dispatch identity")
    if source.get("attempt_id", target_id) != target_id:
        raise ProtocolError("Durable attempt_id does not match dispatch target")

    if command_type == "START_ATTEMPT":
        return StartAttempt.from_dict(
            {
                "command_id": command_id,
                "job_id": source.get("job_id"),
                "attempt_id": target_id,
                "execution_mode": source.get("execution_mode"),
                "resolved_contract": source.get("resolved_contract"),
                "contract_hash": source.get("contract_hash"),
                "resume_from_checkpoint_id": source.get("resume_from_checkpoint_id"),
                "requested_at": source.get("requested_at"),
            }
        ).to_dict()
    if command_type == "ABORT_ATTEMPT":
        return AbortAttempt.from_dict(
            {
                "command_id": command_id,
                "job_id": source.get("job_id"),
                "attempt_id": target_id,
                "reason": source.get("reason") or "No reason provided.",
                "requested_at": source.get("requested_at"),
            }
        ).to_dict()
    if command_type == "REQUEST_CHECKPOINT":
        values: dict[str, object] = {
            "command_id": command_id,
            "job_id": source.get("job_id"),
            "attempt_id": target_id,
            "reason": source.get("reason") or "Operator requested checkpoint.",
        }
        if source.get("requested_at") is not None:
            values["requested_at"] = source["requested_at"]
        return RequestCheckpoint.from_dict(values).to_dict()
    raise ProtocolError(f"Unsupported Backend-to-Runtime command type: {command_type}")
