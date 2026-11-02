"""Immutable historical Runtime facts, using the canonical MCP event envelope."""

import json
from dataclasses import dataclass, field

from pbl4.common.hashing import canonical_json_bytes


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    attempt_id: str
    job_id: str
    runtime_event_seq: int
    event_type: str
    event_schema_version: int
    occurred_at: str
    source_component: str
    severity: str
    _details_json: bytes
    delivery_priority: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.severity not in ("INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError("Invalid EventSeverity")
        if type(self.runtime_event_seq) is not int or self.runtime_event_seq <= 0:
            raise ValueError("Invalid event sequence")
        details = json.loads(self._details_json)
        if not isinstance(details, dict):
            raise ValueError("Event details must be an object")
        object.__setattr__(self, "_details_json", canonical_json_bytes(details))
        if (
            details.get("state") in ("COMPLETED", "FAILED", "ABORTED")
            or self.event_type == "attempt.failed"
            or self.severity in ("ERROR", "CRITICAL")
        ):
            priority = 3
        elif (
            self.event_type in ("step.committed", "epoch.metrics.finalized")
            or self.event_type.startswith("checkpoint.")
            or self.event_type.endswith(".state_changed")
        ):
            priority = 2
        else:
            priority = 0 if self.event_type == "metric.sample" else 1
        object.__setattr__(self, "delivery_priority", priority)

    @property
    def details(self) -> dict[str, object]:
        """Return a detached presentation copy, never mutable historical storage."""
        return json.loads(self._details_json)

    @classmethod
    def create(cls, *, details: dict[str, object], **envelope: object) -> "RuntimeEvent":
        # bytes/NumPy tensors are not JSON metadata and are rejected here.
        return cls(**envelope, _details_json=canonical_json_bytes(details))
