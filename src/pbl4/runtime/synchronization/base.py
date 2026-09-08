"""Policy seam from admission through synchronization completion."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.context import OperationContext
from pbl4.runtime.synchronization.update_plan import UpdatePlan


class AdmissionCode(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT_DUPLICATE = "REJECT_DUPLICATE"
    REJECT_WRONG_OPERATION = "REJECT_WRONG_OPERATION"
    REJECT_MODEL_VERSION = "REJECT_MODEL_VERSION"
    REJECT_MEMBERSHIP = "REJECT_MEMBERSHIP"
    REJECT_ASSIGNMENT = "REJECT_ASSIGNMENT"
    REJECT_STRATEGY_STATE = "REJECT_STRATEGY_STATE"
    FATAL_STRATEGY_ERROR = "FATAL_STRATEGY_ERROR"


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    code: AdmissionCode
    reason: str
    # Only the arrival closing admission receives an update execution intent.
    update_plan: UpdatePlan | None = None


@dataclass(frozen=True, slots=True)
class ParameterApplied:
    attempt_id: str
    session_id: int
    worker_id: int
    operation_id: int
    step_id: int
    model_version: int


class SynchronizationPolicy(ABC):
    @abstractmethod
    def open_operation(self, operation: OperationContext) -> None: ...

    @abstractmethod
    def admit(self, contribution: Contribution) -> AdmissionDecision: ...

    @abstractmethod
    def mark_update_published(self, plan: UpdatePlan, model_version: int) -> None: ...

    @abstractmethod
    def ack_parameter_applied(self, ack: ParameterApplied) -> AdmissionDecision: ...

    @property
    @abstractmethod
    def synchronization_complete(self) -> bool: ...

    @abstractmethod
    def worker_failed(self, worker_id: int, session_id: int) -> AdmissionDecision: ...

    @abstractmethod
    def snapshot(self) -> dict[str, object]: ...

    @abstractmethod
    def cleanup(self) -> None: ...
