"""Liveness inspection returns failure inputs; Coordinator owns fail-stop."""

import math

from pbl4.runtime.worker_registry import SessionState, WorkerRegistry, WorkerSession


class HeartbeatMonitor:
    def __init__(self, registry: WorkerRegistry, timeout_seconds: float = 15.0):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Invalid heartbeat timeout")
        self._registry = registry
        self._timeout = timeout_seconds

    def expired(self, now: float) -> tuple[WorkerSession, ...]:
        """Transport reports validated progress through the same registry clock.

        This prevents a progressing large transfer from expiring simply because
        heartbeat frames cannot interleave with that logical transfer.
        """
        if not math.isfinite(now):
            raise ValueError("Invalid liveness clock")
        return tuple(
            session
            for session in self._registry.snapshot()
            if session.state not in (SessionState.DISCONNECTED, SessionState.FAILED)
            and now - session.last_heartbeat_at >= self._timeout
        )
