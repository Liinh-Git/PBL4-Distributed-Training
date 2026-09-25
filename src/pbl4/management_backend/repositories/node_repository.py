"""Node repository — PostgreSQL data access for nodes table.

Enforces:
- Newly enrolled nodes initialize with state='OFFLINE'.
- Node states V1 are strictly: ONLINE, OFFLINE, REVOKED.
- Repository is pure SQL persistence; business and auth policies live in service layer.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

NODE_STATE_ONLINE = "ONLINE"
NODE_STATE_OFFLINE = "OFFLINE"
NODE_STATE_REVOKED = "REVOKED"

VALID_NODE_STATES = {NODE_STATE_ONLINE, NODE_STATE_OFFLINE, NODE_STATE_REVOKED}


def _row_to_dict(row: dict) -> dict:
    return dict(row)


def create_node(
    conn: psycopg.Connection,
    *,
    node_id: str,
    display_name: str,
    credential_hash: str,
    credential_created_at: datetime,
    capabilities_jsonb: dict[str, Any] | str,
    enrolled_at: datetime,
    state: str = NODE_STATE_OFFLINE,
    agent_version: str | None = None,
    platform: str | None = None,
) -> dict:
    """Insert a newly enrolled node. Defaults to state='OFFLINE'."""
    if state not in VALID_NODE_STATES:
        raise ValueError(f"Invalid node state '{state}', must be one of {VALID_NODE_STATES}")

    caps_str = (
        capabilities_jsonb
        if isinstance(capabilities_jsonb, str)
        else json.dumps(capabilities_jsonb)
    )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO nodes (
                node_id, display_name, credential_hash, credential_created_at,
                capabilities_jsonb, enrolled_at, state, agent_version, platform
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                node_id,
                display_name,
                credential_hash,
                credential_created_at,
                caps_str,
                enrolled_at,
                state,
                agent_version,
                platform,
            ),
        )
        row = cur.fetchone()
    return _row_to_dict(row)


def get_node(conn: psycopg.Connection, node_id: str) -> dict | None:
    """Retrieve a node by its node_id."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM nodes WHERE node_id = %s", (node_id,))
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_nodes(
    conn: psycopg.Connection,
    *,
    state: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List nodes with optional state filtering."""
    query = "SELECT * FROM nodes"
    params: list[Any] = []

    if state:
        if state not in VALID_NODE_STATES:
            raise ValueError(f"Invalid state filter '{state}'")
        query += " WHERE state = %s"
        params.append(state)

    query += " ORDER BY enrolled_at DESC LIMIT %s"
    params.append(limit)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def update_heartbeat(
    conn: psycopg.Connection,
    node_id: str,
    last_seen_at: datetime,
) -> dict | None:
    """Update last_seen_at timestamp for a node."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE nodes
            SET last_seen_at = %s
            WHERE node_id = %s
            RETURNING *
            """,
            (last_seen_at, node_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_resources(
    conn: psycopg.Connection,
    node_id: str,
    latest_resources_jsonb: dict[str, Any] | str,
) -> dict | None:
    """Update the latest resource snapshot telemetry for a node."""
    res_str = (
        latest_resources_jsonb
        if isinstance(latest_resources_jsonb, str)
        else json.dumps(latest_resources_jsonb)
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE nodes
            SET latest_resources_jsonb = %s::jsonb
            WHERE node_id = %s
            RETURNING *
            """,
            (res_str, node_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def update_state(
    conn: psycopg.Connection,
    node_id: str,
    state: str,
) -> dict | None:
    """Update node state (ONLINE, OFFLINE, REVOKED)."""
    if state not in VALID_NODE_STATES:
        raise ValueError(f"Invalid state '{state}', must be one of {VALID_NODE_STATES}")

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE nodes
            SET state = %s
            WHERE node_id = %s
            RETURNING *
            """,
            (state, node_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def revoke_node(
    conn: psycopg.Connection,
    node_id: str,
    credential_revoked_at: datetime,
) -> dict | None:
    """Mark a node as REVOKED and timestamp credential revocation."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE nodes
            SET state = %s,
                credential_revoked_at = %s
            WHERE node_id = %s
            RETURNING *
            """,
            (NODE_STATE_REVOKED, credential_revoked_at, node_id),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None
