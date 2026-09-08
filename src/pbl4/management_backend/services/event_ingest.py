"""Event Ingest Service — processes and persists runtime events from MCP/1.

Deduplication: events with the same (attempt_id, runtime_event_seq) are skipped.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg

from management_backend.repositories import event_repository

logger = logging.getLogger(__name__)


def ingest_runtime_event(
    conn: psycopg.Connection,
    *,
    attempt_id: str | None = None,
    runtime_event_seq: int | None = None,
    event_type: str,
    severity: str,
    occurred_at: datetime,
    source_component: str = "Runtime",
    scope_type: str = "ATTEMPT",
    scope_id: str | None = None,
    payload: dict | None = None,
) -> dict | None:
    """Persist a runtime event. Returns None if the event was a duplicate and skipped."""
    now = datetime.now(timezone.utc)
    row = event_repository.insert_event(
        conn,
        event_type=event_type,
        scope_type=scope_type,
        severity=severity,
        occurred_at=occurred_at,
        persisted_at=now,
        attempt_id=attempt_id,
        runtime_event_seq=runtime_event_seq,
        source_component=source_component,
        scope_id=scope_id or attempt_id,
        payload=payload,
    )
    if row is None:
        logger.debug(
            "Duplicate runtime event skipped: attempt_id=%s seq=%s type=%s",
            attempt_id, runtime_event_seq, event_type,
        )
    else:
        logger.debug(
            "Runtime event persisted: id=%s type=%s attempt=%s",
            row.get("event_id"), event_type, attempt_id,
        )
    return row


def ingest_management_event(
    conn: psycopg.Connection,
    *,
    event_type: str,
    severity: str = "INFO",
    scope_type: str = "SYSTEM",
    scope_id: str | None = None,
    payload: dict | None = None,
) -> dict | None:
    """Persist a management-plane event (no runtime_event_seq dedup)."""
    now = datetime.now(timezone.utc)
    return event_repository.insert_event(
        conn,
        event_type=event_type,
        scope_type=scope_type,
        severity=severity,
        occurred_at=now,
        persisted_at=now,
        source_component="Management",
        scope_id=scope_id,
        payload=payload,
    )


def list_events(
    conn: psycopg.Connection,
    *,
    attempt_id: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    event_type: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> list[dict]:
    return event_repository.list_events(
        conn,
        attempt_id=attempt_id,
        scope_type=scope_type,
        scope_id=scope_id,
        event_type=event_type,
        severity=severity,
        limit=limit,
        cursor=cursor,
    )
