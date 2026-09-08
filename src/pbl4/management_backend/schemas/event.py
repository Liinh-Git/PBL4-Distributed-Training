"""Pydantic schemas for Event endpoints.

Aligned to api_contract_formatted.md — BE Audit and BE Event History groups.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ScopeRef(BaseModel):
    type: str
    id: str | None = None


class EventListItem(BaseModel):
    event_id: str  # BIGSERIAL serialized as string per contract
    scope: ScopeRef
    event_type: str
    severity: str
    occurred_at: datetime
    summary: str | None = None


class RuntimeEventItem(BaseModel):
    attempt_id: str
    job_id: str | None = None
    runtime_event_seq: int
    event_type: str
    event_schema_version: int = 1
    occurred_at: datetime
    source_component: str
    severity: str
    details: dict[str, Any] = {}


class RuntimeEventsMeta(BaseModel):
    complete: bool
    gap_detected: bool
    snapshot_required: bool
