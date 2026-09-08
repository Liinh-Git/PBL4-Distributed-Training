"""Thread-safe Worker Session lifecycle. Attempt transitions belong to Coordinator."""

from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock

from pbl4.runtime.synchronization.context import Member


class SessionState(StrEnum):
    CONNECTING = "CONNECTING"
    REGISTERING = "REGISTERING"
    PROVISIONING = "PROVISIONING"
    SHARD_READY = "SHARD_READY"
    MODEL_SYNCING = "MODEL_SYNCING"
    READY = "READY"
    DISCONNECTED = "DISCONNECTED"
    FAILED = "FAILED"


_PHASES = (
    SessionState.CONNECTING,
    SessionState.REGISTERING,
    SessionState.PROVISIONING,
    SessionState.SHARD_READY,
    SessionState.MODEL_SYNCING,
    SessionState.READY,
)
_TERMINAL = (SessionState.DISCONNECTED, SessionState.FAILED)


@dataclass(frozen=True, slots=True)
class WorkerSession:
    attempt_id: str
    worker_id: int
    session_id: int
    state: SessionState
    connected_at: float
    last_heartbeat_at: float
    disconnected_at: float | None = None
    failure_code: str | None = None


class WorkerRegistry:
    def __init__(self, attempt_id: str, expected_workers: int):
        if type(expected_workers) is not int or expected_workers <= 0:
            raise ValueError("Invalid resolved worker count")
        self._attempt_id = attempt_id
        self._expected_workers = expected_workers
        self._lock = Lock()
        self._sessions: dict[int, WorkerSession] = {}
        self._used_sessions: set[int] = set()
        self._frozen = False

    def register(self, session_id: int, now: float, worker_id: int | None = None) -> WorkerSession:
        with self._lock:
            if self._frozen:
                raise ValueError("Active membership cannot be replaced")
            if session_id in self._used_sessions:
                raise ValueError("Session identity cannot be reused")
            available = [
                w
                for w in range(self._expected_workers)
                if w not in self._sessions or self._sessions[w].state in _TERMINAL
            ]
            if worker_id is None:
                if not available:
                    raise ValueError("Membership is full")
                worker_id = available[0]
            if worker_id not in available:
                raise ValueError("Rank unavailable")
            Member(worker_id, session_id)
            session = WorkerSession(
                self._attempt_id, worker_id, session_id, SessionState.CONNECTING, now, now
            )
            self._sessions[worker_id] = session
            self._used_sessions.add(session_id)
            return session

    def transition(
        self,
        worker_id: int,
        session_id: int,
        state: SessionState,
        now: float,
        failure_code: str | None = None,
    ) -> WorkerSession:
        with self._lock:
            old = self._get(worker_id, session_id)
            state = SessionState(state)
            if state == old.state:
                return old
            if old.state in _TERMINAL:
                raise ValueError("Terminal sessions cannot be reused")
            if state not in _TERMINAL:
                index = _PHASES.index(old.state)
                if index + 1 == len(_PHASES) or state != _PHASES[index + 1]:
                    raise ValueError("Invalid session progression")
            current = replace(
                old,
                state=state,
                disconnected_at=now if state in _TERMINAL else None,
                failure_code=failure_code,
            )
            self._sessions[worker_id] = current
            return current

    def heartbeat(self, worker_id: int, session_id: int, now: float) -> None:
        with self._lock:
            old = self._get(worker_id, session_id)
            if old.state in _TERMINAL or now < old.last_heartbeat_at:
                raise ValueError("Inactive session or backward liveness timestamp")
            self._sessions[worker_id] = replace(old, last_heartbeat_at=now)

    def freeze_membership(self) -> tuple[Member, ...]:
        with self._lock:
            if len(self._sessions) != self._expected_workers or any(
                s.state != SessionState.READY for s in self._sessions.values()
            ):
                raise ValueError("Full membership is not ready")
            self._frozen = True
            return tuple(Member(w, s.session_id) for w, s in sorted(self._sessions.items()))

    def snapshot(self) -> tuple[WorkerSession, ...]:
        with self._lock:
            return tuple(s for _, s in sorted(self._sessions.items()))

    def _get(self, worker_id: int, session_id: int) -> WorkerSession:
        session = self._sessions.get(worker_id)
        if session is None or session.session_id != session_id:
            raise ValueError("Wrong active session")
        return session
