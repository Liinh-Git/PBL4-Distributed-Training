"""Fixed-membership StrictBSP with atomic selection and parameter ACK tracking."""

from threading import Lock

from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.barrier import Barrier
from pbl4.runtime.synchronization.base import AdmissionCode as Code
from pbl4.runtime.synchronization.base import (
    AdmissionDecision,
    ParameterApplied,
    SynchronizationPolicy,
)
from pbl4.runtime.synchronization.context import OperationContext, StrategyContext
from pbl4.runtime.synchronization.update_plan import UpdatePlan


class StrictBSP(SynchronizationPolicy):
    """Serialize semantic decisions only; never perform I/O under this lock.

    Coordinator must satisfy lifecycle and durability gates before opening the
    next operation. This policy only owns the synchronization side of that gate.
    """

    def __init__(self, context: StrategyContext) -> None:
        if context.training_strategy != "strict_bsp":
            raise ValueError("UNSUPPORTED_TRAINING_STRATEGY")
        self._context = context
        self._sessions = {m.worker_id: m.session_id for m in context.membership}
        self._membership = frozenset(self._sessions)
        self._lock = Lock()
        self._operation: OperationContext | None = None
        self._contributions: dict[int, Contribution] = {}
        self._plan: UpdatePlan | None = None
        self._output_version: int | None = None
        self._failed = False
        self._closed = False
        self._acks = Barrier(self._membership)

    @property
    def context(self) -> StrategyContext:
        return self._context

    def open_operation(self, operation: OperationContext) -> None:
        with self._lock:
            if self._failed or self._closed:
                raise ValueError("Strategy is terminal")
            if self._operation is not None:
                if not self._acks.complete:
                    raise ValueError("Previous synchronization is incomplete")
                if operation.step_id != self._operation.step_id + 1:
                    raise ValueError("StrictBSP step must advance once")
                if operation.input_model_version != self._output_version:
                    raise ValueError("Next operation must use published model version")
            elif operation.step_id != 0:
                raise ValueError("A new Attempt starts at step zero")
            if operation.operation_id != operation.step_id:
                raise ValueError("StrictBSP V1 maps operation_id to step_id")
            assignments = {a.worker_id: a for a in operation.assignments}
            if (
                len(assignments) != len(operation.assignments)
                or set(assignments) != self._membership
            ):
                raise ValueError("Assignments must cover exact membership")
            if any(a.batch_ordinal != operation.batch_ordinal for a in operation.assignments):
                raise ValueError("Wrong batch ordinal in assignment")
            self._operation = operation
            self._contributions = {}
            self._plan = None
            self._output_version = None
            self._acks = Barrier(self._membership)

    def admit(self, contribution: Contribution) -> AdmissionDecision:
        c = contribution
        with self._lock:
            op = self._operation
            if self._failed or self._closed or op is None:
                return AdmissionDecision(Code.REJECT_STRATEGY_STATE, "Admission is closed")
            if c.attempt_id != self.context.attempt_id:
                return AdmissionDecision(Code.FATAL_STRATEGY_ERROR, "Wrong Attempt identity")
            if type(c.worker_id) is not int or self._sessions.get(c.worker_id) != c.session_id:
                return AdmissionDecision(Code.REJECT_MEMBERSHIP, "Wrong Worker or active session")
            if type(c.session_id) is not int:
                return AdmissionDecision(Code.REJECT_MEMBERSHIP, "Invalid session identity")
            if (
                type(c.operation_id) is not int
                or type(c.step_id) is not int
                or (c.operation_id, c.step_id) != (op.operation_id, op.step_id)
            ):
                return AdmissionDecision(Code.REJECT_WRONG_OPERATION, "Stale or future operation")
            if c.worker_id in self._contributions:
                return AdmissionDecision(
                    Code.REJECT_DUPLICATE, "Logical contribution already accepted"
                )
            if self._plan is not None:
                return AdmissionDecision(Code.REJECT_STRATEGY_STATE, "Update selection is frozen")
            if type(c.model_version) is not int or c.model_version != op.input_model_version:
                return AdmissionDecision(Code.REJECT_MODEL_VERSION, "Wrong input model version")
            assignment = next(a for a in op.assignments if a.worker_id == c.worker_id)
            actual = (c.shard_id, c.batch_id, c.batch_ordinal, c.sample_count)
            expected = (
                assignment.shard_id,
                assignment.batch_id,
                assignment.batch_ordinal,
                assignment.sample_count,
            )
            if any(type(v) is not int for v in actual) or actual != expected:
                return AdmissionDecision(Code.REJECT_ASSIGNMENT, "Wrong batch or sample count")
            if (
                c.parameter_manifest_hash != self.context.parameter_manifest_hash
                or c.gradient.size != self.context.total_numel
                or type(c.tensor_id) is not int
                or not 0 <= c.tensor_id < 0xFFFFFFFF
            ):
                return AdmissionDecision(Code.FATAL_STRATEGY_ERROR, "Invalid manifest or tensor")
            self._contributions[c.worker_id] = c
            if frozenset(self._contributions) == self._membership:
                self._plan = UpdatePlan(
                    self.context.attempt_id,
                    self.context.training_strategy,
                    op.operation_id,
                    op.step_id,
                    op.input_model_version,
                    self.context.update_policy,
                    tuple(self._contributions[w] for w in sorted(self._membership)),
                )
                return AdmissionDecision(Code.ACCEPT, "Full membership selected", self._plan)
            return AdmissionDecision(Code.ACCEPT, "Contribution accepted")

    def mark_update_published(self, plan: UpdatePlan, model_version: int) -> None:
        with self._lock:
            if self._failed or self._closed or plan is not self._plan:
                raise ValueError("Update does not belong to active strategy selection")
            if type(model_version) is not int or model_version != plan.input_model_version + 1:
                raise ValueError("Canonical model version must advance once")
            self._output_version = model_version

    def ack_parameter_applied(self, ack: ParameterApplied) -> AdmissionDecision:
        with self._lock:
            op = self._operation
            if self._failed or self._closed or op is None or self._output_version is None:
                return AdmissionDecision(
                    Code.REJECT_STRATEGY_STATE, "No published update awaiting ACK"
                )
            if ack.attempt_id != self.context.attempt_id:
                return AdmissionDecision(Code.FATAL_STRATEGY_ERROR, "Wrong ACK Attempt")
            if (
                type(ack.worker_id) is not int
                or type(ack.session_id) is not int
                or self._sessions.get(ack.worker_id) != ack.session_id
            ):
                return AdmissionDecision(Code.REJECT_MEMBERSHIP, "Wrong ACK Worker or session")
            if (
                type(ack.operation_id) is not int
                or type(ack.step_id) is not int
                or (ack.operation_id, ack.step_id) != (op.operation_id, op.step_id)
            ):
                return AdmissionDecision(Code.REJECT_WRONG_OPERATION, "Wrong ACK operation")
            if type(ack.model_version) is not int or ack.model_version != self._output_version:
                return AdmissionDecision(Code.REJECT_MODEL_VERSION, "Wrong ACK output version")
            if not self._acks.arrive(ack.worker_id):
                return AdmissionDecision(Code.REJECT_DUPLICATE, "Parameter already applied")
            return AdmissionDecision(Code.ACCEPT, "Parameter application acknowledged")

    @property
    def synchronization_complete(self) -> bool:
        with self._lock:
            return not self._failed and not self._closed and self._acks.complete

    def worker_failed(self, worker_id: int, session_id: int) -> AdmissionDecision:
        with self._lock:
            if self._sessions.get(worker_id) != session_id:
                return AdmissionDecision(Code.REJECT_MEMBERSHIP, "Not an active member")
            self._failed = True
            self._contributions.clear()
            self._plan = None
            return AdmissionDecision(Code.FATAL_STRATEGY_ERROR, "Fixed membership lost")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "current_step_id": self._operation.step_id if self._operation else None,
                "expected_workers": self.context.expected_workers,
                "accepted_workers": tuple(sorted(self._contributions)),
                "parameter_applied_workers": tuple(sorted(self._acks.arrived)),
                "synchronization_complete": (
                    not self._failed and not self._closed and self._acks.complete
                ),
            }

    def cleanup(self) -> None:
        with self._lock:
            self._closed = True
            self._contributions.clear()
            self._plan = None
            self._operation = None
            self._acks = Barrier(self._membership)
