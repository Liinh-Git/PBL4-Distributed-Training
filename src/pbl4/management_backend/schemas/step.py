"""Pydantic schemas for Step endpoints (StrictBSP steps).

Aligned to api_contract_formatted.md — Training/StrictBSP group.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class StepListItem(BaseModel):
    step_id: int
    operation_id: int
    state: str
    input_model_version: int
    output_model_version: int | None = None
    epoch: int
    batch_ordinal: int
    total_sample_count: int | None = None
    committed_at: datetime | None = None


class StepTiming(BaseModel):
    started_at: datetime
    update_completed_at: datetime | None = None
    synchronization_completed_at: datetime | None = None
    checkpoint_completed_at: datetime | None = None
    committed_at: datetime | None = None


class WorkerStepItem(BaseModel):
    worker_id: int
    session_id: str
    shard_id: int
    batch_id: int
    sample_count: int
    contribution_accepted: bool = False
    parameter_applied: bool = False


class StepDetail(BaseModel):
    training_strategy: str
    step_id: int
    operation_id: int
    input_model_version: int
    output_model_version: int | None = None
    state: str
    epoch: int
    batch_ordinal: int
    total_sample_count: int | None = None
    timing: StepTiming | None = None
    worker_steps: list[WorkerStepItem] = []
