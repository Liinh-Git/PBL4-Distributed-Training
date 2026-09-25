"""Node schemas for REST API.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Defines request/response DTOs for:
- One-time enrollment code generation
- Node onboarding and secret issuance
- Node listings and detailed telemetry/capability inspect
- Revocation response

Invariants:
- Never exposes node_secret in listing or detail schemas.
- Plaintext node_secret is ONLY exposed once in NodeEnrollResponse upon successful enrollment.
- Inherits StrictWriteModel for input validation to forbid unexpected fields.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pbl4.management_backend.schemas.common import StrictWriteModel


class NodeItem(BaseModel):
    """Summary projection of a registered node."""

    model_config = ConfigDict(from_attributes=True)

    node_id: str
    display_name: str
    state: str
    agent_version: str | None = None
    platform: str | None = None
    enrolled_at: datetime
    last_seen_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NodeItem:
        return cls(
            node_id=row["node_id"],
            display_name=row["display_name"],
            state=row["state"],
            agent_version=row.get("agent_version"),
            platform=row.get("platform"),
            enrolled_at=row["enrolled_at"],
            last_seen_at=row.get("last_seen_at"),
        )


class NodeDetail(NodeItem):
    """Detailed inspection of a node including hardware capabilities and latest telemetry."""

    capabilities: dict[str, Any] = Field(default_factory=dict)
    latest_resources: dict[str, Any] | None = None
    credential_created_at: datetime
    credential_revoked_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NodeDetail:
        caps = row.get("capabilities_jsonb") or row.get("capabilities") or {}
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except Exception:
                caps = {}

        resources = row.get("latest_resources_jsonb") or row.get("latest_resources")
        if isinstance(resources, str):
            try:
                resources = json.loads(resources)
            except Exception:
                resources = None

        return cls(
            node_id=row["node_id"],
            display_name=row["display_name"],
            state=row["state"],
            agent_version=row.get("agent_version"),
            platform=row.get("platform"),
            enrolled_at=row["enrolled_at"],
            last_seen_at=row.get("last_seen_at"),
            capabilities=caps,
            latest_resources=resources,
            credential_created_at=row["credential_created_at"],
            credential_revoked_at=row.get("credential_revoked_at"),
        )


class EnrollmentCodeCreateRequest(StrictWriteModel):
    """Request payload to create a new one-time enrollment code."""

    ttl_seconds: int = Field(
        default=3600,
        gt=0,
        le=86400 * 7,
        description="Time-to-live in seconds for the one-time enrollment code (default 1 hour).",
    )


class EnrollmentCodeCreateResponse(BaseModel):
    """Response returned when an enrollment code is successfully generated."""

    enrollment_code: str = Field(
        description="Plaintext one-time code to be distributed to node operator."
    )
    code_hash: str = Field(description="SHA-256 digest persisted in backend.")
    created_at: datetime
    expires_at: datetime


class NodeEnrollRequest(StrictWriteModel):
    """Payload sent by Node Agent or operator to enroll a new node."""

    enrollment_code: str = Field(
        min_length=1, description="One-time enrollment code issued by backend."
    )
    display_name: str | None = Field(
        default=None, max_length=128, description="Optional human-readable label."
    )
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="Static node hardware capabilities (CPU, RAM, GPUs).",
    )
    agent_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default=None, max_length=128)


class NodeEnrollResponse(BaseModel):
    """Response returned upon successful enrollment. Contains node_secret exactly once."""

    node_id: str
    node_secret: str = Field(
        description="Secret token for outbound WSS control authentication. Shown only once."
    )
    node: NodeItem
