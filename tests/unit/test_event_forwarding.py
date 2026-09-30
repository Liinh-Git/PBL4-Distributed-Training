"""Unit tests for Runtime event forwarding and EventEmitter peek/send/ack semantics.

Mandatory tests for Bug #5:
1. Inject send failure after first event in batch -> second event remains queued.
2. Reconnect -> remaining event sent in exact sequence without duplicating state.
3. Terminal event COMPLETED not lost when MCP disconnects during completion.
4. Priority eviction when queue is full preserves checkpoints and terminal events.
5. Peek and ack semantics on EventEmitter.
6. Clean termination on Runtime process shutdown.
"""

from __future__ import annotations

import threading
import time
import unittest

from pbl4.runtime.event_emitter import EventEmitter, _priority
from pbl4.runtime.process import _AttemptRunner, RuntimeProcess
from pbl4.runtime.runtime_events import RuntimeEvent


class _MockProcess:
    def __init__(self) -> None:
        self._stopping = threading.Event()


class _MockManagement:
    def __init__(self) -> None:
        self.backend_connected = True
        self.sent_events: list[dict[str, object]] = []
        self.send_handler = None
        self._lock = threading.Lock()

    def send_runtime_event(self, event: dict[str, object]) -> bool:
        with self._lock:
            if self.send_handler is not None:
                res = self.send_handler(event)
                if res is not None:
                    if res:
                        self.sent_events.append(dict(event))
                    return bool(res)
            self.sent_events.append(dict(event))
            return True


