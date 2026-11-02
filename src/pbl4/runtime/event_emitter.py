"""Bounded in-memory management buffering. No consumer wait or persistence."""

from __future__ import annotations

from threading import Condition, Lock

from pbl4.runtime.runtime_events import RuntimeEvent


def _priority(event: RuntimeEvent) -> int:
    return event.delivery_priority


class EventEmitter:
    """Queue ownership is independent of Coordinator and management sockets.

    Coordinator serializes semantic transitions and calls emit in that order.
    Queue ordering remains sequence order even when lower priority events are
    evicted. Consumers recover missing history from the current state snapshot.
    """

    def __init__(
        self,
        attempt_id: str,
        job_id: str,
        capacity: int = 8192,
        *,
        buffer: EventEmitter | None = None,
    ):
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("Queue capacity must be positive")
        self._attempt_id = attempt_id
        self._job_id = job_id
        self._buffer = buffer or self
        self._capacity = buffer._capacity if buffer is not None else capacity
        self._events: list[RuntimeEvent] = buffer._events if buffer is not None else []
        self._owners: dict[tuple[str, int], EventEmitter] = (
            buffer._owners if buffer is not None else {}
        )
        self._sequence = 0
        self._dropped = 0
        self._queued = 0
        self._lock = buffer._lock if buffer is not None else Lock()
        self._ready = buffer._ready if buffer is not None else Condition(self._lock)

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
                if _priority(self._events[lowest]) > _priority(event):
                    self._dropped += 1
                    if self._buffer is not self:
                        self._buffer._dropped += 1
                    return event
                evicted = self._events.pop(lowest)
                owner = self._owners.pop((evicted.attempt_id, evicted.runtime_event_seq))
                owner._dropped += 1
                if owner._buffer is not owner:
                    owner._buffer._dropped += 1
                owner._queued -= 1
            self._events.append(event)
            self._owners[(event.attempt_id, event.runtime_event_seq)] = self
            self._queued += 1
            self._ready.notify()
            return event

    def wait(self, timeout: float = 0.5) -> None:
        """Wait only in the publisher; emitting never waits for a consumer."""
        with self._ready:
            if not (self._events if self._buffer is self else self._queued):
                self._ready.wait(timeout)

    def peek(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            events = (
                self._events
                if self._buffer is self
                else [event for event in self._events if event.attempt_id == self._attempt_id]
            )
            if limit is not None:
                return tuple(events[:limit])
            return tuple(events)

    def ack(self, sequence: int, *, attempt_id: str | None = None) -> bool:
        with self._lock:
            target = attempt_id if attempt_id is not None else self._attempt_id
            if self._events and (self._events[0].attempt_id, self._events[0].runtime_event_seq) == (
                target,
                sequence,
            ):
                self._events.pop(0)
                self._owners.pop((target, sequence))._queued -= 1
                return True
            if not any(
                event.attempt_id == target and event.runtime_event_seq == sequence
                for event in self._events
            ):
                return False
            retained = []
            for event in self._events:
                if event.attempt_id == target and event.runtime_event_seq <= sequence:
                    owner = self._owners.pop((event.attempt_id, event.runtime_event_seq))
                    owner._queued -= 1
                else:
                    retained.append(event)
            self._events[:] = retained
            return True

    def drain(self, after_sequence: int = 0) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            events = tuple(
                e
                for e in self._events
                if e.attempt_id == self._attempt_id and e.runtime_event_seq > after_sequence
            )
            keys = {(event.attempt_id, event.runtime_event_seq) for event in events}
            self._events[:] = [
                event
                for event in self._events
                if (event.attempt_id, event.runtime_event_seq) not in keys
            ]
            for key in keys:
                self._owners.pop(key)._queued -= 1
            return events

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "last_runtime_event_seq": self._sequence,
                "dropped_event_count": self._dropped,
                "queued_event_count": len(self._events) if self._buffer is self else self._queued,
            }
