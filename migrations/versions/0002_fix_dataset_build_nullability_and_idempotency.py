"""Fix dataset build nullability and add idempotency records table.

Revision ID: 0002_fix_dataset_build_nullability_and_idempotency
Revises: 0001_initial_schema
Create Date: 2026-09-09 00:00:00.000000+00:00

CANONICAL REFERENCES:
- 03. Mô hình dữ liệu (Data model: physical schema, lifecycle invariants)
- 02. Mô hình miền (Dataset Build lifecycle: CREATED -> ... -> REGISTERING -> READY)
- 04. API Backend & Contracts (Idempotency-Key scoping and persistence)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_fix_dataset_build_nullability_and_idempotency"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── 1. Alter dataset_builds nullability for early lifecycle states ────
    # In CREATED, QUEUED, IMPORTING, VALIDATING, PREPROCESSING, MATERIALIZING, VERIFYING,
    # sample_count, manifest_uri, hash, and snapshot are not yet available.
    op.alter_column("dataset_builds", "manifest_uri", nullable=True)
    op.alter_column("dataset_builds", "dataset_manifest_hash", nullable=True)
    op.alter_column("dataset_builds", "manifest_snapshot_jsonb", nullable=True)
    op.alter_column("dataset_builds", "artifact_base_url", nullable=True)
    op.alter_column("dataset_builds", "sample_count", nullable=True)

    # ─── 2. Lifecycle constraints for dataset_builds ───────────────────────
    # REGISTERING requires published manifest location and hash
    op.create_check_constraint(
        "ck_dataset_builds__registering_manifest",
        "dataset_builds",
        "(state NOT IN ('REGISTERING', 'READY')) OR ("
        "manifest_uri IS NOT NULL AND "
        "dataset_manifest_hash IS NOT NULL AND "
        "artifact_base_url IS NOT NULL)",
    )

    # READY requires full registration and catalog completeness
    op.create_check_constraint(
        "ck_dataset_builds__ready_complete",
        "dataset_builds",
        "(state <> 'READY') OR ("
        "manifest_uri IS NOT NULL AND "
        "dataset_manifest_hash IS NOT NULL AND "
        "manifest_snapshot_jsonb IS NOT NULL AND "
        "artifact_base_url IS NOT NULL AND "
        "sample_count IS NOT NULL AND "
        "ready_at IS NOT NULL)",
    )

    # ─── 3. Durable HTTP Idempotency Records Table ─────────────────────────
    op.create_table(
        "idempotency_records",
        sa.Column(
            "operator_identity",
            sa.Text(),
            nullable=False,
            server_default="default",
        ),
        sa.Column("endpoint_semantic_scope", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("canonical_request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "command_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column(
            "response_body_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("locked_until", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "operator_identity",
            "endpoint_semantic_scope",
            "idempotency_key",
            name="pk_idempotency_records",
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'SUCCEEDED', 'DISPATCH_FAILED', 'FAILED')",
            name="ck_idempotency_records__status",
        ),
    )
    op.create_index(
        "ix_idempotency_records__created_at",
        "idempotency_records",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_records__created_at",
        table_name="idempotency_records",
    )
    op.drop_table("idempotency_records")

    op.drop_constraint(
        "ck_dataset_builds__ready_complete",
        "dataset_builds",
        type_="check",
    )
    op.drop_constraint(
        "ck_dataset_builds__registering_manifest",
        "dataset_builds",
        type_="check",
    )

    op.alter_column("dataset_builds", "sample_count", nullable=False)
    op.alter_column("dataset_builds", "artifact_base_url", nullable=False)
    op.alter_column("dataset_builds", "manifest_snapshot_jsonb", nullable=False)
    op.alter_column("dataset_builds", "dataset_manifest_hash", nullable=False)
    op.alter_column("dataset_builds", "manifest_uri", nullable=False)
