"""WebSocket handler — /ws/v1/attempts/{attempt_id}

Per DATA_FLOW_SPECIFICATION.md:
  Runtime → MCP/1 → Backend → WebSocket → Frontend

Guarantees:
  1. Validates attempt exists.
  2. Supports reconnection with ?after_seq=<seq>.
     - If contiguous history exists, streams missed events.
     - If history is discontinuous or truncated: sends SNAPSHOT -> GAP frames.
  3. Delivers events pushed by RuntimeGateway or Management plane in real time.
  4. Manages backpressure: overflows close connection cleanly with directive to reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.services.event_ingest import snapshot_frame

logger = logging.getLogger(__name__)

# ─── Broadcast Hub ────────────────────────────────────────────────────────────


class AttemptBroadcastHub:
    """In-process pub/sub for WebSocket clients subscribed to a given attempt_id."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._dirty: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._background_tasks: set[asyncio.Task] = set()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, attempt_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.setdefault(attempt_id, set()).add(q)
        return q

    def unsubscribe(self, attempt_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(attempt_id)
        if subs:
            subs.discard(q)
            self._dirty.discard(q)
            if not subs:
                del self._subscribers[attempt_id]

    async def broadcast(self, attempt_id: str, message: dict[str, Any]) -> None:
        """Push a message to all clients subscribed to attempt_id."""
        subs = self._subscribers.get(attempt_id, set())
        for q in list(subs):
            if q in self._dirty:
                continue
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "WebSocket queue full for attempt %s; invalidating semantic stream.",
                    attempt_id,
                )
                self._dirty.add(q)
                with contextlib.suppress(Exception):
                    while not q.empty():
                        q.get_nowait()
                    q.put_nowait({"kind": "OVERFLOW_INVALIDATE"})

    def broadcast_sync(self, attempt_id: str, message: dict[str, Any]) -> None:
        """Thread-safe and sync-context broadcast dispatch."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(attempt_id, message), self._loop)
        else:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self.broadcast(attempt_id, message))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                pass

    def subscriber_count(self, attempt_id: str) -> int:
        return len(self._subscribers.get(attempt_id, set()))


hub = AttemptBroadcastHub()


# ─── WebSocket Endpoint ───────────────────────────────────────────────────────


async def _attempt_ws(websocket: WebSocket, attempt_id: str) -> None:
    """Handle a single WebSocket connection for an attempt."""
    from pbl4.management_backend import db
    from pbl4.management_backend.repositories import attempt_repository, event_repository

    # Validate attempt existence
    try:

        def read_attempt():
            with db.get_connection() as conn:
                return attempt_repository.get_attempt(conn, attempt_id)

        attempt = await asyncio.to_thread(read_attempt)
    except Exception as exc:
        logger.error("DB error during WebSocket validation for %s: %s", attempt_id, exc)
        await websocket.close(code=1011, reason="Database unavailable")
        return

    if attempt is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Attempt not found")
        return

    await websocket.accept()
    hub.set_loop(asyncio.get_running_loop())
    logger.info("WebSocket connected: attempt=%s", attempt_id)

    # Subscribe to live hub FIRST before querying persisted catch-up history
    # to eliminate any race condition where live events arriving during DB catch-up are lost.
    q = hub.subscribe(attempt_id)
    last_contiguous_sent_seq: int | None = None
    pending_live_events: dict[int, dict] = {}

    try:
        # Check for after_seq query parameter for reconnection catch-up
        after_seq_raw = websocket.query_params.get("after_seq")
        after_seq: int | None = None
        if after_seq_raw is not None:
            with contextlib.suppress(ValueError):
                after_seq = int(after_seq_raw)

        if after_seq is not None:
            last_contiguous_sent_seq = after_seq

        def read_page(cursor: int):
            with db.get_connection() as conn:
                return event_repository.list_events_after_seq(conn, attempt_id, cursor, limit=200)

        def latest_sequence():
            with db.get_connection() as conn:
                return event_repository.get_latest_runtime_event_seq(conn, attempt_id) or 0

        gap = False
        if after_seq is not None:
            # Capture a finite target; release each SQL connection before network
            # writes. Memory stays one page even for a long reconnect backlog.
            target = await asyncio.to_thread(latest_sequence)
            cursor = after_seq
            while cursor < target:
                before = cursor
                page = await asyncio.to_thread(read_page, cursor)
                if not page:
                    gap = True
                    break
                for row in page:
                    seq = row["runtime_event_seq"]
                    if seq > target:
                        break
                    if seq != cursor + 1:
                        gap = True
                        break
                    details = row.get("payload_jsonb") or {}
                    if isinstance(details, str):
                        details = json.loads(details)
                    occurred = row["occurred_at"]
                    await websocket.send_json(
                        {
                            "kind": "EVENT",
                            "attempt_id": attempt_id,
                            "runtime_event_seq": seq,
                            "occurred_at": occurred.isoformat()
                            if hasattr(occurred, "isoformat")
                            else str(occurred),
                            "payload": {
                                "event_type": row["event_type"],
                                "event_schema_version": 1,
                                "severity": row["severity"],
                                "source_component": row.get("source_component", "Runtime"),
                                "details": details,
                            },
                        }
                    )
                    cursor = seq
                    last_contiguous_sent_seq = seq
                if gap or cursor == before:
                    gap = True
                    break

        if gap or after_seq is None:
            runtime_snap = get_gateway().get_authoritative_snapshot(attempt_id)
            if runtime_snap is not None:
                last_contiguous_sent_seq = runtime_snap["authoritative_snapshot_seq"]
                await websocket.send_json(snapshot_frame(runtime_snap))
            if gap:
                await websocket.send_json(
                    {
                        "kind": "GAP",
                        "attempt_id": attempt_id,
                        "runtime_event_seq": None,
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "payload": {
                            "after_seq": after_seq,
                            "snapshot_required": True,
                            "reason": "Discontinuous persisted history",
                        },
                    }
                )

        while True:
            recv_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(q.get())

            _, pending = await asyncio.wait(
                [recv_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            # A pending task can finish after wait() returns but before cancel().
            # Inspect its final state so a consumed frame/event is never dropped.
            if recv_task.done() and not recv_task.cancelled():
                try:
                    text = recv_task.result()
                    try:
                        msg = json.loads(text)
                        if msg.get("kind") == "PING":
                            await websocket.send_json({"kind": "PONG"})
                    except (json.JSONDecodeError, AttributeError):
                        pass
                except WebSocketDisconnect:
                    break
                except Exception:
                    break

            if queue_task.done() and not queue_task.cancelled():
                try:
                    event = queue_task.result()
                    if isinstance(event, dict) and event.get("kind") == "OVERFLOW_INVALIDATE":
                        logger.warning(
                            "Closing WebSocket for %s due to backpressure overflow.",
                            attempt_id,
                        )
                        await websocket.close(
                            code=1013,
                            reason="Backpressure overflow: reconnect with highest contiguous seq",
                        )
                        break

                    if isinstance(event, dict) and event.get("kind") == "EVENT":
                        e_seq = event.get("runtime_event_seq")
                        if e_seq is None:
                            await websocket.send_json(event)
                            continue

                        baseline = (
                            last_contiguous_sent_seq if last_contiguous_sent_seq is not None else 0
                        )

                        if e_seq <= baseline:
                            # CASE A: duplicate / already replayed -> ignore
                            continue
                        elif e_seq == baseline + 1:
                            # CASE B: exactly contiguous -> send and drain buffer
                            await websocket.send_json(event)
                            last_contiguous_sent_seq = e_seq
                            while (
                                last_contiguous_sent_seq is not None
                                and (last_contiguous_sent_seq + 1) in pending_live_events
                            ):
                                next_seq = last_contiguous_sent_seq + 1
                                next_ev = pending_live_events.pop(next_seq)
                                await websocket.send_json(next_ev)
                                last_contiguous_sent_seq = next_seq
                        else:
                            # CASE C: out-of-order future event -> buffer without sending
                            pending_live_events[e_seq] = event
                            if len(pending_live_events) > 500:
                                logger.warning(
                                    "Closing WebSocket for %s: pending buffer overflow",
                                    attempt_id,
                                )
                                await websocket.close(
                                    code=1013,
                                    reason="Pending buffer overflow: unresolvable live gap",
                                )
                                break
                    elif isinstance(event, dict) and event.get("kind") == "SNAPSHOT":
                        s_seq = event.get("payload", {}).get("snapshot_seq")
                        if s_seq is not None:
                            last_contiguous_sent_seq = s_seq
                            # Discard buffered events with seq <= s_seq
                            pending_live_events = {
                                seq: ev for seq, ev in pending_live_events.items() if seq > s_seq
                            }
                        await websocket.send_json(event)
                        while (
                            last_contiguous_sent_seq is not None
                            and (last_contiguous_sent_seq + 1) in pending_live_events
                        ):
                            next_seq = last_contiguous_sent_seq + 1
                            next_ev = pending_live_events.pop(next_seq)
                            await websocket.send_json(next_ev)
                            last_contiguous_sent_seq = next_seq
                    else:
                        await websocket.send_json(event)
                except Exception as exc:
                    logger.warning("WebSocket send failed for %s: %s", attempt_id, exc)
                    break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error for attempt %s: %s", attempt_id, exc)
    finally:
        hub.unsubscribe(attempt_id, q)
        logger.info("WebSocket disconnected: attempt=%s", attempt_id)
        with contextlib.suppress(Exception):
            await websocket.close()


def register_websocket_routes(app: FastAPI) -> None:
    """Register WebSocket routes on the FastAPI application."""

    @app.websocket("/ws/v1/attempts/{attempt_id}")
    async def attempt_ws(websocket: WebSocket, attempt_id: str) -> None:
        await _attempt_ws(websocket, attempt_id)