class TestEventForwarding(unittest.TestCase):
    def test_inject_send_failure_keeps_subsequent_events_queued(self) -> None:
        """Inject send failure after event 1 -> event 2 remains safely queued."""
        mock_mgmt = _MockManagement()
        mock_proc = _MockProcess()
        runner = _AttemptRunner(
            process=mock_proc,  # type: ignore[arg-type]
            payload={"job_id": "job-1", "attempt_id": "attempt-1"},
            management=mock_mgmt,  # type: ignore[arg-type]
        )
        emitter = EventEmitter("attempt-1", "job-1", capacity=10)
        runner._events = emitter

        ev1 = emitter.emit("step.started", {"step_id": 1}, "2026-09-28T00:00:00Z")
        ev2 = emitter.emit("checkpoint.saved", {"checkpoint_id": "cp-1"}, "2026-09-28T00:00:01Z")

        call_count = 0

        def send_handler(event: dict[str, object]) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return True
            # Inject failure on event 2
            return False

        mock_mgmt.send_handler = send_handler

        runner._event_thread.start()
        # Give event thread enough time to attempt the batch
        time.sleep(0.15)

        with mock_mgmt._lock:
            # Event 1 was sent successfully
            self.assertEqual(len(mock_mgmt.sent_events), 1)
            self.assertEqual(mock_mgmt.sent_events[0]["runtime_event_seq"], 1)

        # Event 2 was NOT acked and remains at head of queue
        snapshot = emitter.snapshot()
        self.assertEqual(snapshot["queued_event_count"], 1)
        peeked = emitter.peek()
        self.assertEqual(len(peeked), 1)
        self.assertEqual(peeked[0].runtime_event_seq, 2)
        self.assertEqual(peeked[0].event_type, "checkpoint.saved")

        mock_proc._stopping.set()
        runner._event_thread.join(timeout=1.0)

    def test_reconnect_retries_remaining_events_in_exact_seq(self) -> None:
        """Reconnect -> remaining events are sent in exact seq without gap or duplication."""
        mock_mgmt = _MockManagement()
        mock_proc = _MockProcess()
        runner = _AttemptRunner(
            process=mock_proc,  # type: ignore[arg-type]
            payload={"job_id": "job-1", "attempt_id": "attempt-1"},
            management=mock_mgmt,  # type: ignore[arg-type]
        )
        emitter = EventEmitter("attempt-1", "job-1", capacity=10)
        runner._events = emitter

        emitter.emit("step.started", {"step_id": 1}, "2026-09-28T00:00:00Z")
        emitter.emit("checkpoint.saved", {"checkpoint_id": "cp-1"}, "2026-09-28T00:00:01Z")

        fail_event_2 = True

        def send_handler(event: dict[str, object]) -> bool:
            if event["runtime_event_seq"] == 2 and fail_event_2:
                return False
            return True

        mock_mgmt.send_handler = send_handler
        runner._event_thread.start()

        # Wait for event 1 to succeed and event 2 to fail
        time.sleep(0.15)
        self.assertEqual(len(mock_mgmt.sent_events), 1)
        self.assertEqual(emitter.snapshot()["queued_event_count"], 1)

        # Reconnect simulated: event 2 now succeeds
        fail_event_2 = False

        # Wait for retry
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if emitter.snapshot()["queued_event_count"] == 0:
                break
            time.sleep(0.05)

        self.assertEqual(emitter.snapshot()["queued_event_count"], 0)
        self.assertEqual(len(mock_mgmt.sent_events), 2)
        self.assertEqual(mock_mgmt.sent_events[0]["runtime_event_seq"], 1)
        self.assertEqual(mock_mgmt.sent_events[1]["runtime_event_seq"], 2)
        self.assertEqual(mock_mgmt.sent_events[1]["event_type"], "checkpoint.saved")

        mock_proc._stopping.set()
        runner._event_thread.join(timeout=1.0)

    def test_terminal_event_completed_not_lost_when_mcp_disconnected(self) -> None:
        """Terminal event COMPLETED is preserved in queue and delivered upon reconnect."""
        mock_mgmt = _MockManagement()
        mock_proc = _MockProcess()
        # MCP is initially disconnected
        mock_mgmt.backend_connected = False

        runner = _AttemptRunner(
            process=mock_proc,  # type: ignore[arg-type]
            payload={"job_id": "job-1", "attempt_id": "attempt-1"},
            management=mock_mgmt,  # type: ignore[arg-type]
        )
        emitter = EventEmitter("attempt-1", "job-1", capacity=10)
        runner._events = emitter

        # Emit checkpoint and COMPLETED
        emitter.emit("checkpoint.saved", {"checkpoint_id": "cp-final"}, "2026-09-28T00:00:00Z")
        emitter.emit(
            "attempt.state_changed",
            {"previous_state": "RUNNING", "state": "COMPLETED"},
            "2026-09-28T00:00:01Z",
        )

        # Mark attempt runner terminal
        runner._set_state("COMPLETED")
        self.assertTrue(runner.terminal)

        # Start event forward thread
        runner._event_thread.start()

        # Wait a short while: event thread should NOT terminate because queued_event_count > 0
        time.sleep(0.2)
        self.assertTrue(runner._event_thread.is_alive())
        self.assertEqual(emitter.snapshot()["queued_event_count"], 2)
        self.assertEqual(len(mock_mgmt.sent_events), 0)

        # MCP reconnects
        mock_mgmt.backend_connected = True

        # Event thread should forward both events, ack them, and cleanly terminate
        runner._event_thread.join(timeout=2.0)
        self.assertFalse(runner._event_thread.is_alive())

        # Verify both events received in order
        self.assertEqual(len(mock_mgmt.sent_events), 2)
        self.assertEqual(mock_mgmt.sent_events[0]["event_type"], "checkpoint.saved")
        self.assertEqual(mock_mgmt.sent_events[1]["event_type"], "attempt.state_changed")
        self.assertEqual(mock_mgmt.sent_events[1]["details"]["state"], "COMPLETED")
        self.assertEqual(emitter.snapshot()["queued_event_count"], 0)

    def test_priority_eviction_preserves_checkpoints_and_terminal_events(self) -> None:
        """Queue capacity overflow drops metrics first, step second, never terminal."""
        emitter = EventEmitter("attempt-1", "job-1", capacity=3)

        emitter.emit("metric.sample", {"compute_ms": 10}, "now")
        emitter.emit("metric.sample", {"compute_ms": 20}, "now")
        emitter.emit("step.started", {"step_id": 1}, "now")
        self.assertEqual(emitter.snapshot()["queued_event_count"], 3)

        # Emitting checkpoint.saved (priority 2) evicts oldest metric.sample (priority 0)
        emitter.emit("checkpoint.saved", {"checkpoint_id": "cp-1"}, "now")
        self.assertEqual(emitter.snapshot()["queued_event_count"], 3)
        self.assertEqual(emitter.snapshot()["dropped_event_count"], 1)

        # Emitting COMPLETED (priority 3) evicts remaining metric.sample (priority 0)
        emitter.emit(
            "attempt.state_changed",
            {"previous_state": "RUNNING", "state": "COMPLETED"},
            "now",
        )
        self.assertEqual(emitter.snapshot()["queued_event_count"], 3)
        self.assertEqual(emitter.snapshot()["dropped_event_count"], 2)

        # Emitting a new metric.sample (priority 0) when queue has [step, checkpoint, COMPLETED]
        # (priorities 1, 2, 3) must drop the incoming metric sample, NOT any queued event
        emitter.emit("metric.sample", {"compute_ms": 30}, "now")
        self.assertEqual(emitter.snapshot()["dropped_event_count"], 3)

        peeked = emitter.peek()
        types = [e.event_type for e in peeked]
        self.assertEqual(types, ["step.started", "checkpoint.saved", "attempt.state_changed"])
        self.assertEqual(peeked[2].details["state"], "COMPLETED")
        # Ensure sequence order is strictly ascending
        seqs = [e.runtime_event_seq for e in peeked]
        self.assertEqual(seqs, sorted(seqs))

    def test_event_emitter_peek_and_ack(self) -> None:
        """Peek is non-destructive and ack cleans up correctly."""
        emitter = EventEmitter("attempt-1", "job-1", capacity=10)
        emitter.emit("step.started", {"step_id": 1}, "now")
        emitter.emit("step.started", {"step_id": 2}, "now")
        emitter.emit("step.started", {"step_id": 3}, "now")

        # Peek without limit
        p_all = emitter.peek()
        self.assertEqual(len(p_all), 3)
        self.assertEqual(emitter.snapshot()["queued_event_count"], 3)

        # Peek with limit
        p_two = emitter.peek(limit=2)
        self.assertEqual(len(p_two), 2)
        self.assertEqual([e.runtime_event_seq for e in p_two], [1, 2])

        # Ack seq 2 -> removes seq 1 and seq 2
        self.assertTrue(emitter.ack(2))
        self.assertEqual(emitter.snapshot()["queued_event_count"], 1)
        remaining = emitter.peek()
        self.assertEqual([e.runtime_event_seq for e in remaining], [3])

        # Ack non-existent seq
        self.assertFalse(emitter.ack(99))

        # Ack seq 3 -> queue empty
        self.assertTrue(emitter.ack(3))
        self.assertEqual(emitter.snapshot()["queued_event_count"], 0)

    def test_clean_shutdown_terminates_forwarding_thread(self) -> None:
        """RuntimeProcess shutdown stops event forwarding thread even if events remain."""
        mock_mgmt = _MockManagement()
        mock_proc = _MockProcess()
        mock_mgmt.backend_connected = False

        runner = _AttemptRunner(
            process=mock_proc,  # type: ignore[arg-type]
            payload={"job_id": "job-1", "attempt_id": "attempt-1"},
            management=mock_mgmt,  # type: ignore[arg-type]
        )
        emitter = EventEmitter("attempt-1", "job-1", capacity=10)
        runner._events = emitter
        emitter.emit("step.started", {"step_id": 1}, "now")

        runner._event_thread.start()
        time.sleep(0.1)
        self.assertTrue(runner._event_thread.is_alive())

        mock_proc._stopping.set()
        runner._event_thread.join(timeout=1.0)
        self.assertFalse(runner._event_thread.is_alive())
