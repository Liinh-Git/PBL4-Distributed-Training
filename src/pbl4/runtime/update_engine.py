"""Serialized, exactly-once canonical updates scoped to one Attempt."""

from threading import Lock

from pbl4.runtime.aggregator import AggregatedGradient
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.sgd_updater import SGDUpdater
from pbl4.runtime.synchronization.update_plan import UpdatePlan


class UpdateEngine:
    def __init__(
        self,
        model: CanonicalModel,
        attempt_id: str,
        update_policy: str,
        learning_rate: float,
    ) -> None:
        self._model = model
        self._attempt_id = attempt_id
        self._update_policy = update_policy
        self._learning_rate = learning_rate
        self._lock = Lock()
        self._updater = SGDUpdater()
        self._last: tuple[UpdatePlan, AggregatedGradient, ModelSnapshot] | None = None
        self._applied: set[tuple[str, str, int]] = set()
        self._async_operations: dict[int, int] = {}
        model._bind_writer(self)

    def apply_once(self, plan: UpdatePlan, aggregate: AggregatedGradient) -> ModelSnapshot:
        with self._lock:
            if plan.attempt_id != self._attempt_id or plan.update_policy != self._update_policy:
                raise ValueError("Update contract identity mismatch")
            if aggregate.plan != plan:
                raise ValueError("Aggregate belongs to a different plan")
            if self._last is not None and self._last[0].identity == plan.identity:
                if self._last[0] != plan or self._last[1] != aggregate:
                    raise ValueError("Conflicting replay of applied update identity")
                return self._last[2]
            if plan.identity in self._applied:
                raise ValueError("Update identity was already applied")
            before = self._model.snapshot()
            if plan.input_model_version != before.model_version:
                raise ValueError("Stale or future canonical input version")
            if aggregate.parameter_manifest_hash != before.parameter_manifest_hash:
                raise ValueError("Parameter manifest mismatch")
            candidate = self._updater.update(
                before.parameters, aggregate.gradient, self._learning_rate
            )
            after = ModelSnapshot(
                before.model_version + 1, before.parameter_manifest_hash, candidate.tobytes()
            )
            self._model._publish(self, before, after)
            # Retain one replay result; older input versions are rejected before mutation.
            self._last = plan, aggregate, after
            self._applied.add(plan.identity)
            return after

    def apply_async_once(
        self, contribution: Contribution, current_version: int, learning_rate: float
    ) -> ModelSnapshot:
        """Execute a policy-approved update; the Coordinator serializes its ledger commit."""
        with self._lock:
            before = self._model.snapshot()
            if (
                contribution.attempt_id != self._attempt_id
                or contribution.parameter_manifest_hash != before.parameter_manifest_hash
                or before.model_version != current_version
                or contribution.operation_id
                <= self._async_operations.get(contribution.worker_id, -1)
            ):
                raise ValueError("Invalid or duplicate async update")
            candidate = self._updater.update(
                before.parameters, contribution.gradient, learning_rate
            )
            after = ModelSnapshot(
                current_version + 1, before.parameter_manifest_hash, candidate.tobytes()
            )
            self._model._publish(self, before, after)
            self._async_operations[contribution.worker_id] = contribution.operation_id
            return after
