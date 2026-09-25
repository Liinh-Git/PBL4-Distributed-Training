"""Worker-local compute/application semantics. DTP transport composes outside this class."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any

import numpy as np

from pbl4.adapter.base import LocalGradient, ModelAdapter, TensorBundle
from pbl4.common.work_unit import WorkUnitRef
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import CachedShard


@dataclass(frozen=True, slots=True, init=False)
class StepAssignment:
    """Step assignment representing one or more Work Units for a worker to compute."""

    attempt_id: str
    session_id: int
    worker_id: int
    operation_id: int
    step_id: int
    input_model_version: int
    batch_ordinal: int
    work_units: tuple[WorkUnitRef, ...]
    expected_sample_count: int

    def __init__(
        self,
        attempt_id: str,
        session_id: int,
        worker_id: int,
        operation_id: int,
        step_id: int,
        input_model_version: int,
        *args: Any,
        batch_ordinal: int | None = None,
        expected_sample_count: int | None = None,
        shard_id: int | None = None,
        batch_id: int | None = None,
        work_units: Sequence[WorkUnitRef] | None = None,
    ) -> None:
        if len(args) == 4:
            # Legacy 10 positional arguments:
            # (attempt_id, session_id, worker_id, operation_id, step_id, input_model_version,
            #  shard_id, batch_id, batch_ordinal, expected_sample_count)
            shard_id, batch_id, batch_ordinal, expected_sample_count = args

        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("Invalid STEP_START assignment: empty attempt_id")
        for name, val in (
            ("session_id", session_id),
            ("worker_id", worker_id),
            ("operation_id", operation_id),
            ("step_id", step_id),
            ("input_model_version", input_model_version),
            ("batch_ordinal", batch_ordinal),
        ):
            if type(val) is not int or val < 0:
                raise ValueError(
                    f"Invalid STEP_START assignment: {name} must be a non-negative integer"
                )

        if shard_id is not None and (type(shard_id) is not int or shard_id < 0):
            raise ValueError(
                "Invalid STEP_START assignment: shard_id must be a non-negative integer"
            )
        if batch_id is not None and (type(batch_id) is not int or batch_id < 0):
            raise ValueError(
                "Invalid STEP_START assignment: batch_id must be a non-negative integer"
            )

        if work_units is not None:
            resolved_units = tuple(work_units)
        elif shard_id is not None and batch_id is not None and expected_sample_count is not None:
            try:
                resolved_units = (
                    WorkUnitRef(
                        shard_id=shard_id,
                        batch_id=batch_id,
                        sample_count=expected_sample_count,
                    ),
                )
            except ValueError as exc:
                raise ValueError(f"Invalid STEP_START assignment: {exc}") from exc
        else:
            raise ValueError(
                "Invalid STEP_START assignment: requires either work_units or "
                "(shard_id, batch_id, expected_sample_count)"
            )

        if not resolved_units:
            raise ValueError("Invalid STEP_START assignment: requires at least one WorkUnitRef")

        for u in resolved_units:
            if not isinstance(u, WorkUnitRef):
                raise TypeError(f"Expected WorkUnitRef, got {type(u).__name__}")

        total_samples = sum(u.sample_count for u in resolved_units)
        if expected_sample_count is not None and expected_sample_count != total_samples:
            raise ValueError(
                f"Invalid STEP_START assignment: expected_sample_count {expected_sample_count} != "
                f"sum of unit sample counts {total_samples}"
            )

        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "input_model_version", input_model_version)
        object.__setattr__(self, "batch_ordinal", batch_ordinal)
        object.__setattr__(self, "work_units", resolved_units)
        object.__setattr__(self, "expected_sample_count", total_samples)

    @property
    def shard_id(self) -> int:
        return self.work_units[0].shard_id

    @property
    def batch_id(self) -> int:
        return self.work_units[0].batch_id


@dataclass(frozen=True, slots=True)
class ComputedGradient:
    assignment: StepAssignment
    local_gradient: LocalGradient


@dataclass(frozen=True, slots=True)
class ParameterAppliedEligibility:
    attempt_id: str
    session_id: int
    worker_id: int
    operation_id: int
    step_id: int
    model_version: int


class _SingleShardCacheWrapper:
    def __init__(self, shard: Any) -> None:
        self._shard = shard
        self.shard_id = int(shard.key.shard_id)
        self.shards = {self.shard_id: shard}

    def __contains__(self, shard_id: int) -> bool:
        return shard_id == self.shard_id

    def load_work_unit(self, unit: WorkUnitRef) -> tuple[np.ndarray, np.ndarray, Sequence[str]]:
        if unit.shard_id != self.shard_id:
            raise KeyError(f"Shard {unit.shard_id} not available")
        return self._shard.load_batch(unit.batch_id)

    def load_batch(
        self, shard_id: int, batch_id: int
    ) -> tuple[np.ndarray, np.ndarray, Sequence[str]]:
        if shard_id != self.shard_id:
            raise KeyError(f"Shard {shard_id} not available")
        return self._shard.load_batch(batch_id)


class TrainingLoop:
    def __init__(
        self,
        adapter: ModelAdapter,
        dataset: CachedShard | DatasetCache,
        model_version: int,
    ) -> None:
        if type(model_version) is not int or model_version < 0:
            raise ValueError("Invalid local model version")
        self._adapter = adapter
        if isinstance(dataset, DatasetCache):
            self._dataset_cache = dataset
        elif isinstance(dataset, CachedShard):
            self._dataset_cache = DatasetCache(
                dataset_build_id=dataset.key.dataset_build_id,
                dataset_manifest_hash=dataset.key.dataset_manifest_hash,
                shards={dataset.key.shard_id: dataset},
                root_manifest=dataset.root_manifest,
            )
        elif hasattr(dataset, "load_batch") and hasattr(dataset, "key"):
            self._dataset_cache = _SingleShardCacheWrapper(dataset)  # type: ignore[assignment]
        else:
            raise TypeError(f"Expected CachedShard or DatasetCache, got {type(dataset).__name__}")
        self._model_version = model_version
        self._lock = Lock()
        self._pending: StepAssignment | None = None
        self._eligibility: ParameterAppliedEligibility | None = None

    @property
    def local_model_version(self) -> int:
        with self._lock:
            return self._model_version

    @property
    def dataset_cache(self) -> DatasetCache:
        return self._dataset_cache

    def initialize_parameters(self, target_model_version: int, bundle: TensorBundle) -> None:
        """Install the Runtime's initial canonical snapshot, including resume versions."""
        with self._lock:
            if self._pending is not None or self._eligibility is not None:
                raise ValueError("Cannot initialize parameters while a Step is active")
            if type(target_model_version) is not int or target_model_version < 0:
                raise ValueError("Initial canonical model version must be non-negative")
            self._adapter.apply_parameters(bundle)
            self._model_version = target_model_version

    def compute(self, assignment: StepAssignment) -> ComputedGradient:
        with self._lock:
            if self._pending is not None:
                raise ValueError("Previous operation awaits canonical parameters")
            if assignment.input_model_version != self._model_version:
                raise ValueError("STEP_START uses the wrong local model version")

            units = assignment.work_units
            if not units:
                raise ValueError("StepAssignment contains no work units")

            total_samples = 0
            accum_loss = 0.0
            accum_tensors: list[np.ndarray] | None = None
            manifest_hash: str | None = None

            for unit in units:
                if unit.shard_id not in self._dataset_cache:
                    raise ValueError(
                        f"STEP_START shard assignment {unit.shard_id!r} does not match "
                        f"locally cached shards {sorted(self._dataset_cache.shards.keys())!r}"
                    )
                x, y, sample_ids = self._dataset_cache.load_work_unit(unit)
                if len(sample_ids) != len(x):
                    raise ValueError("Invalid cached batch")

                grad = self._adapter.compute_loss_and_gradients(x, y)
                if (
                    grad.sample_count != unit.sample_count
                    or grad.bundle.parameter_manifest_hash
                    != self._adapter.manifest.parameter_manifest_hash
                ):
                    raise ValueError("Local gradient does not match the assignment/model")

                n_u = unit.sample_count
                total_samples += n_u
                accum_loss += float(grad.loss) * n_u

                if accum_tensors is None:
                    manifest_hash = grad.bundle.parameter_manifest_hash
                    accum_tensors = [
                        t.astype(np.float64, copy=True) * n_u for t in grad.bundle.tensors
                    ]
                else:
                    for idx, t in enumerate(grad.bundle.tensors):
                        accum_tensors[idx] += t.astype(np.float64, copy=False) * n_u

            if total_samples != assignment.expected_sample_count or accum_tensors is None:
                raise ValueError("Computed sample count does not match expected_sample_count")

            mean_loss = accum_loss / total_samples
            mean_tensors = tuple(
                (t / total_samples).astype(np.float32, copy=False) for t in accum_tensors
            )
            bundle = TensorBundle(
                manifest_hash or self._adapter.manifest.parameter_manifest_hash,
                mean_tensors,
            )
            local_grad = LocalGradient(loss=mean_loss, bundle=bundle, sample_count=total_samples)

            self._pending = assignment
            self._eligibility = None
            return ComputedGradient(assignment, local_grad)

    def apply_parameters(
        self, assignment: StepAssignment, target_model_version: int, bundle: TensorBundle
    ) -> ParameterAppliedEligibility:
        with self._lock:
            if self._pending != assignment:
                raise ValueError("Canonical parameters do not match the pending operation")
            if (
                type(target_model_version) is not int
                or target_model_version != assignment.input_model_version + 1
                or self._model_version != assignment.input_model_version
            ):
                raise ValueError("Wrong canonical output model version")
            self._adapter.apply_parameters(bundle)
            self._model_version = target_model_version
            self._pending = None
            self._eligibility = ParameterAppliedEligibility(
                assignment.attempt_id,
                assignment.session_id,
                assignment.worker_id,
                assignment.operation_id,
                assignment.step_id,
                target_model_version,
            )
            return self._eligibility

    def consume_parameter_applied(self) -> ParameterAppliedEligibility:
        with self._lock:
            if self._eligibility is None:
                raise ValueError("Local parameter application is not ACK-eligible")
            eligibility = self._eligibility
            self._eligibility = None
            return eligibility
