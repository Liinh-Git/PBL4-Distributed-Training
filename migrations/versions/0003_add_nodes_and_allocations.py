"""Add node enrollment codes, nodes, worker allocations, and extend worker sessions.

Revision ID: 0003_add_nodes_and_allocations
Revises: 0002_fix_dsb_null_and_idemp
Create Date: 2026-09-24 00:00:00.000000+00:00

CANONICAL REFERENCES:
- docs/NODE_AGENT_IMPLEMENTATION_PLAN.md Section 4.4 (Backend Persistence)
- AGENTS.md Rule 16 (Node Agent is control plane, never training data plane)
- Execution Blueprint Phase 4 (Backend Persistence, Schema Migration 0003 & Repositories)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_add_nodes_and_allocations"
down_revision: str | None = "0002_fix_dsb_null_and_idemp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── 1. Table: node_enrollment_codes ──────────────────────────────────
    op.create_table(
        "node_enrollment_codes",
        sa.Column("code_hash", sa.CHAR(length=64), primary_key=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_node_enrollment_codes__expiry",
        ),
    )

    # ─── 2. Table: nodes ──────────────────────────────────────────────────
    op.create_table(
        "nodes",
        sa.Column("node_id", sa.Text(), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("credential_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("credential_created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("credential_revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("agent_version", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column(
            "capabilities_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "latest_resources_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("enrolled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('ONLINE', 'OFFLINE', 'REVOKED')",
            name="ck_nodes__state",
        ),
    )
    op.create_index("idx_nodes__state", "nodes", ["state"])

    # ─── 3. Table: worker_allocations ─────────────────────────────────────
    op.create_table(
        "worker_allocations",
        sa.Column("allocation_id", sa.Text(), primary_key=True),
        sa.Column(
            "attempt_id",
            sa.Text(),
            sa.ForeignKey("attempts.attempt_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Text(),
            sa.ForeignKey("nodes.node_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("desired_state", sa.Text(), nullable=False),
        sa.Column("actual_state", sa.Text(), nullable=False),
        sa.Column("device", sa.Text(), nullable=False),
        sa.Column(
            "resource_allocation_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("runtime_endpoint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "desired_state IN ('RUNNING', 'STOPPED')",
            name="ck_worker_allocations__desired_state",
        ),
        sa.CheckConstraint(
            "actual_state IN ('REQUESTED', 'DISPATCHED', 'STARTED', 'ENDED', 'FAILED')",
            name="ck_worker_allocations__actual_state",
        ),
    )
    op.create_index(
        "idx_worker_allocations__attempt_id",
        "worker_allocations",
        ["attempt_id"],
    )
    op.create_index(
        "idx_worker_allocations__node_id",
        "worker_allocations",
        ["node_id"],
    )

    # Partial unique index: at most one active worker allocation per node
    op.create_index(
        "uq_worker_allocations__one_active_per_node",
        "worker_allocations",
        ["node_id"],
        unique=True,
        postgresql_where=sa.text("actual_state IN ('REQUESTED', 'DISPATCHED', 'STARTED')"),
    )

    # ─── 4. Extend worker_sessions with nullable node_id and allocation_id ───
    op.add_column("worker_sessions", sa.Column("node_id", sa.Text(), nullable=True))
    op.add_column("worker_sessions", sa.Column("allocation_id", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_worker_sessions__node_id",
        "worker_sessions",
        "nodes",
        ["node_id"],
        ["node_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_worker_sessions__allocation_id",
        "worker_sessions",
        "worker_allocations",
        ["allocation_id"],
        ["allocation_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_worker_sessions__node_id", "worker_sessions", ["node_id"])
    op.create_index("idx_worker_sessions__allocation_id", "worker_sessions", ["allocation_id"])


def downgrade() -> None:
    # ─── 4. Revert worker_sessions additions ──────────────────────────────
    op.drop_index("idx_worker_sessions__allocation_id", table_name="worker_sessions")
    op.drop_index("idx_worker_sessions__node_id", table_name="worker_sessions")
    op.drop_constraint("fk_worker_sessions__allocation_id", "worker_sessions", type_="foreignkey")
    op.drop_constraint("fk_worker_sessions__node_id", "worker_sessions", type_="foreignkey")
    op.drop_column("worker_sessions", "allocation_id")
    op.drop_column("worker_sessions", "node_id")

    # ─── 3. Drop worker_allocations ───────────────────────────────────────
    op.drop_index("uq_worker_allocations__one_active_per_node", table_name="worker_allocations")
    op.drop_index("idx_worker_allocations__node_id", table_name="worker_allocations")
    op.drop_index("idx_worker_allocations__attempt_id", table_name="worker_allocations")
    op.drop_table("worker_allocations")

    # ─── 2. Drop nodes ────────────────────────────────────────────────────
    op.drop_index("idx_nodes__state", table_name="nodes")
    op.drop_table("nodes")

    # ─── 1. Drop node_enrollment_codes ────────────────────────────────────
    op.drop_table("node_enrollment_codes")
