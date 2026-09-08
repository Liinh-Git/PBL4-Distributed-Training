"""Pydantic schemas for Checkpoint endpoints.

Aligned to api_contract_formatted.md — Training/Checkpoint group.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class CheckpointListItem(BaseModel):
    checkpoint_id: str
    job_id: str
    created_by_attempt_id: str
    state: str
    model_version: int
    source_step_id: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CheckpointRecoveryCursor(BaseModel):
    epoch: int
    next_batch_ordinal: int


class CheckpointIntegrity(BaseModel):
    model_sha256: str | None = None
    metadata_sha256: str | None = None
    artifact_size_bytes: int | None = None


class CheckpointDetail(BaseModel):
    checkpoint_id: str
    state: str
    job_id: str
    created_by_attempt_id: str
    contract_hash: str | None = None
    dataset_build_id: str | None = None
    dataset_manifest_hash: str | None = None
    parameter_manifest_hash: str | None = None
    training_strategy: str | None = None
    source_operation_id: int
    source_step_id: int | None = None
    model_version: int
    recovery_cursor: CheckpointRecoveryCursor | None = None
    integrity: CheckpointIntegrity | None = None
    created_at: datetime
    completed_at: datetime | None = None
