"""Event Ingest Service — processes and persists runtime events from MCP/1.

Guarantees:
- Monotonic sequence tracking per attempt.
- Idempotent deduplication when receiving identical payloads for existing sequence numbers.
- ConflictingEventPayloadError when receiving different payloads for existing sequence numbers.
- Gap detection when receiving out-of-order sequence numbers (seq > last_seen + 1).
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from pbl4.management_backend.repositories import event_repository

logger = logging.getLogger(__name__)


class ConflictingEventPayloadError(Exception):
    """Raised when an incoming event has the same sequence number but different payload."""


@dataclass(frozen=True)
class RuntimeEventIngestResult:
    row: dict | None
    inserted: bool


def _normalize_datetime(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    if isinstance(dt, str):
        with contextlib.suppress(Exception):
            parsed = datetime.fromisoformat(dt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
    return None


def _is_semantic_event_equal(
    existing: dict[str, Any],
    *,
    attempt_id: str | None,
    runtime_event_seq: int | None,
    event_type: str,
    severity: str,
    occurred_at: datetime,
    source_component: str,
    scope_type: str,
    scope_id: str | None,
    norm_payload: dict[str, Any],
) -> bool:
    """Compare all immutable semantic Runtime Event fields.

    Excludes DB-generated metadata (event_id, persisted_at, inserted_at).
    """
    if existing.get("attempt_id") != attempt_id:
        return False
    if existing.get("runtime_event_seq") != runtime_event_seq:
        return False
    if existing.get("event_type") != event_type:
        return False
    if existing.get("severity") != severity:
        return False
    if existing.get("source_component") != source_component:
        return False

    existing_dt = _normalize_datetime(existing.get("occurred_at"))
    incoming_dt = _normalize_datetime(occurred_at)
    if existing_dt != incoming_dt:
        return False

    existing_payload = existing.get("payload_jsonb")
    if isinstance(existing_payload, str):
        with contextlib.suppress(Exception):
            existing_payload = json.loads(existing_payload)
    if (existing_payload or {}) != norm_payload:
        return False

    existing_scope_type = existing.get("scope_type")
    if existing_scope_type is not None and existing_scope_type != scope_type:
        return False

    effective_scope_id = scope_id or attempt_id
    existing_scope_id = existing.get("scope_id")
    return existing_scope_id is None or existing_scope_id == effective_scope_id


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
) -> RuntimeEventIngestResult:
    """Persist a runtime event with deduplication, conflict checking, and gap detection."""
    now = datetime.now(UTC)
    norm_payload = payload or {}

    # Check deduplication and payload integrity if sequence number is present
    if attempt_id is not None and runtime_event_seq is not None:
        existing = event_repository.get_event_by_seq(conn, attempt_id, runtime_event_seq)
        if existing is not None:
            if _is_semantic_event_equal(
                existing,
                attempt_id=attempt_id,
                runtime_event_seq=runtime_event_seq,
                event_type=event_type,
                severity=severity,
                occurred_at=occurred_at,
                source_component=source_component,
                scope_type=scope_type,
                scope_id=scope_id,
                norm_payload=norm_payload,
            ):
                logger.debug(
                    "Idempotent duplicate runtime event skipped: attempt_id=%s seq=%s",
                    attempt_id,
                    runtime_event_seq,
                )
                return RuntimeEventIngestResult(existing, inserted=False)
            logger.error(
                "Conflicting semantic event: attempt_id=%s seq=%s existing=%s new=%s",
                attempt_id,
                runtime_event_seq,
                existing,
                {
                    "event_type": event_type,
                    "severity": severity,
                    "source_component": source_component,
                    "occurred_at": occurred_at,
                    "payload": norm_payload,
                },
            )
            raise ConflictingEventPayloadError(
                f"Conflicting semantic event for attempt {attempt_id} event seq {runtime_event_seq}"
            )

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
        payload=norm_payload,
    )

    if row is None and attempt_id is not None and runtime_event_seq is not None:
        # Concurrent insert occurred, re-fetch and check semantic match
        existing = event_repository.get_event_by_seq(conn, attempt_id, runtime_event_seq)
        if existing is not None:
            if _is_semantic_event_equal(
                existing,
                attempt_id=attempt_id,
                runtime_event_seq=runtime_event_seq,
                event_type=event_type,
                severity=severity,
                occurred_at=occurred_at,
                source_component=source_component,
                scope_type=scope_type,
                scope_id=scope_id,
                norm_payload=norm_payload,
            ):
                return RuntimeEventIngestResult(existing, inserted=False)
            raise ConflictingEventPayloadError(
                f"Conflicting semantic event for attempt {attempt_id} event seq {runtime_event_seq}"
            )

    return RuntimeEventIngestResult(row, inserted=row is not None)


def broadcast_runtime_event(
    *,
    attempt_id: str,
    runtime_event_seq: int | None,
    event_type: str,
    severity: str,
    occurred_at: datetime,
    source_component: str,
    payload: dict | None,
) -> None:
    """Publish a newly persisted Runtime event after its transaction commits."""
    from pbl4.management_backend.websocket import hub

    hub.broadcast_sync(
        attempt_id,
        {
            "kind": "EVENT",
            "attempt_id": attempt_id,
            "runtime_event_seq": runtime_event_seq,
            "occurred_at": occurred_at.isoformat(),
            "payload": {
                "event_type": event_type,
                "severity": severity,
                "source_component": source_component,
                **(payload or {}),
            },
        },
    )


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
    now = datetime.now(UTC)
    row = event_repository.insert_event(
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
    if row is not None and scope_id is not None:
        try:
            from pbl4.management_backend.websocket import hub

            hub.broadcast_sync(
                scope_id,
                {
                    "kind": "EVENT",
                    "attempt_id": scope_id,
                    "runtime_event_seq": None,
                    "occurred_at": now.isoformat(),
                    "payload": {
                        "event_type": event_type,
                        "severity": severity,
                        "source_component": "Management",
                        **(payload or {}),
                    },
                },
            )
        except Exception as exc:
            logger.debug("Failed to broadcast management event: %s", exc)

    return row


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
    after_seq: int | None = None,
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
        after_seq=after_seq,
    )
