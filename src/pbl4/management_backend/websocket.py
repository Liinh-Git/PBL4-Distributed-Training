"""WebSocket handler — /ws/v1/attempts/{attempt_id}

Per DATA_FLOW_SPECIFICATION.md:
  Runtime → MCP/1 → Backend → WebSocket → Frontend

This handler:
  1. Validates the attempt exists.
  2. Subscribes the client to the attempt's broadcast channel.
  3. Delivers events pushed by the RuntimeGateway (or management events) in real time.
  4. Handles client disconnect cleanly.

V1 status: runtime not connected → only management-sourced events are delivered.
Clients receive JSON messages with a 'type' and 'data' envelope.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

logger = logging.getLogger(__name__)

# ─── Broadcast Hub ────────────────────────────────────────────────────────────

class AttemptBroadcastHub:
    """In-process pub/sub for WebSocket clients subscribed to a given attempt_id.

    Thread-safe via asyncio — all operations must run in the event loop.
    """

    def __init__(self) -> None:
        # attempt_id → set of asyncio.Queue instances (one per connected client)
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

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
                    "WebSocket queue full for attempt %s; dropping message.", attempt_id
                )

    def subscriber_count(self, attempt_id: str) -> int:
        return len(self._subscribers.get(attempt_id, set()))


# Module-level hub singleton
hub = AttemptBroadcastHub()


# ─── WebSocket Endpoint ───────────────────────────────────────────────────────

async def _attempt_ws(websocket: WebSocket, attempt_id: str) -> None:
    """Handle a single WebSocket connection for an attempt."""
    from management_backend import db
    from management_backend.repositories import attempt_repository

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
    logger.info("WebSocket connected: attempt=%s", attempt_id)

    # Send initial "connected" frame
    await websocket.send_json({
        "type": "CONNECTED",
        "data": {
            "attempt_id": attempt_id,
            "attempt_state": attempt["state"],
            "stale": True,
            "message": "Connected. Runtime not yet active; live events will arrive when runtime connects.",
        },
    })

    q = hub.subscribe(attempt_id)
    try:
        while True:
            # Wait for either a message from the hub or a client disconnect
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
                    # Handle ping/pong if client sends {"type":"PING"}
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
        try:
            await websocket.close()
        except Exception:
            pass


def register_websocket_routes(app: FastAPI) -> None:
    """Register WebSocket routes on the FastAPI application."""

    @app.websocket("/ws/v1/attempts/{attempt_id}")
    async def attempt_ws(websocket: WebSocket, attempt_id: str) -> None:
        await _attempt_ws(websocket, attempt_id)
