-- Management Backend — Initial Schema Bootstrap
-- 
-- Derived from: context/0001_initial_schema.py (canonical schema reference)
-- 12 canonical business tables per specification.
--
-- This script is idempotent: it uses IF NOT EXISTS guards.
-- Run once against a fresh database to provision the schema.

-- ─── Extensions ────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

-- ─── 1. datasets ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id          TEXT        NOT NULL,
    name                TEXT        NOT NULL,
    task_type           TEXT        NOT NULL,
    source_type         TEXT        NOT NULL,
    source_reference    TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_datasets PRIMARY KEY (dataset_id)
);

-- ─── 2. dataset_builds ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dataset_builds (
    dataset_build_id                TEXT        NOT NULL,
    dataset_id                      TEXT        NOT NULL,
    state                           TEXT        NOT NULL,
    profile                         TEXT        NOT NULL,
    input_shape_json                JSONB       NOT NULL,
    dtype                           TEXT        NOT NULL,
    num_classes                     INTEGER     NOT NULL,
    preprocessing_json              JSONB       NOT NULL,
    batch_size                      INTEGER     NOT NULL,
    shard_count                     INTEGER     NOT NULL,
    partition_seed                  BIGINT      NOT NULL,
    sample_count                    BIGINT      NOT NULL,
    batch_count_per_shard           INTEGER,
    manifest_uri                    TEXT        NOT NULL DEFAULT '',
    dataset_manifest_hash           CHAR(64)    NOT NULL DEFAULT '',
    manifest_snapshot_jsonb         JSONB       NOT NULL DEFAULT '{}',
    artifact_base_url               TEXT        NOT NULL DEFAULT '',
    registration_id                 TEXT,
    registration_acknowledged_at    TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ NOT NULL,
    ready_at                        TIMESTAMPTZ,
    deprecated_at                   TIMESTAMPTZ,
    CONSTRAINT pk_dataset_builds PRIMARY KEY (dataset_build_id),
    CONSTRAINT fk_dataset_builds__dataset_id__datasets
        FOREIGN KEY (dataset_id) REFERENCES datasets (dataset_id),
    CONSTRAINT ck_dataset_builds__state CHECK (
        state IN (
            'CREATED', 'QUEUED', 'IMPORTING', 'VALIDATING',
            'PREPROCESSING', 'MATERIALIZING', 'VERIFYING', 'REGISTERING',
            'READY', 'FAILED', 'DEPRECATED', 'DELETING', 'DELETED'
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_dataset_builds__dataset_id_state
    ON dataset_builds (dataset_id, state);

-- ─── 3. jobs ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT        NOT NULL,
    display_name        TEXT        NOT NULL,
    description         TEXT        NOT NULL DEFAULT '',
    state               TEXT        NOT NULL,
    requested_contract  JSONB       NOT NULL,
    resolved_contract   JSONB,
    contract_hash       CHAR(64),
    cloned_from_job_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL,
    frozen_at           TIMESTAMPTZ,
    archived_at         TIMESTAMPTZ,
    CONSTRAINT pk_jobs PRIMARY KEY (job_id),
    CONSTRAINT fk_jobs__cloned_from_job_id__jobs
        FOREIGN KEY (cloned_from_job_id) REFERENCES jobs (job_id),
    CONSTRAINT ck_jobs__state CHECK (
        state IN ('DRAFT', 'READY', 'ARCHIVED')
    ),
    CONSTRAINT ck_jobs__ready_frozen_contract CHECK (
        (state <> 'READY') OR (
            resolved_contract IS NOT NULL
            AND contract_hash IS NOT NULL
            AND frozen_at IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS ix_jobs__state_created_at
    ON jobs (state, created_at);

-- ─── 4. attempts ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id                  TEXT        NOT NULL,
    job_id                      TEXT        NOT NULL,
    contract_hash               CHAR(64)    NOT NULL,
    execution_mode              TEXT        NOT NULL,
    state                       TEXT        NOT NULL,
    resume_from_checkpoint_id   TEXT,
    created_at                  TIMESTAMPTZ NOT NULL,
    started_at                  TIMESTAMPTZ,
    ended_at                    TIMESTAMPTZ,
    failure_code                TEXT,
    failure_message             TEXT,
    runtime_metadata            JSONB,
    CONSTRAINT pk_attempts PRIMARY KEY (attempt_id),
    CONSTRAINT fk_attempts__job_id__jobs
        FOREIGN KEY (job_id) REFERENCES jobs (job_id),
    CONSTRAINT ck_attempts__execution_mode CHECK (
        execution_mode IN ('FRESH', 'RETRY_FROM_START', 'RESUME')
    ),
    CONSTRAINT ck_attempts__state CHECK (
        state IN (
            'CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING',
            'RUNNING', 'COMPLETING', 'COMPLETED', 'FAILED', 'ABORTED'
        )
    ),
    CONSTRAINT ck_attempts__resume_checkpoint CHECK (
        (execution_mode = 'RESUME' AND resume_from_checkpoint_id IS NOT NULL)
        OR (execution_mode IN ('FRESH', 'RETRY_FROM_START') AND resume_from_checkpoint_id IS NULL)
    )
);

-- V1: at most one active attempt globally
CREATE UNIQUE INDEX IF NOT EXISTS uq_attempts__one_active
    ON attempts ((1))
    WHERE state IN ('CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING', 'RUNNING', 'COMPLETING');

CREATE INDEX IF NOT EXISTS ix_attempts__job_id_created_at
    ON attempts (job_id, created_at);

-- ─── 5. worker_sessions ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worker_sessions (
    session_id          BIGINT      NOT NULL,
    attempt_id          TEXT        NOT NULL,
    worker_id           INTEGER     NOT NULL,
    node_label          TEXT        NOT NULL,
    protocol_version    INTEGER     NOT NULL,
    state               TEXT        NOT NULL,
    connected_at        TIMESTAMPTZ NOT NULL,
    last_heartbeat_at   TIMESTAMPTZ,
    disconnected_at     TIMESTAMPTZ,
    failure_code        TEXT,
    CONSTRAINT pk_worker_sessions PRIMARY KEY (session_id),
    CONSTRAINT fk_worker_sessions__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT ck_worker_sessions__session_id_positive CHECK (session_id > 0),
    CONSTRAINT ck_worker_sessions__state CHECK (
        state IN (
            'CONNECTING', 'REGISTERING', 'PROVISIONING', 'SHARD_READY',
            'MODEL_SYNCING', 'READY', 'DISCONNECTED', 'FAILED'
        )
    )
);

-- V1: at most one active session per (attempt_id, worker_id) rank
CREATE UNIQUE INDEX IF NOT EXISTS uq_worker_sessions__active_rank
    ON worker_sessions (attempt_id, worker_id)
    WHERE state NOT IN ('DISCONNECTED', 'FAILED');

-- ─── 6. worker_provisioning ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worker_provisioning (
    attempt_id          TEXT        NOT NULL,
    worker_id           INTEGER     NOT NULL,
    dataset_build_id    TEXT        NOT NULL,
    shard_id            INTEGER     NOT NULL,
    state               TEXT        NOT NULL,
    cache_reused        BOOLEAN     NOT NULL DEFAULT FALSE,
    bytes_downloaded    BIGINT      NOT NULL DEFAULT 0,
    download_ms         DOUBLE PRECISION,
    verify_ms           DOUBLE PRECISION,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    CONSTRAINT pk_worker_provisioning PRIMARY KEY (attempt_id, worker_id),
    CONSTRAINT fk_worker_provisioning__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT fk_worker_provisioning__dataset_build_id__dataset_builds
        FOREIGN KEY (dataset_build_id) REFERENCES dataset_builds (dataset_build_id),
    CONSTRAINT ck_worker_provisioning__state CHECK (
        state IN ('PENDING', 'DOWNLOADING', 'VERIFYING', 'READY', 'FAILED')
    )
);

-- ─── 7. steps ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS steps (
    attempt_id                  TEXT            NOT NULL,
    step_id                     BIGINT          NOT NULL,
    operation_id                BIGINT          NOT NULL,
    training_strategy           TEXT            NOT NULL,
    epoch                       INTEGER         NOT NULL,
    batch_ordinal               BIGINT          NOT NULL,
    input_model_version         BIGINT          NOT NULL,
    output_model_version        BIGINT,
    state                       TEXT            NOT NULL,
    total_sample_count          BIGINT,
    started_at                  TIMESTAMPTZ     NOT NULL,
    synchronization_completed_at TIMESTAMPTZ,
    update_completed_at         TIMESTAMPTZ,
    committed_at                TIMESTAMPTZ,
    aggregate_ms                DOUBLE PRECISION,
    optimizer_ms                DOUBLE PRECISION,
    broadcast_ms                DOUBLE PRECISION,
    checkpoint_ms               DOUBLE PRECISION,
    CONSTRAINT pk_steps PRIMARY KEY (attempt_id, step_id),
    CONSTRAINT fk_steps__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT ck_steps__state CHECK (
        state IN (
            'CREATED', 'DISPATCHED', 'COLLECTING_GRADIENTS', 'AGGREGATING',
            'UPDATING', 'BROADCASTING', 'WAITING_PARAMETER_APPLIED',
            'CHECKPOINTING', 'COMMITTED'
        )
    )
);

-- ─── 8. worker_steps ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS worker_steps (
    attempt_id          TEXT            NOT NULL,
    step_id             BIGINT          NOT NULL,
    worker_id           INTEGER         NOT NULL,
    session_id          BIGINT          NOT NULL,
    shard_id            INTEGER         NOT NULL,
    batch_id            BIGINT          NOT NULL,
    sample_count        INTEGER         NOT NULL,
    loss                DOUBLE PRECISION,
    accuracy            DOUBLE PRECISION,
    compute_ms          DOUBLE PRECISION NOT NULL DEFAULT 0,
    upload_ms           DOUBLE PRECISION NOT NULL DEFAULT 0,
    parameter_apply_ms  DOUBLE PRECISION NOT NULL DEFAULT 0,
    bytes_sent          BIGINT          NOT NULL DEFAULT 0,
    bytes_received      BIGINT          NOT NULL DEFAULT 0,
    CONSTRAINT pk_worker_steps PRIMARY KEY (attempt_id, step_id, worker_id),
    CONSTRAINT fk_worker_steps__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT fk_worker_steps__attempt_step__steps
        FOREIGN KEY (attempt_id, step_id) REFERENCES steps (attempt_id, step_id),
    CONSTRAINT fk_worker_steps__session_id__worker_sessions
        FOREIGN KEY (session_id) REFERENCES worker_sessions (session_id)
);

-- ─── 9. checkpoints ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id               TEXT            NOT NULL,
    created_by_attempt_id       TEXT            NOT NULL,
    source_operation_id         BIGINT          NOT NULL,
    source_step_id              BIGINT,
    state                       TEXT            NOT NULL,
    model_version               BIGINT          NOT NULL,
    recovery_cursor_jsonb       JSONB           NOT NULL DEFAULT '{}',
    epoch                       INTEGER,
    next_batch_ordinal          BIGINT,
    contract_hash               CHAR(64),
    dataset_build_id            TEXT,
    dataset_manifest_hash       CHAR(64),
    parameter_manifest_hash     CHAR(64),
    checkpoint_policy           TEXT            NOT NULL,
    checkpoint_policy_version   INTEGER         NOT NULL,
    model_path                  TEXT,
    metadata_path               TEXT,
    model_sha256                CHAR(64),
    metadata_sha256             CHAR(64),
    artifact_size_bytes         BIGINT,
    created_at                  TIMESTAMPTZ     NOT NULL,
    completed_at                TIMESTAMPTZ,
    CONSTRAINT pk_checkpoints PRIMARY KEY (checkpoint_id),
    CONSTRAINT fk_checkpoints__created_by_attempt_id__attempts
        FOREIGN KEY (created_by_attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT fk_checkpoints__dataset_build_id__dataset_builds
        FOREIGN KEY (dataset_build_id) REFERENCES dataset_builds (dataset_build_id),
    CONSTRAINT ck_checkpoints__state CHECK (
        state IN ('WRITING', 'COMPLETE', 'FAILED')
    ),
    CONSTRAINT ck_checkpoints__complete_requirements CHECK (
        (state <> 'COMPLETE') OR (
            contract_hash IS NOT NULL
            AND dataset_build_id IS NOT NULL
            AND dataset_manifest_hash IS NOT NULL
            AND parameter_manifest_hash IS NOT NULL
            AND model_path IS NOT NULL
            AND metadata_path IS NOT NULL
            AND model_sha256 IS NOT NULL
            AND metadata_sha256 IS NOT NULL
            AND completed_at IS NOT NULL
        )
    )
);

-- ─── Circular FK: attempts.resume_from_checkpoint_id → checkpoints ──────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_attempts__resume_from_checkpoint_id__checkpoints'
    ) THEN
        ALTER TABLE attempts
            ADD CONSTRAINT fk_attempts__resume_from_checkpoint_id__checkpoints
            FOREIGN KEY (resume_from_checkpoint_id)
            REFERENCES checkpoints (checkpoint_id);
    END IF;
END $$;

-- ─── 10. events ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    event_id            BIGSERIAL       NOT NULL,
    attempt_id          TEXT,
    runtime_event_seq   BIGINT,
    event_type          TEXT            NOT NULL,
    source_component    TEXT            NOT NULL DEFAULT 'Management',
    scope_type          TEXT            NOT NULL,
    scope_id            TEXT,
    severity            TEXT            NOT NULL,
    payload_jsonb       JSONB           NOT NULL DEFAULT '{}',
    occurred_at         TIMESTAMPTZ     NOT NULL,
    persisted_at        TIMESTAMPTZ     NOT NULL,
    CONSTRAINT pk_events PRIMARY KEY (event_id),
    CONSTRAINT fk_events__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id),
    CONSTRAINT ck_events__severity CHECK (
        severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')
    )
);

-- Deduplication: per-attempt sequence uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS uq_events__attempt_runtime_seq
    ON events (attempt_id, runtime_event_seq)
    WHERE attempt_id IS NOT NULL AND runtime_event_seq IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_events__attempt_occurred_at
    ON events (attempt_id, occurred_at);

CREATE INDEX IF NOT EXISTS ix_events__scope_type_id
    ON events (scope_type, scope_id);

-- ─── 11. control_commands ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS control_commands (
    command_id              UUID            NOT NULL,
    command_type            TEXT            NOT NULL,
    target_type             TEXT            NOT NULL,
    target_id               TEXT,
    state                   TEXT            NOT NULL,
    request_jsonb           JSONB           NOT NULL DEFAULT '{}',
    requester_context_jsonb JSONB,
    result_jsonb            JSONB,
    requested_at            TIMESTAMPTZ     NOT NULL,
    dispatched_at           TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    CONSTRAINT pk_control_commands PRIMARY KEY (command_id),
    CONSTRAINT ck_control_commands__command_type CHECK (
        command_type IN (
            'CREATE_DATASET_BUILD', 'REBUILD_DATASET_BUILD', 'DELETE_DATASET_BUILD',
            'START_ATTEMPT', 'ABORT_ATTEMPT', 'REQUEST_CHECKPOINT'
        )
    ),
    CONSTRAINT ck_control_commands__target_type CHECK (
        target_type IN ('DATASET_BUILD', 'ATTEMPT')
    ),
    CONSTRAINT ck_control_commands__state CHECK (
        state IN ('PENDING', 'ACCEPTED', 'DEFERRED', 'SUCCEEDED', 'REJECTED', 'FAILED')
    )
);

CREATE INDEX IF NOT EXISTS ix_control_commands__state_requested_at
    ON control_commands (state, requested_at);

CREATE INDEX IF NOT EXISTS ix_control_commands__target
    ON control_commands (target_type, target_id);

-- ─── 12. metrics ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics (
    metric_id       BIGSERIAL       NOT NULL,
    attempt_id      TEXT            NOT NULL,
    worker_id       INTEGER,
    operation_id    BIGINT,
    step_id         BIGINT,
    strategy        TEXT,
    name            TEXT            NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    unit            TEXT,
    labels_jsonb    JSONB,
    observed_at     TIMESTAMPTZ     NOT NULL,
    CONSTRAINT pk_metrics PRIMARY KEY (metric_id),
    CONSTRAINT fk_metrics__attempt_id__attempts
        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id)
);

CREATE INDEX IF NOT EXISTS ix_metrics__attempt_id_observed_at
    ON metrics (attempt_id, observed_at);
