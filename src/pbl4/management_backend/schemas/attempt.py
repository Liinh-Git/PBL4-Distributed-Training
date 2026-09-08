"""Pydantic schemas for Attempt, Worker, Step endpoints.

Aligned to api_contract_formatted.md — Attempt and Runtime/Worker groups.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# ─── Attempt ─────────────────────────────────────────────────────────────────


class AttemptListItem(BaseModel):
    attempt_id: str
    job_id: str
    state: str
    execution_mode: str
    training_strategy: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    failure_code: str | None = None


class MembershipInfo(BaseModel):
    active_workers: int
    expected_workers: int


class ProgressCursor(BaseModel):
    epoch: int
    next_batch_ordinal: int


class CheckpointRef(BaseModel):
    state: str
    latest_checkpoint_id: str | None = None


class RuntimeInfo(BaseModel):
    stale: bool
    observed_at: datetime | None = None
    runtime_event_seq: int | None = None


class StrategyStateStrictBSP(BaseModel):
    type: str
    current_step_id: int | None = None
    state: str | None = None
    accepted_contribution_count: int | None = None
    expected_contribution_count: int | None = None
    parameter_applied_count: int | None = None
    barrier_wait_ms: float | None = None
    synchronization_complete: bool | None = None


class FailureInfo(BaseModel):
    code: str
    message: str | None = None


class AttemptLinks(BaseModel):
    job: str
    workers: str
    steps: str
    events: str


class AttemptDetail(BaseModel):
    attempt_id: str
    job_id: str
    contract_hash: str
    state: str
    execution_mode: str
    training_strategy: str | None = None
    expected_workers: int | None = None
    membership: MembershipInfo | None = None
    epoch: int | None = None
    progress_cursor: ProgressCursor | None = None
    model_version: int | None = None
    checkpoint: CheckpointRef | None = None
    runtime: RuntimeInfo | None = None
    strategy_state: StrategyStateStrictBSP | None = None
    failure: FailureInfo | None = None
    links: AttemptLinks | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None


class AbortAttemptRequest(BaseModel):
    reason: str | None = None


class AbortAttemptResponse(BaseModel):
    command_id: str
    command_type: str
    command_state: str
    target_type: str
    target_id: str
    attempt_id: str


class CheckpointRequestBody(BaseModel):
    reason: str | None = None


class CheckpointRequestResponse(BaseModel):
    command_id: str
    command_type: str
    command_state: str
    target_type: str
    target_id: str
    attempt_id: str


# ─── Worker Session ───────────────────────────────────────────────────────────


class WorkerSessionItem(BaseModel):
    worker_id: int
    session_id: str
    node_label: str
    state: str
    shard_id: int | None = None
    local_model_version: int | None = None
    protocol_version: int
    connected_at: datetime
    last_heartbeat_at: datetime | None = None
    disconnected_at: datetime | None = None
    failure_code: str | None = None


class WorkerDetail(BaseModel):
    worker_id: int
    active_session: WorkerSessionItem | None = None
    historical_sessions: list[WorkerSessionItem] = []


# ─── Attempt Snapshot ─────────────────────────────────────────────────────────


class AttemptSnapshot(BaseModel):
    attempt_id: str
    state: str
    training_strategy: str | None = None
    epoch: int | None = None
    current_operation_id: int | None = None
    current_batch_ordinal: int | None = None
    model_version: int | None = None
    workers: list[WorkerSessionItem] = []
    strategy_state: StrategyStateStrictBSP | None = None
    checkpoint_state: str | None = None
    latest_checkpoint_id: str | None = None
    stale: bool = True
    observed_at: datetime | None = None
    runtime_event_seq: int | None = None


# ─── Join Spec ───────────────────────────────────────────────────────────────


class JoinSpecProtocol(BaseModel):
    dtp_version: int


class JoinSpec(BaseModel):
    ps_host: str
    ps_port: int
    job_id: str
    attempt_id: str
    contract_hash: str
    protocol: JoinSpecProtocol
    expires_at: datetime | None = None
