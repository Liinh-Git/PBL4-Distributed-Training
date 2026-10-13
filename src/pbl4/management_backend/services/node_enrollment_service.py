"""Node Enrollment Service — business logic for node onboarding.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Responsibilities:
- Open auto-enrollment for Node Agents.
- Generate node_id and node_secret (secrets.token_urlsafe(32)).
- Hash node_secret using SHA-256 before storage as credential_hash.
- Return plaintext node_secret exactly once upon successful enrollment.
- Initialize newly enrolled nodes strictly in 'OFFLINE' state (never 'ONLINE').
- Zero plaintext credential logging.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg

from pbl4.management_backend.repositories import node_repository

logger = logging.getLogger(__name__)


# ─── Service Exceptions ───────────────────────────────────────────────────────


class NodeEnrollmentError(Exception):
    """Base exception for node enrollment errors."""

    code: str = "NODE_ENROLLMENT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ─── Service Implementation ───────────────────────────────────────────────────


def hash_secret(secret: str) -> str:
    """Compute standard SHA-256 hex digest of a secret string."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class NodeEnrollmentService:
    """Domain service managing node onboarding lifecycle."""

    @staticmethod
    def enroll_node(
        conn: psycopg.Connection,
        *,
        capabilities: dict[str, Any] | None = None,
        display_name: str | None = None,
        agent_version: str | None = None,
        platform: str | None = None,
        node_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically onboard a node and issue credentials.

        Returns plaintext node_secret exactly once. Newly created node starts at OFFLINE.
        """
        current_time = now or datetime.now(UTC)

        # Generate node credentials
        chosen_node_id = node_id or f"node-{uuid.uuid4().hex[:12]}"
        node_secret = secrets.token_urlsafe(32)
        credential_hash = hash_secret(node_secret)

        caps = capabilities or {}
        resolved_display_name = (
            display_name or caps.get("hostname") or f"Node-{chosen_node_id[-6:]}"
        )

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
enroll_node = NodeEnrollmentService.enroll_node
