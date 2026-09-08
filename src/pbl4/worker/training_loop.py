"""Worker-local compute/application semantics. DTP transport composes outside this class."""

from dataclasses import dataclass
from threading import Lock

from pbl4.adapter.base import LocalGradient, ModelAdapter, TensorBundle
from pbl4.worker.shard_cache import CachedShard


@dataclass(frozen=True, slots=True)
class StepAssignment:
    attempt_id: str
    session_id: int
    worker_id: int
    operation_id: int
    step_id: int
    input_model_version: int
    batch_id: int
    batch_ordinal: int
    expected_sample_count: int

    def __post_init__(self) -> None:
        if (
            not self.attempt_id
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.session_id,
                    self.worker_id,
                    self.operation_id,
                    self.step_id,
                    self.input_model_version,
                    self.batch_id,
                    self.batch_ordinal,
                )
            )
            or type(self.expected_sample_count) is not int
            or self.expected_sample_count <= 0
        ):
            raise ValueError("Invalid STEP_START assignment")


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


class TrainingLoop:
    def __init__(self, adapter: ModelAdapter, shard: CachedShard, model_version: int):
        if type(model_version) is not int or model_version < 0:
            raise ValueError("Invalid local model version")
        self._adapter = adapter
        self._shard = shard
        self._model_version = model_version
        self._lock = Lock()
        self._pending: StepAssignment | None = None
        self._eligibility: ParameterAppliedEligibility | None = None

    @property
    def local_model_version(self) -> int:
        with self._lock:
            return self._model_version

    def compute(self, assignment: StepAssignment) -> ComputedGradient:
        with self._lock:
            if self._pending is not None:
                raise ValueError("Previous operation awaits canonical parameters")
            if assignment.input_model_version != self._model_version:
                raise ValueError("STEP_START uses the wrong local model version")
            x, y, sample_ids = self._shard.load_batch(assignment.batch_id)
            if len(x) != assignment.expected_sample_count:
                raise ValueError("Assigned physical batch sample count mismatch")
            # sample_ids are verified by the cache; workers never choose a replacement.
            if len(sample_ids) != len(x):
                raise ValueError("Invalid cached batch")
            gradient = self._adapter.compute_loss_and_gradients(x, y)
            if (
                gradient.sample_count != assignment.expected_sample_count
                or gradient.bundle.parameter_manifest_hash
                != self._adapter.manifest.parameter_manifest_hash
            ):
                raise ValueError("Local gradient does not match the assignment/model")
            self._pending = assignment
            self._eligibility = None
            return ComputedGradient(assignment, gradient)

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
