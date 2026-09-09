"""Pydantic schemas for Job endpoints.

Aligned to api_contract_formatted.md — Job group.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pbl4.management_backend.schemas.common import StrictWriteModel

# ─── Requested Contract (user input) ─────────────────────────────────────────


class RequestedContractV1(StrictWriteModel):
    dataset_build_id: str
    model_id: str
    epochs: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    training_seed: int
    training_strategy: str = "strict_bsp"

    @field_validator("epochs", "training_seed", mode="before")
    @classmethod
    def reject_bool_int(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted for integer fields.")
        return v

    @field_validator("learning_rate", mode="before")
    @classmethod
    def validate_learning_rate(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted for float fields.")
        if isinstance(v, (int, float)) and (not math.isfinite(v) or v <= 0):
            raise ValueError("learning_rate must be a finite positive number.")
        return v

    @field_validator("training_strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        if v != "strict_bsp":
            raise ValueError(f"Unsupported training_strategy '{v}'. V1 only supports 'strict_bsp'.")
        return v


class RequestedContractPatchV1(StrictWriteModel):
    dataset_build_id: str | None = None
    model_id: str | None = None
    epochs: int | None = Field(default=None, ge=1)
    learning_rate: float | None = Field(default=None, gt=0)
    training_seed: int | None = None
    training_strategy: str | None = None

    @field_validator("epochs", "training_seed", mode="before")
    @classmethod
    def reject_bool_int(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted for integer fields.")
        return v

    @field_validator("learning_rate", mode="before")
    @classmethod
    def validate_learning_rate(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Boolean values are not accepted for float fields.")
        if isinstance(v, (int, float)) and (not math.isfinite(v) or v <= 0):
            raise ValueError("learning_rate must be a finite positive number.")
        return v

    @field_validator("training_strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is not None and v != "strict_bsp":
            raise ValueError(f"Unsupported training_strategy '{v}'. V1 only supports 'strict_bsp'.")
        return v


# ─── Resolved Contract (frozen after validate/freeze) ─────────────────────────


class ResolvedDataset(BaseModel):
    dataset_build_id: str
    dataset_manifest_hash: str
    task_type: str
    input_shape: list[int]
    dtype: str
    num_classes: int
    batch_size: int
    shard_count: int
    preprocessing: dict[str, Any]


class ResolvedModel(BaseModel):
    model_id: str
    profile: str
    parameter_manifest_hash: str


class ResolvedTraining(BaseModel):
    epochs: int
    learning_rate: float
    training_seed: int


class ResolvedSynchronization(BaseModel):
    training_strategy: str
    expected_workers: int


class ResolvedUpdatePolicy(BaseModel):
    type: str


class ResolvedCheckpointPolicy(BaseModel):
    type: str
    schema_version: int = 1


class ResolvedProtocols(BaseModel):
    dtp_version: int
    mcp_version: int


class ResolvedContractV1(BaseModel):
    dataset: ResolvedDataset
    model: ResolvedModel
    training: ResolvedTraining
    synchronization: ResolvedSynchronization
    update_policy: ResolvedUpdatePolicy
    checkpoint_policy: ResolvedCheckpointPolicy
    protocols: ResolvedProtocols


# ─── Request Bodies ───────────────────────────────────────────────────────────


class JobCreateRequest(StrictWriteModel):
    display_name: str = Field(min_length=1)
    description: str = ""
    requested_contract: RequestedContractV1


class JobPatchRequest(StrictWriteModel):
    display_name: str | None = None
    description: str | None = None
    requested_contract: RequestedContractPatchV1 | None = None


class JobCloneRequest(StrictWriteModel):
    display_name: str | None = None


class JobStartRequest(StrictWriteModel):
    note: str | None = None


class JobResumeRequest(StrictWriteModel):
    checkpoint_id: str


# ─── Response Objects ─────────────────────────────────────────────────────────


class LatestAttemptSummary(BaseModel):
    attempt_id: str
    state: str


class JobListItem(BaseModel):
    job_id: str
    display_name: str
    state: str
    dataset_build_id: str | None = None
    model_id: str | None = None
    training_strategy: str | None = None
    contract_hash: str | None = None
    attempt_count: int = 0
    latest_attempt: LatestAttemptSummary | None = None
    created_at: datetime
    frozen_at: datetime | None = None


class AttemptSummary(BaseModel):
    total: int
    latest_attempt_id: str | None = None
    latest_attempt_state: str | None = None


class JobLinks(BaseModel):
    attempts: str


class JobDetail(BaseModel):
    job_id: str
    display_name: str
    description: str
    state: str
    requested_contract: RequestedContractV1
    resolved_contract: ResolvedContractV1 | None = None
    contract_hash: str | None = None
    cloned_from_job_id: str | None = None
    attempt_summary: AttemptSummary | None = None
    links: JobLinks | None = None
    created_at: datetime
    frozen_at: datetime | None = None
    archived_at: datetime | None = None


class JobCloneResponse(BaseModel):
    job_id: str
    state: str
    cloned_from_job_id: str
    display_name: str
    description: str
    requested_contract: RequestedContractV1
    resolved_contract: None = None
    contract_hash: None = None


class JobArchiveResponse(BaseModel):
    job_id: str
    state: str
    archived_at: datetime


class JobValidateResponse(BaseModel):
    requested_contract: RequestedContractV1
    resolved_preview: ResolvedContractV1 | None = None
    warnings: list[str] = []
    errors: list[str] = []


class CommandRef(BaseModel):
    command_id: str
    command_type: str
    command_state: str
    target_type: str
    target_id: str


class StartAttemptResponse(CommandRef):
    job_id: str
    attempt_id: str
    execution_mode: str
    resume_from_checkpoint_id: str | None = None
