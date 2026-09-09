"""Temporary storage of already admitted contributions, without admission policy."""

from threading import Lock

from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.base import AdmissionCode, AdmissionDecision


class GradientStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[tuple[str, int, int], Contribution] = {}

    def record(self, contribution: Contribution, decision: AdmissionDecision) -> None:
        if decision.code != AdmissionCode.ACCEPT:
            raise ValueError("Only admitted contributions may be recorded")
        key = contribution.attempt_id, contribution.operation_id, contribution.worker_id
        with self._lock:
            previous = self._values.get(key)
            if previous is not None and previous != contribution:
                raise ValueError("Cannot overwrite accepted contribution")
            self._values[key] = contribution

    def snapshot(self, attempt_id: str, operation_id: int) -> tuple[Contribution, ...]:
        with self._lock:
            return tuple(
                c
                for key, c in sorted(self._values.items())
                if key[:2] == (attempt_id, operation_id)
            )

    def discard(self, attempt_id: str, operation_id: int) -> None:
        with self._lock:
            self._values = {
                key: c for key, c in self._values.items() if key[:2] != (attempt_id, operation_id)
            }
