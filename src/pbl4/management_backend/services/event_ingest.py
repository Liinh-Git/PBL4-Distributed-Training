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
from datetime import UTC, datetime

import psycopg

from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.repositories import event_repository

logger = logging.getLogger(__name__)


class ConflictingEventPayloadError(Exception):
    """Raised when an incoming event has the same sequence number but different payload."""


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
    """Persist a runtime event with deduplication, conflict checking, and gap detection."""
    now = datetime.now(UTC)
    norm_payload = payload or {}

    # Check deduplication and payload integrity if sequence number is present
    if attempt_id is not None and runtime_event_seq is not None:
        existing = event_repository.get_event_by_seq(conn, attempt_id, runtime_event_seq)
        if existing is not None:
            existing_payload = existing.get("payload_jsonb")
            if isinstance(existing_payload, str):
                with contextlib.suppress(Exception):
                    existing_payload = json.loads(existing_payload)
            if (existing_payload or {}) == norm_payload:
                logger.debug(
                    "Idempotent duplicate runtime event skipped: attempt_id=%s seq=%s",
                    attempt_id,
                    runtime_event_seq,
                )
                return existing
            logger.error(
                "Conflicting payload for runtime event: attempt_id=%s seq=%s existing=%s new=%s",
                attempt_id,
                runtime_event_seq,
                existing_payload,
                norm_payload,
            )
            raise ConflictingEventPayloadError(
                f"Conflicting payload for attempt {attempt_id} event seq {runtime_event_seq}"
            )

        latest_seq = event_repository.get_latest_runtime_event_seq(conn, attempt_id)
        if latest_seq is not None and runtime_event_seq > latest_seq + 1:
            logger.warning(
                "Event gap detected for attempt %s: expected seq=%s, received seq=%s",
                attempt_id,
                latest_seq + 1,
                runtime_event_seq,
            )
            try:
                gw = get_gateway()
                cur_gap_count = gw.get_snapshot().get("management_event_gap_count", 0)
                gw.update_snapshot({"management_event_gap_count": cur_gap_count + 1})
            except Exception:
                pass

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
        # Concurrent insert occurred, re-fetch and check payload
        existing = event_repository.get_event_by_seq(conn, attempt_id, runtime_event_seq)
        if existing is not None:
            existing_payload = existing.get("payload_jsonb")
            if isinstance(existing_payload, str):
                with contextlib.suppress(Exception):
                    existing_payload = json.loads(existing_payload)
            if (existing_payload or {}) == norm_payload:
                return existing
            raise ConflictingEventPayloadError(
                f"Conflicting payload for attempt {attempt_id} event seq {runtime_event_seq}"
            )

    if row is not None and attempt_id is not None:
        try:
            from pbl4.management_backend.websocket import hub

            hub.broadcast_sync(
                attempt_id,
                {
                    "type": "RUNTIME_EVENT",
                    "data": {
                        "attempt_id": attempt_id,
                        "runtime_event_seq": runtime_event_seq,
                        "event_type": event_type,
                        "occurred_at": (
                            occurred_at.isoformat()
                            if hasattr(occurred_at, "isoformat")
                            else str(occurred_at)
                        ),
                        "source_component": source_component,
                        "severity": severity,
                        "payload": norm_payload,
                    },
                },
            )
        except Exception as exc:
            logger.debug("Failed to broadcast runtime event: %s", exc)

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
                    "type": "MANAGEMENT_EVENT",
                    "data": {
                        "event_type": event_type,
                        "severity": severity,
                        "occurred_at": now.isoformat(),
                        "source_component": "Management",
                        "scope_id": scope_id,
                        "payload": payload or {},
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
