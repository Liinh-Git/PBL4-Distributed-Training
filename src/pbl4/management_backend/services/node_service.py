"""Node Service — domain logic for Node authentication, heartbeat, liveness, and revocation.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Lifecycle rules:
1. Node after enrollment -> OFFLINE.
2. Valid control plane connect / heartbeat -> ONLINE.
3. Stale ONLINE (> node_heartbeat_timeout_seconds) -> OFFLINE.
4. Revoke ONLINE or OFFLINE -> REVOKED.
5. REVOKED is strictly terminal: REVOKED -> ONLINE is impossible.
6. Revoked node authentication is strictly rejected (NODE_REVOKED).
7. Revoked node heartbeat is strictly rejected (NODE_REVOKED).

Critical boundary:
- ONLINE/OFFLINE only reflects control-plane liveness.
- NodeService MUST NOT create WorkerAllocations, STOP Workers, ABORT Attempts,
  release allocations, or modify Attempt lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import logging
from typing import Any

import psycopg

from pbl4.management_backend.repositories import node_repository

logger = logging.getLogger(__name__)


# ─── Service Exceptions ───────────────────────────────────────────────────────

class NodeServiceError(Exception):
    """Base exception for node service domain errors."""

    code: str = "NODE_SERVICE_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NodeNotFoundError(NodeServiceError):
    """Raised when the specified node does not exist."""

    code: str = "NODE_NOT_FOUND"


class NodeUnauthorizedError(NodeServiceError):
    """Raised when node authentication fails (invalid secret or unknown identity)."""

    code: str = "NODE_UNAUTHORIZED"


class NodeRevokedError(NodeServiceError):
    """Raised when attempting an operation on a REVOKED node."""

    code: str = "NODE_REVOKED"


class NodeOfflineError(NodeServiceError):
    """Raised when an operation requires an ONLINE node but the node is OFFLINE."""

    code: str = "NODE_OFFLINE"


# ─── Service Implementation ───────────────────────────────────────────────────

def hash_secret(secret: str) -> str:
    """Compute standard SHA-256 hex digest of a secret string."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class NodeService:
    """Domain service managing Node lifecycle, authentication, liveness, and revocation."""

    @staticmethod
    def get_node(conn: psycopg.Connection, node_id: str) -> dict[str, Any]:
        """Fetch node by node_id or raise NodeNotFoundError."""
        node = node_repository.get_node(conn, node_id)
        if node is None:
            raise NodeNotFoundError(f"Node '{node_id}' not found.")
        return node

    @staticmethod
    def list_nodes(
        conn: psycopg.Connection,
        *,
        state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List nodes with optional state filtering."""
        return node_repository.list_nodes(conn, state=state, limit=limit)

    @staticmethod
    def authenticate_node(
        conn: psycopg.Connection,
        node_id: str,
        node_secret: str,
    ) -> dict[str, Any]:
        """Authenticate a node by its node_id and plaintext node_secret.

        Guarantees:
        - If node does not exist -> NodeUnauthorizedError / NodeNotFoundError.
        - If node is REVOKED -> NodeRevokedError (authentication rejected).
        - Secret compared using constant-time HMAC digest.
        - Never returns secret or logs secret.
        """
        if not isinstance(node_id, str) or not node_id:
            raise NodeUnauthorizedError("node_id must be a non-empty string.")
        if not isinstance(node_secret, str) or not node_secret:
            raise NodeUnauthorizedError("node_secret must be a non-empty string.")

        node = node_repository.get_node(conn, node_id)
        if node is None:
            raise NodeUnauthorizedError(f"Node '{node_id}' does not exist.")

        # Revoked nodes must never be authenticated
        if node.get("state") == node_repository.NODE_STATE_REVOKED or node.get("credential_revoked_at") is not None:
            raise NodeRevokedError(f"Node '{node_id}' has been revoked.")

        actual_hash = hash_secret(node_secret)
        expected_hash = node.get("credential_hash", "")

        if not hmac.compare_digest(actual_hash, expected_hash):
            raise NodeUnauthorizedError(f"Invalid secret for node '{node_id}'.")

        return node

    @staticmethod
    def record_node_online(
        conn: psycopg.Connection,
        node_id: str,
        *,
        agent_version: str | None = None,
        platform: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Transition a valid node to ONLINE after successful control-plane connection.

        Strictly enforces:
        - REVOKED node can NEVER transition to ONLINE.
        """
        node = NodeService.get_node(conn, node_id)

        if node.get("state") == node_repository.NODE_STATE_REVOKED or node.get("credential_revoked_at") is not None:
            raise NodeRevokedError(f"Node '{node_id}' is revoked and cannot be brought ONLINE.")

        current_time = now or datetime.now(UTC)
        updated = node_repository.update_state(conn, node_id, node_repository.NODE_STATE_ONLINE)
        node_repository.update_heartbeat(conn, node_id, current_time)

        # Update metadata if provided
        if agent_version or platform:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE nodes
                    SET agent_version = COALESCE(%s, agent_version),
                        platform = COALESCE(%s, platform)
                    WHERE node_id = %s
                    """,
                    (agent_version, platform, node_id),
                )

        logger.info("Node '%s' transitioned to ONLINE at %s", node_id, current_time)
        return NodeService.get_node(conn, node_id)

    @staticmethod
    def record_heartbeat(
        conn: psycopg.Connection,
        node_id: str,
        *,
        last_seen_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Record a control-plane heartbeat from an active node.

        Strictly enforces:
        - Heartbeats from REVOKED nodes are rejected with NodeRevokedError.
        - Valid heartbeats update last_seen_at and ensure state is ONLINE.
        """
        node = NodeService.get_node(conn, node_id)

        if node.get("state") == node_repository.NODE_STATE_REVOKED or node.get("credential_revoked_at") is not None:
            raise NodeRevokedError(f"Heartbeat rejected: Node '{node_id}' is revoked.")

        current_time = last_seen_at or datetime.now(UTC)

        # If node was OFFLINE, heartbeat brings it back ONLINE
        if node.get("state") == node_repository.NODE_STATE_OFFLINE:
            node_repository.update_state(conn, node_id, node_repository.NODE_STATE_ONLINE)

        updated = node_repository.update_heartbeat(conn, node_id, current_time)
        return updated or node

    @staticmethod
    def record_resources(
        conn: psycopg.Connection,
        node_id: str,
        resources: dict[str, Any] | str,
    ) -> dict[str, Any]:
        """Update latest resource telemetry snapshot for a node."""
        node = NodeService.get_node(conn, node_id)
        if node.get("state") == node_repository.NODE_STATE_REVOKED:
            raise NodeRevokedError(f"Resource report rejected: Node '{node_id}' is revoked.")

        updated = node_repository.update_resources(conn, node_id, resources)
        return updated or node

    @staticmethod
    def mark_stale_nodes(
        conn: psycopg.Connection,
        *,
        timeout_seconds: float,
        now: datetime | None = None,
    ) -> list[str]:
        """Transition ONLINE nodes whose last_seen_at exceeds timeout_seconds to OFFLINE.

        Strict invariants:
        - Only transitions ONLINE -> OFFLINE.
        - NEVER transitions REVOKED -> OFFLINE.
        - NEVER transitions REVOKED -> ONLINE.
        - Does NOT touch active allocations or training attempts.
        """
        current_time = now or datetime.now(UTC)
        online_nodes = node_repository.list_nodes(conn, state=node_repository.NODE_STATE_ONLINE, limit=1000)

        stale_node_ids: list[str] = []
        for node in online_nodes:
            last_seen = node.get("last_seen_at")
            if last_seen is None:
                is_stale = True
            else:
                is_stale = (current_time - last_seen).total_seconds() > timeout_seconds

            if is_stale:
                node_id = str(node["node_id"])
                node_repository.update_state(conn, node_id, node_repository.NODE_STATE_OFFLINE)
                stale_node_ids.append(node_id)
                logger.info("Marked stale node '%s' as OFFLINE (last_seen=%s)", node_id, last_seen)

        return stale_node_ids

    @staticmethod
    def revoke_node(
        conn: psycopg.Connection,
        node_id: str,
        *,
        now: datetime | None = None,
        gateway: Any | None = None,
    ) -> dict[str, Any]:
        """Revoke a node's credentials and mark its state as REVOKED.

        Guarantees:
        - Node state becomes REVOKED.
        - credential_revoked_at timestamp is set.
        - Node will fail any subsequent authentication or heartbeat.
        - Coordinates with gateway to close active WSS connection.
        - Does NOT modify Attempt lifecycle or create/release allocations.
        """
        node = NodeService.get_node(conn, node_id)
        if node.get("state") == node_repository.NODE_STATE_REVOKED:
            if gateway is not None:
                try:
                    gateway.close_node_connection(node_id)
                except Exception as exc:
                    logger.warning("Failed closing active WSS connection for revoked node '%s': %s", node_id, exc)
            return node

        current_time = now or datetime.now(UTC)
        updated = node_repository.revoke_node(conn, node_id, current_time)
        logger.warning("Node '%s' has been REVOKED at %s", node_id, current_time)

        if gateway is not None:
            try:
                gateway.close_node_connection(node_id)
            except Exception as exc:
                logger.warning("Failed closing active WSS connection for revoked node '%s': %s", node_id, exc)

        return updated or node


# Module-level convenience functions
get_node = NodeService.get_node
list_nodes = NodeService.list_nodes
authenticate_node = NodeService.authenticate_node
record_node_online = NodeService.record_node_online
record_heartbeat = NodeService.record_heartbeat
record_resources = NodeService.record_resources
mark_stale_nodes = NodeService.mark_stale_nodes
revoke_node = NodeService.revoke_node
