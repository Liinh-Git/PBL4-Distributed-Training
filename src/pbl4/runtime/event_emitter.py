"""Bounded in-memory management buffering. No consumer wait or persistence."""

from threading import Lock

from pbl4.runtime.runtime_events import RuntimeEvent


def _priority(event: RuntimeEvent) -> int:
    if (
        event.severity in ("ERROR", "CRITICAL")
        or event.event_type.startswith("checkpoint.")
        or event.event_type.endswith(".state_changed")
        or event.event_type == "attempt.failed"
    ):
        return 2
    return 0 if event.event_type == "metric.sample" else 1


class EventEmitter:
    """Queue ownership is independent of Coordinator and management sockets.

    Coordinator serializes semantic transitions and calls emit in that order.
    Queue ordering remains sequence order even when lower priority events are
    evicted. Consumers recover missing history from the current state snapshot.
    """

    def __init__(self, attempt_id: str, job_id: str, capacity: int = 1024):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("Queue capacity must be positive")
        self._attempt_id = attempt_id
        self._job_id = job_id
        self._capacity = capacity
        self._events: list[RuntimeEvent] = []
        self._sequence = 0
        self._dropped = 0
        self._lock = Lock()

    def emit(
        self,
        event_type: str,
        details: dict[str, object],
        occurred_at: str,
        source_component: str = "runtime",
        severity: str = "INFO",
    ) -> RuntimeEvent:
        with self._lock:
            event = RuntimeEvent.create(
                attempt_id=self._attempt_id,
                job_id=self._job_id,
                runtime_event_seq=self._sequence + 1,
                event_type=event_type,
                event_schema_version=1,
                occurred_at=occurred_at,
                source_component=source_component,
                severity=severity,
                details=details,
            )
            self._sequence += 1
            if len(self._events) == self._capacity:
                lowest = min(range(len(self._events)), key=lambda i: _priority(self._events[i]))
                self._dropped += 1
                if _priority(self._events[lowest]) > _priority(event):
                    return event
                del self._events[lowest]
            self._events.append(event)
            return event

    def drain(self, after_sequence: int = 0) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            events = tuple(e for e in self._events if e.runtime_event_seq > after_sequence)
            self._events.clear()
            return events

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "last_runtime_event_seq": self._sequence,
                "dropped_event_count": self._dropped,
                "queued_event_count": len(self._events),
            }
