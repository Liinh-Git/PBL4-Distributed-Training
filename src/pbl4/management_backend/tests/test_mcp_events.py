from __future__ import annotations

import threading
from typing import Any

from pbl4.management_backend.gateways.mcp_events import McpEventConsumer


def test_mcp_event_consumer_batches_and_flushes() -> None:
    received_batches: list[list[dict[str, Any]]] = []
    flush_event = threading.Event()

    def fake_ingest(batch: list[dict[str, Any]]) -> int:
        received_batches.append(batch)
        if len(received_batches) == 1:
            flush_event.set()
        return len(batch)

    consumer = McpEventConsumer(fake_ingest, batch_size=10, max_wait=0.02)
    consumer.start()
    try:
        consumer.enqueue({"event_type": "step.started", "runtime_event_seq": 1})
        consumer.enqueue({"event_type": "step.committed", "runtime_event_seq": 2})

        assert flush_event.wait(timeout=1.0)
        assert len(received_batches) >= 1
        assert len(received_batches[0]) == 2
        assert [e["runtime_event_seq"] for e in received_batches[0]] == [1, 2]
    finally:
        consumer.stop()


def test_mcp_event_consumer_flushes_immediately_on_state_change() -> None:
    received_batches: list[list[dict[str, Any]]] = []
    flush_event = threading.Event()

    def fake_ingest(batch: list[dict[str, Any]]) -> int:
        received_batches.append(batch)
        flush_event.set()
        return len(batch)

    # Use a long max_wait (2.0s) so flush can ONLY happen immediately due to state change
    consumer = McpEventConsumer(fake_ingest, batch_size=100, max_wait=2.0)
    consumer.start()
    try:
        consumer.enqueue({"event_type": "step.started", "runtime_event_seq": 1})
        consumer.enqueue(
            {
                "event_type": "attempt.state_changed",
                "runtime_event_seq": 2,
                "details": {"state": "RUNNING"},
            }
        )

        assert flush_event.wait(timeout=0.5)
        assert len(received_batches) >= 1
        assert len(received_batches[0]) == 2
    finally:
        consumer.stop()


def test_mcp_event_consumer_flushes_on_max_batch_size() -> None:
    received_batches: list[list[dict[str, Any]]] = []
    flush_event = threading.Event()

    def fake_ingest(batch: list[dict[str, Any]]) -> int:
        received_batches.append(batch)
        flush_event.set()
        return len(batch)

    # Use batch_size = 3 and long max_wait
    consumer = McpEventConsumer(fake_ingest, batch_size=3, max_wait=2.0)
    consumer.start()
    try:
        for i in range(1, 4):
            consumer.enqueue({"event_type": "step.started", "runtime_event_seq": i})

        assert flush_event.wait(timeout=0.5)
        assert len(received_batches) >= 1
        assert len(received_batches[0]) == 3
    finally:
        consumer.stop()
