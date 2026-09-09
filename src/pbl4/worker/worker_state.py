"""Canonical Worker Session lifecycle, separate from transient computation activity."""

from enum import StrEnum
from threading import Lock


class WorkerSessionState(StrEnum):
    CONNECTING = "CONNECTING"
    REGISTERING = "REGISTERING"
    PROVISIONING = "PROVISIONING"
    SHARD_READY = "SHARD_READY"
    MODEL_SYNCING = "MODEL_SYNCING"
    READY = "READY"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


_ORDER = (
    WorkerSessionState.CONNECTING,
    WorkerSessionState.REGISTERING,
    WorkerSessionState.PROVISIONING,
    WorkerSessionState.SHARD_READY,
    WorkerSessionState.MODEL_SYNCING,
    WorkerSessionState.READY,
)


class WorkerState:
    def __init__(self) -> None:
        self._state = WorkerSessionState.CONNECTING
        self._lock = Lock()

    @property
    def state(self) -> WorkerSessionState:
        with self._lock:
            return self._state

    def transition(self, state: WorkerSessionState) -> None:
        with self._lock:
            state = WorkerSessionState(state)
            if state == self._state:
                return
            if self._state in (WorkerSessionState.DISCONNECTED, WorkerSessionState.FAILED):
                raise ValueError("Worker Session is terminal")
            if state not in (WorkerSessionState.DISCONNECTED, WorkerSessionState.FAILED):
                index = _ORDER.index(self._state)
                if index + 1 == len(_ORDER) or state != _ORDER[index + 1]:
                    raise ValueError("Invalid Worker Session transition")
            self._state = state
