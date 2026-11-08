"""In-memory event batcher for MCP/1 telemetry stream when Redis is not used."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class McpEventConsumer:
    """Consumes MCP/1 runtime events, batches them in memory, and commits via SQL transaction."""

    def __init__(
        self,
        ingest: Callable[[list[dict[str, Any]]], int],
        *,
        batch_size: int = 50,
        max_wait: float = 0.010,  # 10ms collection window
    ) -> None:
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._ingest = ingest
        self._batch_size = batch_size
        self._max_wait = max_wait
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mcp-events", daemon=True)

    def enqueue(self, payload: dict[str, Any]) -> None:
        """Non-blocking enqueue from MCP dispatch thread."""
        self._queue.put(payload)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        # Wake up worker thread
        self._queue.put({})
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                first = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._stopping.is_set() or not first:
                break

            batch = [first]
            deadline = time.monotonic() + self._max_wait

            # Collect subsequent events until batch_size or deadline
            while len(batch) < self._batch_size:
                timeout = max(0.0, deadline - time.monotonic())
                if timeout <= 0.0:
                    break
                try:
                    item = self._queue.get(timeout=timeout)
                    if self._stopping.is_set() or not item:
                        break
                    batch.append(item)
                    # Immediate flush on lifecycle state changes
                    if (
                        item.get("event_type") == "attempt.state_changed"
                        and item.get("details", {}).get("state")
                        in {"RUNNING", "COMPLETED", "FAILED", "ABORTED"}
                    ):
                        break
                except queue.Empty:
                    break

            if batch:
                try:
                    self._ingest(batch)
                except Exception as exc:
                    logger.error("Error ingesting MCP in-memory event batch: %s", exc)
