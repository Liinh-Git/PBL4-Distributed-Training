"""Initial PostgreSQL schema for PBL4 distributed training infrastructure.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-09-07 21:00:00.000000+00:00

CANONICAL SPECIFICATION REFERENCES:
- 03. Mô hình dữ liệu (Data model: physical schema, 12 business tables, types, PK/FK, invariants)
- 02. Mô hình miền (Domain model: Attempt, Job, Session, Checkpoint, Dataset lifecycle semantics)
- 01. PostgreSQL (Persistence policy: explicit SQL, off training critical path)
- 04. Cấu trúc mã nguồn (Migration tooling boundary)

12 CANONICAL BUSINESS TABLES:
1. datasets
2. dataset_builds
3. jobs
4. attempts (circular FK to checkpoints created after checkpoints table)
5. worker_sessions
6. worker_provisioning
7. steps
8. worker_steps
9. checkpoints
10. events
11. control_commands
12. metrics
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── 1. datasets ────────────────────────────────────────────────────────
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_datasets"),
    )

    # ─── 2. dataset_builds ──────────────────────────────────────────────────
    op.create_table(
        "dataset_builds",
        sa.Column("dataset_build_id", sa.Text(), nullable=False),
        sa.Column("dataset_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column(
            "input_shape_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("dtype", sa.Text(), nullable=False),
        sa.Column("num_classes", sa.Integer(), nullable=False),
        sa.Column(
            "preprocessing_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("shard_count", sa.Integer(), nullable=False),
        sa.Column("partition_seed", sa.BigInteger(), nullable=False),
        sa.Column("sample_count", sa.BigInteger(), nullable=False),
        sa.Column("batch_count_per_shard", sa.Integer(), nullable=True),
        sa.Column("manifest_uri", sa.Text(), nullable=False),
        sa.Column("dataset_manifest_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "manifest_snapshot_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("artifact_base_url", sa.Text(), nullable=False),
        sa.Column("registration_id", sa.Text(), nullable=True),
        sa.Column(
            "registration_acknowledged_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ready_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("dataset_build_id", name="pk_dataset_builds"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_dataset_builds__dataset_id__datasets",
        ),
        sa.CheckConstraint(
            "state IN ('CREATED', 'QUEUED', 'IMPORTING', 'VALIDATING', "
            "'PREPROCESSING', 'MATERIALIZING', 'VERIFYING', 'REGISTERING', "
            "'READY', 'FAILED', 'DEPRECATED', 'DELETING', 'DELETED')",
            name="ck_dataset_builds__state",
        ),
    )
    op.create_index(
        "ix_dataset_builds__dataset_id_state",
        "dataset_builds",
        ["dataset_id", "state"],
    )

    # ─── 3. jobs ────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "requested_contract",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "resolved_contract",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("contract_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("cloned_from_job_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("job_id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["cloned_from_job_id"],
            ["jobs.job_id"],
            name="fk_jobs__cloned_from_job_id__jobs",
        ),
        sa.CheckConstraint(
            "state IN ('DRAFT', 'READY', 'ARCHIVED')",
            name="ck_jobs__state",
        ),
        sa.CheckConstraint(
            "(state <> 'READY') OR (resolved_contract IS NOT NULL AND "
            "contract_hash IS NOT NULL AND frozen_at IS NOT NULL)",
            name="ck_jobs__ready_frozen_contract",
        ),
    )
    op.create_index(
        "ix_jobs__state_created_at",
        "jobs",
        ["state", "created_at"],
    )

    # ─── 4. attempts ────────────────────────────────────────────────────────
    op.create_table(
        "attempts",
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("contract_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("execution_mode", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("resume_from_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "runtime_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_attempts"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.job_id"],
            name="fk_attempts__job_id__jobs",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('FRESH', 'RETRY_FROM_START', 'RESUME')",
            name="ck_attempts__execution_mode",
        ),
        sa.CheckConstraint(
            "state IN ('CREATED', 'WAITING_WORKERS', 'PROVISIONING', "
            "'INITIALIZING', 'RUNNING', 'COMPLETING', 'COMPLETED', "
            "'FAILED', 'ABORTED')",
            name="ck_attempts__state",
        ),
        sa.CheckConstraint(
            "((execution_mode = 'RESUME' AND "
            "resume_from_checkpoint_id IS NOT NULL) OR "
            "(execution_mode IN ('FRESH', 'RETRY_FROM_START') AND "
            "resume_from_checkpoint_id IS NULL))",
            name="ck_attempts__resume_checkpoint",
        ),
    )
    # V1 invariant: at most one active attempt globally across the system
    op.create_index(
        "uq_attempts__one_active",
        "attempts",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('CREATED', 'WAITING_WORKERS', 'PROVISIONING', "
            "'INITIALIZING', 'RUNNING', 'COMPLETING')"
        ),
    )
    op.create_index(
        "ix_attempts__job_id_created_at",
        "attempts",
        ["job_id", "created_at"],
    )

    # ─── 5. worker_sessions ─────────────────────────────────────────────────
    op.create_table(
        "worker_sessions",
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("node_label", sa.Text(), nullable=False),
        sa.Column("protocol_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("connected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "last_heartbeat_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "disconnected_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("session_id", name="pk_worker_sessions"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_worker_sessions__attempt_id__attempts",
        ),
        sa.CheckConstraint(
            "session_id > 0",
            name="ck_worker_sessions__session_id_positive",
        ),
        sa.CheckConstraint(
            "state IN ('CONNECTING', 'REGISTERING', 'PROVISIONING', "
            "'SHARD_READY', 'MODEL_SYNCING', 'READY', 'DISCONNECTED', 'FAILED')",
            name="ck_worker_sessions__state",
        ),
    )
    # V1 invariant: at most one active session per (attempt_id, worker_id) rank
    op.create_index(
        "uq_worker_sessions__active_rank",
        "worker_sessions",
        ["attempt_id", "worker_id"],
        unique=True,
        postgresql_where=sa.text("state NOT IN ('DISCONNECTED', 'FAILED')"),
    )

    # ─── 6. worker_provisioning ─────────────────────────────────────────────
    op.create_table(
        "worker_provisioning",
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("dataset_build_id", sa.Text(), nullable=False),
        sa.Column("shard_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("cache_reused", sa.Boolean(), nullable=False),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False),
        sa.Column("download_ms", sa.Double(), nullable=True),
        sa.Column("verify_ms", sa.Double(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "attempt_id",
            "worker_id",
            name="pk_worker_provisioning",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_worker_provisioning__attempt_id__attempts",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_build_id"],
            ["dataset_builds.dataset_build_id"],
            name="fk_worker_provisioning__dataset_build_id__dataset_builds",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'DOWNLOADING', 'VERIFYING', 'READY', 'FAILED')",
            name="ck_worker_provisioning__state",
        ),
    )

    # ─── 7. steps ───────────────────────────────────────────────────────────
    op.create_table(
        "steps",
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.BigInteger(), nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("training_strategy", sa.Text(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("batch_ordinal", sa.BigInteger(), nullable=False),
        sa.Column("input_model_version", sa.BigInteger(), nullable=False),
        sa.Column("output_model_version", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("total_sample_count", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "synchronization_completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "update_completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("committed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("aggregate_ms", sa.Double(), nullable=True),
        sa.Column("optimizer_ms", sa.Double(), nullable=True),
        sa.Column("broadcast_ms", sa.Double(), nullable=True),
        sa.Column("checkpoint_ms", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("attempt_id", "step_id", name="pk_steps"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_steps__attempt_id__attempts",
        ),
        sa.CheckConstraint(
            "state IN ('CREATED', 'DISPATCHED', 'COLLECTING_GRADIENTS', "
            "'AGGREGATING', 'UPDATING', 'BROADCASTING', "
            "'WAITING_PARAMETER_APPLIED', 'CHECKPOINTING', 'COMMITTED')",
            name="ck_steps__state",
        ),
    )

    # ─── 8. worker_steps ────────────────────────────────────────────────────
    op.create_table(
        "worker_steps",
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("shard_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("loss", sa.Double(), nullable=True),
        sa.Column("accuracy", sa.Double(), nullable=True),
        sa.Column("compute_ms", sa.Double(), nullable=False),
        sa.Column("upload_ms", sa.Double(), nullable=False),
        sa.Column("parameter_apply_ms", sa.Double(), nullable=False),
        sa.Column("bytes_sent", sa.BigInteger(), nullable=False),
        sa.Column("bytes_received", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "attempt_id",
            "step_id",
            "worker_id",
            name="pk_worker_steps",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_worker_steps__attempt_id__attempts",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "step_id"],
            ["steps.attempt_id", "steps.step_id"],
            name="fk_worker_steps__attempt_step__steps",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["worker_sessions.session_id"],
            name="fk_worker_steps__session_id__worker_sessions",
        ),
    )

    # ─── 9. checkpoints ─────────────────────────────────────────────────────
    op.create_table(
        "checkpoints",
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("created_by_attempt_id", sa.Text(), nullable=False),
        sa.Column("source_operation_id", sa.BigInteger(), nullable=False),
        sa.Column("source_step_id", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("model_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "recovery_cursor_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("epoch", sa.Integer(), nullable=True),
        sa.Column("next_batch_ordinal", sa.BigInteger(), nullable=True),
        sa.Column("contract_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("dataset_build_id", sa.Text(), nullable=True),
        sa.Column("dataset_manifest_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("parameter_manifest_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("checkpoint_policy", sa.Text(), nullable=False),
        sa.Column("checkpoint_policy_version", sa.Integer(), nullable=False),
        sa.Column("model_path", sa.Text(), nullable=True),
        sa.Column("metadata_path", sa.Text(), nullable=True),
        sa.Column("model_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("metadata_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("checkpoint_id", name="pk_checkpoints"),
        sa.ForeignKeyConstraint(
            ["created_by_attempt_id"],
            ["attempts.attempt_id"],
            name="fk_checkpoints__created_by_attempt_id__attempts",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_build_id"],
            ["dataset_builds.dataset_build_id"],
            name="fk_checkpoints__dataset_build_id__dataset_builds",
        ),
        sa.CheckConstraint(
            "state IN ('WRITING', 'COMPLETE', 'FAILED')",
            name="ck_checkpoints__state",
        ),
        sa.CheckConstraint(
            "(state <> 'COMPLETE') OR ("
            "contract_hash IS NOT NULL AND "
            "dataset_build_id IS NOT NULL AND "
            "dataset_manifest_hash IS NOT NULL AND "
            "parameter_manifest_hash IS NOT NULL AND "
            "model_path IS NOT NULL AND "
            "metadata_path IS NOT NULL AND "
            "model_sha256 IS NOT NULL AND "
            "metadata_sha256 IS NOT NULL AND "
            "completed_at IS NOT NULL)",
            name="ck_checkpoints__complete_requirements",
        ),
    )

    # ─── Circular FK: attempts.resume_from_checkpoint_id -> checkpoints ────
    op.create_foreign_key(
        "fk_attempts__resume_from_checkpoint_id__checkpoints",
        "attempts",
        "checkpoints",
        ["resume_from_checkpoint_id"],
        ["checkpoint_id"],
    )

    # ─── 10. events ─────────────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("attempt_id", sa.Text(), nullable=True),
        sa.Column("runtime_event_seq", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_component", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "payload_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_events"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_events__attempt_id__attempts",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')",
            name="ck_events__severity",
        ),
    )
    # Deduplication invariant: per-attempt sequence uniqueness
    op.create_index(
        "uq_events__attempt_runtime_seq",
        "events",
        ["attempt_id", "runtime_event_seq"],
        unique=True,
        postgresql_where=sa.text(
            "attempt_id IS NOT NULL AND runtime_event_seq IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_events__attempt_occurred_at",
        "events",
        ["attempt_id", "occurred_at"],
    )

    # ─── 11. control_commands ───────────────────────────────────────────────
    op.create_table(
        "control_commands",
        sa.Column(
            "command_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("command_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "request_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "requester_context_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "result_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("command_id", name="pk_control_commands"),
        sa.CheckConstraint(
            "command_type IN ('CREATE_DATASET_BUILD', 'REBUILD_DATASET_BUILD', "
            "'DELETE_DATASET_BUILD', 'START_ATTEMPT', 'ABORT_ATTEMPT', 'REQUEST_CHECKPOINT')",
            name="ck_control_commands__command_type",
        ),
        sa.CheckConstraint(
            "target_type IN ('DATASET_BUILD', 'ATTEMPT')",
            name="ck_control_commands__target_type",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING', 'ACCEPTED', 'DEFERRED', 'SUCCEEDED', 'REJECTED', 'FAILED')",
            name="ck_control_commands__state",
        ),
    )
    op.create_index(
        "ix_control_commands__state_requested_at",
        "control_commands",
        ["state", "requested_at"],
    )

    # ─── 12. metrics ────────────────────────────────────────────────────────
    op.create_table(
        "metrics",
        sa.Column(
            "metric_id",
            sa.BigInteger(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("operation_id", sa.BigInteger(), nullable=True),
        sa.Column("step_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column(
            "labels_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("metric_id", name="pk_metrics"),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.attempt_id"],
            name="fk_metrics__attempt_id__attempts",
        ),
    )
    op.create_index(
        "ix_metrics__attempt_id_observed_at",
        "metrics",
        ["attempt_id", "observed_at"],
    )


def downgrade() -> None:
    # ─── 1. Drop Circular FK attempts ↔ checkpoints ─────────────────────────
    op.drop_constraint(
        "fk_attempts__resume_from_checkpoint_id__checkpoints",
        "attempts",
        type_="foreignkey",
    )

    # ─── 2. Drop Secondary and Partial Indexes ──────────────────────────────
    op.drop_index(
        "ix_metrics__attempt_id_observed_at",
        table_name="metrics",
    )
    op.drop_index(
        "ix_control_commands__state_requested_at",
        table_name="control_commands",
    )
    op.drop_index(
        "ix_events__attempt_occurred_at",
        table_name="events",
    )
    op.drop_index(
        "uq_events__attempt_runtime_seq",
        table_name="events",
    )
    op.drop_index(
        "uq_worker_sessions__active_rank",
        table_name="worker_sessions",
    )
    op.drop_index(
        "ix_attempts__job_id_created_at",
        table_name="attempts",
    )
    op.drop_index(
        "uq_attempts__one_active",
        table_name="attempts",
    )
    op.drop_index(
        "ix_jobs__state_created_at",
        table_name="jobs",
    )
    op.drop_index(
        "ix_dataset_builds__dataset_id_state",
        table_name="dataset_builds",
    )

    # ─── 3. Drop Tables in Reverse Dependency Order ─────────────────────────
    op.drop_table("metrics")
    op.drop_table("control_commands")
    op.drop_table("events")
    op.drop_table("checkpoints")
    op.drop_table("worker_steps")
    op.drop_table("steps")
    op.drop_table("worker_provisioning")
    op.drop_table("worker_sessions")
    op.drop_table("attempts")
    op.drop_table("jobs")
    op.drop_table("dataset_builds")
    op.drop_table("datasets")
