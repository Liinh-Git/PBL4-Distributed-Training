"""Pydantic schemas for Runtime and System endpoints.

Aligned to api_contract_formatted.md — System, Runtime, and System/Runtime groups.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from pbl4.management_backend.schemas.attempt import StrategyStateStrictBSP, WorkerSessionItem

# ─── System / Health ─────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    backend: str
    postgres: str
    runtime_mcp: str
    dataset_manager: str
    timestamp: datetime


# ─── System / Capabilities ───────────────────────────────────────────────────


class FeatureFlags(BaseModel):
    attempt_websocket_stream: bool = True
    manual_checkpoint_request: bool = True


class CapabilitiesResponse(BaseModel):
    api_version: str = "v1"
    dtp_versions: list[int] = [1]
    mcp_versions: list[int] = [1]
    runtime_connected: bool
    runtime_instance_id: str | None = None
    supported_training_strategies: list[str] = ["strict_bsp"]
    feature_flags: FeatureFlags = FeatureFlags()


# ─── Runtime / Snapshot ──────────────────────────────────────────────────────


class RecoveryCursor(BaseModel):
    epoch: int
    next_batch_ordinal: int


class RuntimeSnapshot(BaseModel):
    runtime_instance_id: str | None = None
    active_job_id: str | None = None
    active_attempt_id: str | None = None
    attempt_state: str | None = None
    training_strategy: str | None = None
    checkpoint_policy: str | None = None
    epoch: int | None = None
    current_operation_id: int | None = None
    current_batch_ordinal: int | None = None
    model_version: int | None = None
    workers: list[WorkerSessionItem] = []
    strategy_state: StrategyStateStrictBSP | None = None
    checkpoint_state: str | None = None
    latest_checkpoint_id: str | None = None
    recovery_cursor: RecoveryCursor | None = None
    dataset_build_id: str | None = None
    dataset_manifest_hash: str | None = None
    management_event_gap_count: int = 0
    stale: bool = True
    observed_at: datetime | None = None
    runtime_event_seq: int | None = None

    @field_validator("strategy_state", "recovery_cursor", mode="before")
    @classmethod
    def _normalize_empty_objects(cls, v: object) -> object:
        if not v:
            return None
        return v
