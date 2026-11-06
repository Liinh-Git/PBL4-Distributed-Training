"""Async admission arithmetic; no sockets, lifecycle or durability ownership."""

from dataclasses import dataclass

from pbl4.runtime.contribution import Contribution, ContributionRejected
from pbl4.runtime.workload_pool import AsyncAssignment


@dataclass(frozen=True, slots=True)
class AsyncDecision:
    staleness: int
    learning_rate: float | None


class AsyncSGD:
    def __init__(self, attempt_id: str, learning_rate: float, threshold: int):
        self.attempt_id = attempt_id
        self.learning_rate = learning_rate
        self.threshold = threshold
        self._closed = False

    def cleanup(self):
        self._closed = True

    def snapshot(self):
        return {"type": "async_sgd"}

    def admit(self, contribution: Contribution, assignment: AsyncAssignment, version: int):
        if (
            self._closed
            or contribution.attempt_id != self.attempt_id
            or (contribution.worker_id, contribution.session_id, contribution.operation_id)
            != (assignment.worker_id, assignment.session_id, assignment.operation_id)
            or contribution.batch_ordinal != assignment.operation_id
            or contribution.sample_count != sum(u.sample_count for u in assignment.work_units)
            or (contribution.shard_id, contribution.batch_id)
            != (assignment.work_units[0].shard_id, assignment.work_units[0].batch_id)
        ):
            raise ContributionRejected(
                "TRAIN_WRONG_BATCH_ASSIGNMENT", "Async contribution does not match its assignment"
            )
        if contribution.model_version != assignment.model_version:
            raise ContributionRejected(
                "TRAIN_WRONG_MODEL_VERSION", "Gradient source version differs from its assignment"
            )
        staleness = version - assignment.model_version
        if staleness < 0:
            raise ContributionRejected("TRAIN_FUTURE_CONTRIBUTION", "Future async gradient")
        rate = self.learning_rate / max(1, staleness) if staleness <= self.threshold else None
        return AsyncDecision(staleness, rate)
