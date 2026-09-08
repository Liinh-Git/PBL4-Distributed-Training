"""Pydantic schemas for Dataset and DatasetBuild endpoints.

Aligned to api_contract_formatted.md — Dataset and Dataset Build groups.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from pbl4.management_backend.schemas.common import StrictWriteModel

# ─── Dataset ──────────────────────────────────────────────────────────────────


class DatasetCreateRequest(StrictWriteModel):
    """POST /api/v1/datasets — DatasetSourceV1."""

    name: str = Field(min_length=1)
    task_type: str
    source_type: str
    source_reference: str


class DatasetItem(BaseModel):
    dataset_id: str
    name: str
    task_type: str
    source_type: str
    source_reference: str
    created_at: datetime


class BuildCounts(BaseModel):
    CREATED: int = 0
    QUEUED: int = 0
    IMPORTING: int = 0
    VALIDATING: int = 0
    PREPROCESSING: int = 0
    MATERIALIZING: int = 0
    VERIFYING: int = 0
    REGISTERING: int = 0
    READY: int = 0
    FAILED: int = 0
    DEPRECATED: int = 0
    DELETING: int = 0
    DELETED: int = 0


class DatasetDetail(DatasetItem):
    build_counts: BuildCounts


# ─── Dataset Build ────────────────────────────────────────────────────────────


class NormalizationConfig(StrictWriteModel):
    mean: list[float]
    std: list[float]


class PreprocessingConfig(StrictWriteModel):
    input_shape: list[int] | None = None
    normalization: NormalizationConfig | None = None


class DatasetBuildCreateRequest(StrictWriteModel):
    """POST /api/v1/dataset-builds — DatasetBuildCreateV1."""

    dataset_id: str
    profile: str
    batch_size: int = Field(gt=0)
    partition_seed: int = Field(ge=0)
    preprocessing: PreprocessingConfig | None = None


class DatasetBuildRebuildRequest(StrictWriteModel):
    """POST /api/v1/dataset-builds/{id}/rebuild — optional overrides."""

    batch_size: int | None = Field(default=None, gt=0)
    partition_seed: int | None = Field(default=None, ge=0)
    preprocessing: PreprocessingConfig | None = None


class DatasetBuildDeprecateRequest(StrictWriteModel):
    reason: str | None = None


class DatasetBuildDeleteRequest(StrictWriteModel):
    reason: str | None = None


class ManifestSummary(BaseModel):
    dataset_manifest_hash: str
    manifest_uri: str
    artifact_base_url: str


class BuildReference(BaseModel):
    type: str
    id: str


class DatasetBuildListItem(BaseModel):
    dataset_build_id: str
    dataset_id: str
    state: str
    profile: str
    batch_size: int
    shard_count: int
    sample_count: int | None = None
    created_at: datetime
    ready_at: datetime | None = None


class DatasetBuildDetail(BaseModel):
    dataset_build_id: str
    dataset_id: str
    state: str
    current_stage: str
    progress: float
    profile: str
    batch_size: int
    shard_count: int
    partition_seed: int
    sample_count: int | None = None
    manifest_summary: ManifestSummary | None = None
    references: list[BuildReference] = []
    error: str | None = None
    created_at: datetime
    ready_at: datetime | None = None


class DatasetBuildDeprecateResponse(BaseModel):
    dataset_build_id: str
    state: str
    deprecated_at: datetime


class BuildCommandResponse(BaseModel):
    command_id: str
    command_type: str
    command_state: str
    target_type: str
    target_id: str
    dataset_build_id: str
    dataset_build_state: str
    source_dataset_build_id: str | None = None
    new_dataset_build_id: str | None = None
