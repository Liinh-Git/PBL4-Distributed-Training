"""Schemas package — re-exports for convenience."""

from __future__ import annotations

from management_backend.schemas.attempt import (
    AttemptDetail,
    AttemptListItem,
    AttemptSnapshot,
    AbortAttemptRequest,
    AbortAttemptResponse,
    CheckpointRequestBody,
    CheckpointRequestResponse,
    JoinSpec,
    WorkerDetail,
    WorkerSessionItem,
)
from management_backend.schemas.checkpoint import CheckpointDetail, CheckpointListItem
from management_backend.schemas.command import CommandDetail, CommandListItem
from management_backend.schemas.common import (
    ErrorDetail,
    ErrorResponse,
    ItemResponse,
    ListResponse,
    Meta,
    PageInfo,
)
from management_backend.schemas.dataset import (
    DatasetBuildCreateRequest,
    DatasetBuildDeprecateRequest,
    DatasetBuildDeleteRequest,
    DatasetBuildDetail,
    DatasetBuildListItem,
    DatasetBuildRebuildRequest,
    DatasetCreateRequest,
    DatasetDetail,
    DatasetItem,
)
from management_backend.schemas.event import EventListItem, RuntimeEventItem, RuntimeEventsMeta
from management_backend.schemas.job import (
    JobArchiveResponse,
    JobCloneResponse,
    JobCreateRequest,
    JobDetail,
    JobListItem,
    JobPatchRequest,
    JobResumeRequest,
    JobStartRequest,
    JobValidateResponse,
    StartAttemptResponse,
)
from management_backend.schemas.runtime import (
    CapabilitiesResponse,
    FeatureFlags,
    HealthResponse,
    RuntimeSnapshot,
)
from management_backend.schemas.step import StepDetail, StepListItem

__all__ = [
    "AttemptDetail", "AttemptListItem", "AttemptSnapshot",
    "AbortAttemptRequest", "AbortAttemptResponse",
    "CheckpointRequestBody", "CheckpointRequestResponse",
    "CheckpointDetail", "CheckpointListItem",
    "CommandDetail", "CommandListItem",
    "DatasetBuildCreateRequest", "DatasetBuildDeprecateRequest",
    "DatasetBuildDeleteRequest", "DatasetBuildDetail", "DatasetBuildListItem",
    "DatasetBuildRebuildRequest", "DatasetCreateRequest",
    "DatasetDetail", "DatasetItem",
    "ErrorDetail", "ErrorResponse", "ItemResponse", "ListResponse",
    "Meta", "PageInfo",
    "EventListItem", "RuntimeEventItem", "RuntimeEventsMeta",
    "JobArchiveResponse", "JobCloneResponse", "JobCreateRequest",
    "JobDetail", "JobListItem", "JobPatchRequest", "JobResumeRequest",
    "JobStartRequest", "JobValidateResponse", "StartAttemptResponse",
    "JoinSpec", "WorkerDetail", "WorkerSessionItem",
    "CapabilitiesResponse", "FeatureFlags", "HealthResponse", "RuntimeSnapshot",
    "StepDetail", "StepListItem",
]
