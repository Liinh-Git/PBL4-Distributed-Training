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

        with db.get_connection() as conn:
            latest_seq = event_repository.get_latest_runtime_event_seq(conn, attempt_id) or 0

            if after_seq is not None:
                # Multi-page catch-up: fetch all pages (> 200 events) without silent truncation
                missed_events: list[dict] = []
                curr_cursor = after_seq
                batch_size = 200
                while True:
                    batch = event_repository.list_events_after_seq(
                        conn, attempt_id, curr_cursor, limit=batch_size
                    )
                    if not batch:
                        break
                    missed_events.extend(batch)
                    curr_cursor = batch[-1].get("runtime_event_seq")
                    if len(batch) < batch_size or curr_cursor is None:
                        break

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
                        seq = e["runtime_event_seq"]
                        last_contiguous_sent_seq = seq
                        e_occurred = (
                            e["occurred_at"].isoformat()
                            if hasattr(e["occurred_at"], "isoformat")
                            else str(e["occurred_at"])
                        )
                        payload_data = e.get("payload_jsonb") or {}
                        if isinstance(payload_data, str):
                            with contextlib.suppress(Exception):
                                payload_data = json.loads(payload_data)
                        await websocket.send_json(
                            {
                                "kind": "EVENT",
                                "attempt_id": attempt_id,
                                "runtime_event_seq": seq,
                                "occurred_at": e_occurred,
                                "payload": {
                                    "event_type": e["event_type"],
                                    "severity": e["severity"],
                                    "source_component": e.get("source_component", "Runtime"),
                                    **payload_data,
                                },
                            }
                        )
                else:
                    # Discontinuous history requested:
                    # send actual reconciled Runtime SNAPSHOT@M + GAP
                    gw = get_gateway()
                    runtime_snap = gw.get_authoritative_snapshot(attempt_id)
                    now_str = datetime.now(UTC).isoformat()
                    snap_seq = None
                    if runtime_snap is not None:
                        snap_seq = runtime_snap["authoritative_snapshot_seq"]
                        if snap_seq is not None:
                            last_contiguous_sent_seq = snap_seq
                        await websocket.send_json(
                            {
                                "kind": "SNAPSHOT",
                                "attempt_id": attempt_id,
                                "runtime_event_seq": snap_seq,
                                "occurred_at": now_str,
                                "payload": runtime_snap,
                            }
                        )
                    await websocket.send_json(
                        {
                            "kind": "GAP",
                            "attempt_id": attempt_id,
                            "runtime_event_seq": None,
                            "occurred_at": now_str,
                            "payload": {
                                "after_seq": after_seq,
                                "authoritative_seq": snap_seq,
                                "snapshot_required": True,
                                "reason": f"Discontinuous history requested after_seq={after_seq}",
                            },
                        }
                    )
            else:
                # New connection without after_seq: send authoritative SNAPSHOT if available
                gw = get_gateway()
                runtime_snap = gw.get_authoritative_snapshot(attempt_id)
                if runtime_snap is not None:
                    snap_seq = runtime_snap["authoritative_snapshot_seq"]
                    if snap_seq is not None:
                        last_contiguous_sent_seq = snap_seq
                    now_str = datetime.now(UTC).isoformat()
                    await websocket.send_json(
                        {
                            "kind": "SNAPSHOT",
                            "attempt_id": attempt_id,
                            "runtime_event_seq": snap_seq,
                            "occurred_at": now_str,
                            "payload": runtime_snap,
                        }
                    )

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
                        if msg.get("kind") == "PING":
                            await websocket.send_json({"kind": "PONG"})
                    except (json.JSONDecodeError, AttributeError):
                        pass
                except WebSocketDisconnect:
                    break
                except Exception:
                    break

            if queue_task in done:
                try:
                    event = queue_task.result()
                    if isinstance(event, dict) and event.get("kind") == "OVERFLOW_INVALIDATE":
                        logger.warning(
                            "Closing WebSocket for %s due to backpressure overflow.",
                            attempt_id,
                        )
                        await websocket.close(
                            code=status.WS_1008_POLICY_VIOLATION,
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
                                    code=status.WS_1008_POLICY_VIOLATION,
                                    reason="Pending buffer overflow: unresolvable live gap",
                                )
                                break
                    elif isinstance(event, dict) and event.get("kind") == "SNAPSHOT":
                        s_seq = event.get("runtime_event_seq")
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
