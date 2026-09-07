"""Typed identifiers and value representations for PBL4 domain entities.

Reference: Canonical Data Model & DTP/1 Specification (Google Drive)

All identifier types provide clear domain typing and prevent accidental mixing
of IDs across subsystem boundaries.

Key Invariants:
- session_id: wire representation is uint64; in PostgreSQL it must fit within safe positive BIGINT.
- operation_id: canonical DTP/1 wire representation is an 8-byte generic correlation field.
  Python-side representation is not chosen here.
- No random UUID generation is assumed unless explicitly defined by canonical specification.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobId:
    """Unique identifier for a training Job."""

    value: str


@dataclass(frozen=True, slots=True)
class AttemptId:
    """Unique identifier for an execution Attempt of a Job."""

    value: str


@dataclass(frozen=True, slots=True)
class DatasetBuildId:
    """Unique identifier for an ingested and partitioned Dataset Build."""

    value: str


@dataclass(frozen=True, slots=True)
class CheckpointId:
    """Unique identifier for a saved model Checkpoint."""

    value: str


@dataclass(frozen=True, slots=True)
class CommandId:
    """Unique identifier for an asynchronous control command."""

    value: str


@dataclass(frozen=True, slots=True)
class WorkerId:
    """Logical worker rank assigned by Runtime during registration (0-indexed)."""

    value: int


@dataclass(frozen=True, slots=True)
class SessionId:
    """Unique worker session identifier within an attempt.

    Wire representation: uint64 (8 bytes).
    Allocated values: positive integers safe for PostgreSQL BIGINT (1 .. 2^63 - 1).
    """

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise TypeError("SessionId value must be an integer")
        if self.value <= 0 or self.value > (2**63 - 1):
            raise ValueError(f"SessionId must be in 1 .. 2^63 - 1 (safe BIGINT), got {self.value}")


@dataclass(frozen=True, slots=True)
class ModelVersion:
    """Monotonically increasing version counter for the canonical model."""

    value: int


# Note: OperationId wire representation is an 8-byte generic correlation field in DTP/1.
# It represents generic operation identity; StrictBSP V1 maps operation_id 1:1 with step_id,
# but the concepts are not globally synonymous.
# Its Python-side representation will be decided during protocol implementation.
