"""Idempotency Service — durable request deduplication and lease tracking.

CANONICAL REFERENCES:
- 04. API Backend & Contracts (Idempotency-Key scoping, conflict codes, retry state machine)
- 03. Mô hình dữ liệu (idempotency_records table)

INVARIANTS:
- Identity scope is composite: (operator_identity, endpoint_semantic_scope, idempotency_key).
- Request hash incorporates semantic operation, target path, normalized query, and body.
- Reusing the same key with different request identity raises
  IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST (HTTP 409).
- A retry with matching key and matching payload reuses existing command/resource identity.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from pbl4.common.hashing import canonical_json_hash

logger = logging.getLogger(__name__)

CONFLICT_CODE_REUSED_WITH_DIFFERENT_REQUEST = "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
CONFLICT_CODE_IN_PROGRESS = "REQUEST_IN_PROGRESS"


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a conflicting request payload."""

    def __init__(
        self,
        msg: str = "Idempotency key reused with different request payload or scope.",
        code: str = CONFLICT_CODE_REUSED_WITH_DIFFERENT_REQUEST,
    ) -> None:
        super().__init__(msg)
        self.code = code


class RequestInProgressError(Exception):
    """Raised when an identical request is actively holding a valid lease."""

    def __init__(
        self,
        msg: str = "An identical request is currently in progress.",
        code: str = CONFLICT_CODE_IN_PROGRESS,
    ) -> None:
        super().__init__(msg)
        self.code = code


def compute_request_hash(
    operation: str,
    path: str,
    query_params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    body_obj: dict[str, Any] | None = None,
) -> str:
    """Compute deterministic SHA-256 hash over canonical request identity tuple."""
    payload = {
        "operation": operation,
        "path": path,
        "query": query_params or {},
        "body": body_obj if body_obj is not None else (body or {}),
    }
    return canonical_json_hash(payload)


build_request_hash = compute_request_hash


def acquire_or_get_record(
    conn: psycopg.Connection,
    *,
    operator_identity: str = "default",
    endpoint_semantic_scope: str,
    idempotency_key: str,
    canonical_request_hash: str,
    lease_seconds: int = 30,
) -> tuple[dict[str, Any] | None, str]:
    """Acquire a lease or retrieve existing record for the given idempotency identity.

    Returns (record, action) where action is one of:
      - "NEW": freshly inserted lease; caller proceeds with side-effect execution.
      - "SUCCEEDED": completed record available; caller returns cached response.
      - "RESUME": expired lease or recoverable failure; caller resumes using durable
        command_id/resource_id.
    """
    now = datetime.now(UTC)
    locked_until = now + timedelta(seconds=lease_seconds)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO idempotency_records (
                operator_identity, endpoint_semantic_scope, idempotency_key,
                canonical_request_hash, status, created_at, locked_until
            ) VALUES (%s, %s, %s, %s, 'IN_PROGRESS', %s, %s)
            ON CONFLICT (operator_identity, endpoint_semantic_scope, idempotency_key)
            DO NOTHING
            RETURNING *
            """,
            (
                operator_identity,
                endpoint_semantic_scope,
                idempotency_key,
                canonical_request_hash,
                now,
                locked_until,
            ),
        )
        inserted = cur.fetchone()
        if inserted is not None:
            return None, "NEW"

        cur.execute(
            """
            SELECT * FROM idempotency_records
            WHERE operator_identity = %s
              AND endpoint_semantic_scope = %s
              AND idempotency_key = %s
            FOR UPDATE
            """,
            (operator_identity, endpoint_semantic_scope, idempotency_key),
        )
        record = cur.fetchone()

        if record is None:
            raise RuntimeError("Idempotency record disappeared after conflict resolution.")

        # Record exists — verify request identity
        if record["canonical_request_hash"] != canonical_request_hash:
            raise IdempotencyConflictError()

        status = record["status"]
        if status == "SUCCEEDED":
            return dict(record), "SUCCEEDED"

        if status == "IN_PROGRESS":
            if record["locked_until"] > now:
                raise RequestInProgressError()
            # Lease expired — reclaim lease
            cur.execute(
                """
                UPDATE idempotency_records
                SET locked_until = %s
                WHERE operator_identity = %s
                  AND endpoint_semantic_scope = %s
                  AND idempotency_key = %s
                RETURNING *
                """,
                (locked_until, operator_identity, endpoint_semantic_scope, idempotency_key),
            )
            updated = cur.fetchone()
            return dict(updated or record), "RESUME"

        # status in ('DISPATCH_FAILED', 'FAILED')
        cur.execute(
            """
            UPDATE idempotency_records
            SET status = 'IN_PROGRESS', locked_until = %s
            WHERE operator_identity = %s
              AND endpoint_semantic_scope = %s
              AND idempotency_key = %s
            RETURNING *
            """,
            (locked_until, operator_identity, endpoint_semantic_scope, idempotency_key),
        )
        updated = cur.fetchone()
        return dict(updated or record), "RESUME"


def complete_record(
    conn: psycopg.Connection,
    *,
    operator_identity: str = "default",
    endpoint_semantic_scope: str,
    idempotency_key: str,
    response_status_code: int,
    response_body: dict[str, Any],
    command_id: str | None = None,
    resource_id: str | None = None,
) -> dict[str, Any]:
    """Mark idempotency record as SUCCEEDED with durable response payload."""
    now = datetime.now(UTC)
    body_json = json.dumps(response_body, ensure_ascii=False)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE idempotency_records
            SET status = 'SUCCEEDED',
                response_status_code = %s,
                response_body_jsonb = %s::jsonb,
                completed_at = %s,
                command_id = COALESCE(%s::uuid, command_id),
                resource_id = COALESCE(%s, resource_id)
            WHERE operator_identity = %s
              AND endpoint_semantic_scope = %s
              AND idempotency_key = %s
            RETURNING *
            """,
            (
                response_status_code,
                body_json,
                now,
                command_id,
                resource_id,
                operator_identity,
                endpoint_semantic_scope,
                idempotency_key,
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {}


def record_dispatch_failure(
    conn: psycopg.Connection,
    *,
    operator_identity: str = "default",
    endpoint_semantic_scope: str,
    idempotency_key: str,
    command_id: str | None = None,
    resource_id: str | None = None,
) -> None:
    """Record that durable command was created but downstream dispatch failed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE idempotency_records
            SET status = 'DISPATCH_FAILED',
                command_id = COALESCE(%s::uuid, command_id),
                resource_id = COALESCE(%s, resource_id)
            WHERE operator_identity = %s
              AND endpoint_semantic_scope = %s
              AND idempotency_key = %s
            """,
            (
                command_id,
                resource_id,
                operator_identity,
                endpoint_semantic_scope,
                idempotency_key,
            ),
        )


def record_failure(
    conn: psycopg.Connection,
    *,
    operator_identity: str = "default",
    endpoint_semantic_scope: str,
    idempotency_key: str,
) -> None:
    """Record execution failure prior to durable identity creation."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE idempotency_records
            SET status = 'FAILED'
            WHERE operator_identity = %s
              AND endpoint_semantic_scope = %s
              AND idempotency_key = %s
            """,
            (operator_identity, endpoint_semantic_scope, idempotency_key),
        )
