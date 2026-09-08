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
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from pbl4.management_backend.gateways.runtime_gateway import get_gateway

logger = logging.getLogger(__name__)

# ─── Broadcast Hub ────────────────────────────────────────────────────────────


class AttemptBroadcastHub:
    """In-process pub/sub for WebSocket clients subscribed to a given attempt_id."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
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
            if not subs:
                del self._subscribers[attempt_id]

    async def broadcast(self, attempt_id: str, message: dict[str, Any]) -> None:
        """Push a message to all clients subscribed to attempt_id."""
        subs = self._subscribers.get(attempt_id, set())
        for q in list(subs):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning(
                    "WebSocket queue full for attempt %s; sending overflow sentinel.",
                    attempt_id,
                )
                with contextlib.suppress(Exception):
                    q.get_nowait()
                    q.put_nowait({"type": "BACKPRESSURE_OVERFLOW"})

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
    from pbl4.management_backend.services import attempt_service

    # Validate attempt existence
    try:
        with db.get_connection() as conn:
            attempt = attempt_repository.get_attempt(conn, attempt_id)
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

    # Check for after_seq query parameter for reconnection catch-up
    after_seq_raw = websocket.query_params.get("after_seq")
    after_seq: int | None = None
    if after_seq_raw is not None:
        with contextlib.suppress(ValueError):
            after_seq = int(after_seq_raw)

    latest_seq: int = 0
    with db.get_connection() as conn:
        latest_seq = event_repository.get_latest_runtime_event_seq(conn, attempt_id) or 0

        if after_seq is not None:
            missed_events = event_repository.list_events_after_seq(
                conn, attempt_id, after_seq, limit=200
            )
            # Check if missed events form a contiguous sequence from after_seq + 1
            is_contiguous = False
            if missed_events:
                first_seq = missed_events[0].get("runtime_event_seq")
                if first_seq == after_seq + 1:
                    is_contiguous = True
                    curr = first_seq
                    for e in missed_events[1:]:
                        seq = e.get("runtime_event_seq")
                        if seq != curr + 1:
                            is_contiguous = False
                            break
                        curr = seq
            elif after_seq >= latest_seq:
                is_contiguous = True  # Already caught up

            if is_contiguous:
                for e in missed_events:
                    await websocket.send_json(
                        {
                            "type": "RUNTIME_EVENT",
                            "data": {
                                "attempt_id": attempt_id,
                                "runtime_event_seq": e["runtime_event_seq"],
                                "event_type": e["event_type"],
                                "occurred_at": (
                                    e["occurred_at"].isoformat()
                                    if hasattr(e["occurred_at"], "isoformat")
                                    else str(e["occurred_at"])
                                ),
                                "source_component": e.get("source_component", "Runtime"),
                                "severity": e["severity"],
                                "payload": e.get("payload_jsonb"),
                            },
                        }
                    )
            else:
                # Discontinuous history requested: send SNAPSHOT -> GAP frames
                snap = attempt_service.get_attempt_snapshot(conn, attempt_id)
                await websocket.send_json(
                    {
                        "type": "SNAPSHOT",
                        "data": {
                            "attempt_id": attempt_id,
                            "snapshot_seq": latest_seq,
                            "snapshot": snap,
                        },
                    }
                )
                await websocket.send_json(
                    {
                        "type": "GAP",
                        "data": {
                            "attempt_id": attempt_id,
                            "snapshot_seq": latest_seq,
                            "reason": f"Discontinuous history requested after_seq={after_seq}",
                        },
                    }
                )

    # Send initial "CONNECTED" frame
    await websocket.send_json(
        {
            "type": "CONNECTED",
            "data": {
                "attempt_id": attempt_id,
                "attempt_state": attempt["state"],
                "highest_contiguous_seq": latest_seq,
                "stale": not get_gateway().connected,
                "message": "Connected to attempt stream.",
            },
        }
    )

    q = hub.subscribe(attempt_id)
    try:
        while True:
            recv_task = asyncio.create_task(websocket.receive_text())
            queue_task = asyncio.create_task(q.get())

            done, pending = await asyncio.wait(
                [recv_task, queue_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            if recv_task in done:
                try:
                    text = recv_task.result()
                    try:
                        msg = json.loads(text)
                        if msg.get("type") == "PING":
                            await websocket.send_json({"type": "PONG"})
                    except (json.JSONDecodeError, AttributeError):
                        pass
                except WebSocketDisconnect:
                    break
                except Exception:
                    break

            if queue_task in done:
                try:
                    event = queue_task.result()
                    if isinstance(event, dict) and event.get("type") == "BACKPRESSURE_OVERFLOW":
                        logger.warning(
                            "Closing WebSocket for %s due to backpressure overflow.",
                            attempt_id,
                        )
                        await websocket.close(
                            code=1008,
                            reason="Backpressure overflow: reconnect with highestContiguousSeq",
                        )
                        break
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
