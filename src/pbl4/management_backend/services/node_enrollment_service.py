"""Node Enrollment Service — business logic for one-time code generation and node onboarding.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Responsibilities:
- Issue one-time enrollment codes with high CSPRNG entropy.
- Hash enrollment codes using SHA-256 before database persistence.
- Atomically consume enrollment codes via repository to prevent race conditions.
- Differentiate between expired and invalid/used codes for precise error reporting.
- Generate node_id and node_secret (secrets.token_urlsafe(32)).
- Hash node_secret using SHA-256 before storage as credential_hash.
- Return plaintext node_secret exactly once upon successful enrollment.
- Initialize newly enrolled nodes strictly in 'OFFLINE' state (never 'ONLINE').
- Zero plaintext credential logging.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import logging
import secrets
from typing import Any
import uuid

import psycopg

from pbl4.management_backend.repositories import (
    node_enrollment_repository,
    node_repository,
)

logger = logging.getLogger(__name__)


# ─── Service Exceptions ───────────────────────────────────────────────────────

class NodeEnrollmentError(Exception):
    """Base exception for node enrollment errors."""

    code: str = "NODE_ENROLLMENT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NodeEnrollmentCodeInvalidError(NodeEnrollmentError):
    """Raised when an enrollment code does not exist or has already been consumed."""

    code: str = "NODE_ENROLLMENT_CODE_INVALID"


class NodeEnrollmentCodeExpiredError(NodeEnrollmentError):
    """Raised when an enrollment code has passed its expiration timestamp."""

    code: str = "NODE_ENROLLMENT_CODE_EXPIRED"


# ─── Service Implementation ───────────────────────────────────────────────────

def hash_secret(secret: str) -> str:
    """Compute standard SHA-256 hex digest of a secret string."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class NodeEnrollmentService:
    """Domain service managing node onboarding lifecycle and one-time enrollment codes."""

    @staticmethod
    def create_enrollment_code(
        conn: psycopg.Connection,
        *,
        ttl_seconds: int = 3600,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Generate and persist a one-time enrollment code.

        Returns a dictionary containing the plaintext enrollment_code (returned to caller once),
        code_hash, created_at, and expires_at. Plaintext code is never logged or stored in DB.
        """
        current_time = now or datetime.now(UTC)
        expires_at = current_time + timedelta(seconds=ttl_seconds)

        # High-entropy CSPRNG token
        raw_code = secrets.token_urlsafe(32)
        code_hash = hash_secret(raw_code)

        row = node_enrollment_repository.create_enrollment_code(
            conn,
            code_hash=code_hash,
            created_at=current_time,
            expires_at=expires_at,
        )

        logger.info("Created node enrollment code hash=%s expires_at=%s", code_hash[:8] + "...", expires_at)
        return {
            "enrollment_code": raw_code,
            "code_hash": code_hash,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    @staticmethod
    def enroll_node(
        conn: psycopg.Connection,
        *,
        enrollment_code: str,
        capabilities: dict[str, Any] | None = None,
        display_name: str | None = None,
        agent_version: str | None = None,
        platform: str | None = None,
        node_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically validate enrollment code, consume it, and create a new node.

        Returns plaintext node_secret exactly once. Newly created node starts at OFFLINE.
        """
        if not isinstance(enrollment_code, str) or not enrollment_code.strip():
            raise NodeEnrollmentCodeInvalidError("Enrollment code must be a non-empty string.")

        current_time = now or datetime.now(UTC)
        code_hash = hash_secret(enrollment_code.strip())

        # Atomically consume the code
        consumed = node_enrollment_repository.consume_code_if_valid(
            conn,
            code_hash=code_hash,
            now=current_time,
        )

        if consumed is None:
            # Distinguish reason for consumption failure
            existing = node_enrollment_repository.get_enrollment_code(conn, code_hash)
            if existing is None:
                raise NodeEnrollmentCodeInvalidError("Enrollment code is invalid.")
            if existing.get("used_at") is not None:
                raise NodeEnrollmentCodeInvalidError("Enrollment code has already been used.")
            if existing.get("expires_at") and existing["expires_at"] <= current_time:
                raise NodeEnrollmentCodeExpiredError("Enrollment code has expired.")
            raise NodeEnrollmentCodeInvalidError("Enrollment code could not be consumed.")

        # Generate node credentials
        chosen_node_id = node_id or f"node-{uuid.uuid4().hex[:12]}"
        node_secret = secrets.token_urlsafe(32)
        credential_hash = hash_secret(node_secret)

        caps = capabilities or {}
        resolved_display_name = display_name or caps.get("hostname") or f"Node-{chosen_node_id[-6:]}"

        # Insert new node record with INITIAL STATE OFFLINE
        node = node_repository.create_node(
            conn,
            node_id=chosen_node_id,
            display_name=resolved_display_name,
            credential_hash=credential_hash,
            credential_created_at=current_time,
            capabilities_jsonb=caps,
            enrolled_at=current_time,
            state=node_repository.NODE_STATE_OFFLINE,
            agent_version=agent_version,
            platform=platform,
        )

        logger.info(
            "Node '%s' enrolled successfully in state OFFLINE; credentials issued.",
            chosen_node_id,
        )

        return {
            "node_id": node.get("node_id", chosen_node_id),
            "node_secret": node_secret,
            "node": node,
        }


# Module-level convenience functions
create_enrollment_code = NodeEnrollmentService.create_enrollment_code
enroll_node = NodeEnrollmentService.enroll_node
