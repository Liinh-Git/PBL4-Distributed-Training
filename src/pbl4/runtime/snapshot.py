"""Immutable checkpoint revision captured by Coordinator before filesystem I/O."""

from dataclasses import dataclass

from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import ModelSnapshot


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    checkpoint_id: str
    checkpoint_schema_version: int
    job_id: str
    created_by_attempt_id: str
    contract_hash: str
    checkpoint_policy: str
    checkpoint_policy_version: int
    training_strategy: str
    dataset_build_id: str
    dataset_manifest_hash: str
    model_id: str
    model_profile: str
    source_operation_id: int
    source_step_id: int | None
    optimizer: str
    created_at: str
    model: ModelSnapshot
    recovery_cursor: RecoveryCursor
