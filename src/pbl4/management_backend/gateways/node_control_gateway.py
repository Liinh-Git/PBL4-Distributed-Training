"""Node Control Gateway — WSS control plane connection and command dispatch boundary.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Responsibilities:
- Accept outbound WSS connections from Node Agents at:
  `/ws/v1/nodes/{node_id}/control`
- Authenticate `Authorization: Bearer <node_secret>` strictly BEFORE accepting logical session.
- Reject invalid secrets, non-existent nodes, and REVOKED nodes.
- Maintain `node_id -> active websocket` mapping (strictly ONE active control connection per node).
- Process inbound agent protocol messages:
  * AGENT_HELLO -> validate, update node metadata, transition OFFLINE -> ONLINE, reply HELLO_ACK.
  * HEARTBEAT -> validate, update last_seen_at, idempotent.
  * RESOURCE_SNAPSHOT -> validate, persist latest_resources telemetry.
  * COMMAND_ACK -> ACCEPTED keeps DISPATCHED; REJECTED transitions to FAILED.
  * WORKER_STATUS -> STARTED, ENDED, FAILED mapped directly to allocation actual_state.
- Outbound command dispatch:
  * START_WORKER -> send COMMAND envelope to target node's active websocket.
  * STOP_WORKER -> send COMMAND envelope to target node's active websocket.
- On disconnect: remove from active map WITHOUT marking node OFFLINE.
  Stale maintenance owns the OFFLINE transition.
- On revoke: close active WSS cleanly without stopping workers or aborting attempts.
- Strict isolation: never proxy Runtime/Worker internals, DTP/1, tensors, or gradients.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect, status

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    MESSAGE_TYPE_AGENT_HELLO,
    MESSAGE_TYPE_COMMAND,
    MESSAGE_TYPE_COMMAND_ACK,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_RESOURCE_SNAPSHOT,
    MESSAGE_TYPE_WORKER_STATUS,
    WORKER_ACTUAL_STATE_ENDED,
    WORKER_ACTUAL_STATE_FAILED,
    WORKER_ACTUAL_STATE_STARTED,
    AgentEnvelope,
    AgentHelloPayload,
    AgentMessageError,
    CommandAckPayload,
    HeartbeatPayload,
    HelloAckPayload,
    ResourceSnapshotPayload,
    StartWorkerPayload,
    StopWorkerPayload,
    WorkerStatusPayload,
    parse_agent_envelope,
)
from pbl4.management_backend import db
from pbl4.management_backend.config import get_settings
from pbl4.management_backend.services import (
    allocation_service,
    node_service,
)
from pbl4.management_backend.services.allocation_service import (
    AllocationNotFoundError,
    NodeControlGatewayProtocol,
)
from pbl4.management_backend.services.node_service import (
    NodeNotFoundError,
    NodeRevokedError,
    NodeUnauthorizedError,
)

logger = logging.getLogger(__name__)


class NodeControlGateway(NodeControlGatewayProtocol):
    """Manage outbound control channels and bidirectional Node Agent messages."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_connections: dict[str, WebSocket] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the running asyncio event loop for threadsafe dispatch."""
        self._loop = loop

    def get_active_node_ids(self) -> list[str]:
        """Return list of node IDs currently holding active WebSocket connections."""
        with self._lock:
            return list(self._active_connections.keys())

    def is_node_connected(self, node_id: str) -> bool:
        """Check whether target node holds an active WebSocket session."""
        with self._lock:
            return node_id in self._active_connections

    # ─── WSS Connection Lifecycle ─────────────────────────────────────────────

    async def handle_websocket_connection(self, websocket: WebSocket, node_id: str) -> None:
        """Authenticate and serve one logical WSS session for a node."""
        # 1. Capture event loop reference
        self._loop = asyncio.get_running_loop()

        # 2. Extract Bearer node_secret from Authorization header (or query param fallback)
        auth_header = websocket.headers.get("authorization") or websocket.headers.get(
            "Authorization"
        )
        node_secret: str | None = None
        if auth_header and auth_header.startswith("Bearer "):
            node_secret = auth_header[len("Bearer ") :].strip()
        elif "token" in websocket.query_params:
            node_secret = websocket.query_params["token"].strip()
        elif "secret" in websocket.query_params:
            node_secret = websocket.query_params["secret"].strip()

        if not node_secret:
            logger.warning(
                "WSS rejected for node '%s': missing Authorization Bearer token", node_id
            )
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Missing authorization token"
            )
            return

        # 3. Authenticate node_secret via NodeService BEFORE accepting logical session
        try:
            with db.get_connection() as conn:
                node = node_service.authenticate_node(conn, node_id, node_secret)
        except (NodeUnauthorizedError, NodeNotFoundError) as exc:
            logger.warning("WSS authentication failed for node '%s': %s", node_id, exc)
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Invalid credentials"
            )
            return
        except NodeRevokedError as exc:
            logger.warning("WSS authentication rejected for REVOKED node '%s': %s", node_id, exc)
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="Node has been revoked"
            )
            return
        except Exception as exc:
            logger.error("Database error during WSS auth for node '%s': %s", node_id, exc)
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Authentication error")
            return

        # 4. Enforce ONE active control connection per node
        old_ws: WebSocket | None = None
        with self._lock:
            if node_id in self._active_connections:
                old_ws = self._active_connections.pop(node_id)
            self._active_connections[node_id] = websocket

        if old_ws is not None:
            logger.info("Closing previous control connection for node '%s'", node_id)
            with contextlib.suppress(Exception):
                await old_ws.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Superseded by new control connection",
                )

        # 5. Accept logical WebSocket session
        await websocket.accept()
        logger.info(
            "Accepted control WebSocket session for node '%s' (initial state=%s)",
            node_id,
            node["state"],
        )

        # 6. Bi-directional message receive loop
        hello_accepted = False
        try:
            while True:
                raw_text = await websocket.receive_text()
                try:
                    envelope = parse_agent_envelope(raw_text)
                except (AgentMessageError, json.JSONDecodeError) as exc:
                    logger.warning("Malformed message received from node '%s': %s", node_id, exc)
                    continue

                if envelope.node_id != node_id:
                    logger.warning(
                        "Envelope node_id mismatch: expected '%s', got '%s'",
                        node_id,
                        envelope.node_id,
                    )
                    continue

                if envelope.message_type == MESSAGE_TYPE_AGENT_HELLO:
                    hello_accepted = await self._handle_agent_hello(websocket, node_id, envelope)
                    continue
                if not hello_accepted:
                    logger.warning(
                        "Ignoring %s from node '%s' before AGENT_HELLO acceptance",
                        envelope.message_type,
                        node_id,
                    )
                    continue
                await self._process_inbound_message(websocket, node_id, envelope)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for node '%s'", node_id)
        except Exception as exc:
            logger.error("Unexpected error in WebSocket loop for node '%s': %s", node_id, exc)
        finally:
            with self._lock:
                if self._active_connections.get(node_id) is websocket:
                    self._active_connections.pop(node_id, None)
            logger.info("Cleaned up WebSocket connection for node '%s'", node_id)

    # ─── Inbound Message Dispatcher ───────────────────────────────────────────

    async def _process_inbound_message(
        self,
        websocket: WebSocket,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> None:
        """Route message based on message_type."""
        msg_type = envelope.message_type

        if msg_type == MESSAGE_TYPE_AGENT_HELLO:
            await self._handle_agent_hello(websocket, node_id, envelope)
        elif msg_type == MESSAGE_TYPE_HEARTBEAT:
            await self._handle_heartbeat(node_id, envelope)
        elif msg_type == MESSAGE_TYPE_RESOURCE_SNAPSHOT:
            await self._handle_resource_snapshot(node_id, envelope)
        elif msg_type == MESSAGE_TYPE_COMMAND_ACK:
            await self._handle_command_ack(node_id, envelope)
        elif msg_type == MESSAGE_TYPE_WORKER_STATUS:
            await self._handle_worker_status(node_id, envelope)
        else:
            logger.warning("Unhandled message type '%s' from node '%s'", msg_type, node_id)

    async def _handle_agent_hello(
        self,
        websocket: WebSocket,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> bool:
        """Process AGENT_HELLO: transition OFFLINE -> ONLINE and reply with HELLO_ACK."""
        try:
            if isinstance(envelope.payload, AgentHelloPayload):
                payload = envelope.payload
            elif isinstance(envelope.payload, dict):
                payload = AgentHelloPayload.from_dict(envelope.payload)
            else:
                raise TypeError(f"Unexpected payload type: {type(envelope.payload).__name__}")
        except Exception as exc:
            logger.warning("Invalid AGENT_HELLO payload from node '%s': %s", node_id, exc)
            return False

        settings = get_settings()
        now = datetime.now(UTC)

        # Transition node to ONLINE in database
        try:
            with db.transaction() as conn:
                node_service.record_node_online(
                    conn,
                    node_id,
                    agent_version=payload.agent_version,
                    platform=payload.platform,
                    now=now,
                )
        except Exception as exc:
            logger.error("Failed recording node online for '%s': %s", node_id, exc)
            return False

        # Reply with HELLO_ACK
        ack_payload = HelloAckPayload(
            heartbeat_interval_seconds=settings.node_heartbeat_interval_seconds,
            telemetry_interval_seconds=settings.node_telemetry_interval_seconds,
        )
        reply_env = AgentEnvelope(
            message_type=MESSAGE_TYPE_HELLO_ACK,
            message_id=f"msg-{uuid.uuid4().hex[:12]}",
            correlation_id=envelope.message_id,
            node_id=node_id,
            sent_at=now.isoformat(),
            payload=ack_payload.to_dict(),
        )
        await websocket.send_text(reply_env.to_json())
        logger.info("Sent HELLO_ACK to node '%s' (node transitioned to ONLINE)", node_id)
        return True

    async def _handle_heartbeat(
        self,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> None:
        """Process HEARTBEAT: update last_seen_at idempotently."""
        try:
            if isinstance(envelope.payload, HeartbeatPayload):
                pass
            elif isinstance(envelope.payload, dict):
                HeartbeatPayload.from_dict(envelope.payload)
            else:
                raise TypeError(f"Unexpected payload type: {type(envelope.payload).__name__}")
        except Exception as exc:
            logger.warning("Invalid HEARTBEAT payload from node '%s': %s", node_id, exc)
            return

        now = datetime.now(UTC)
        try:
            with db.transaction() as conn:
                node_service.record_heartbeat(conn, node_id, last_seen_at=now)
        except Exception as exc:
            logger.error("Failed recording heartbeat for node '%s': %s", node_id, exc)

    async def _handle_resource_snapshot(
        self,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> None:
        """Process RESOURCE_SNAPSHOT: persist latest telemetry metrics."""
        try:
            if isinstance(envelope.payload, ResourceSnapshotPayload):
                payload = envelope.payload
            elif isinstance(envelope.payload, dict):
                payload = ResourceSnapshotPayload.from_dict(envelope.payload)
            else:
                raise TypeError(f"Unexpected payload type: {type(envelope.payload).__name__}")
        except Exception as exc:
            logger.warning("Invalid RESOURCE_SNAPSHOT payload from node '%s': %s", node_id, exc)
            return

        now = datetime.now(UTC)
        try:
            with db.transaction() as conn:
                node_service.record_resources(conn, node_id, payload.to_dict())
                node_service.record_heartbeat(conn, node_id, last_seen_at=now)
        except Exception as exc:
            logger.error("Failed persisting resource snapshot for node '%s': %s", node_id, exc)

    async def _handle_command_ack(
        self,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> None:
        """Process COMMAND_ACK:

        - ACCEPTED: allocation remains DISPATCHED (no-op).
        - REJECTED: allocation transitions to FAILED.
        """
        try:
            if isinstance(envelope.payload, CommandAckPayload):
                payload = envelope.payload
            elif isinstance(envelope.payload, dict):
                payload = CommandAckPayload.from_dict(envelope.payload)
            else:
                raise TypeError(f"Unexpected payload type: {type(envelope.payload).__name__}")
        except Exception as exc:
            logger.warning("Invalid COMMAND_ACK payload from node '%s': %s", node_id, exc)
            return

        try:
            with db.transaction() as conn:
                alloc = allocation_service.get_allocation(conn, payload.allocation_id)
                if alloc["node_id"] != node_id:
                    logger.warning(
                        "COMMAND_ACK allocation '%s' belongs to node '%s', not sender '%s'",
                        payload.allocation_id,
                        alloc["node_id"],
                        node_id,
                    )
                    return

                if payload.status == COMMAND_STATUS_ACCEPTED:
                    logger.info(
                        "Command '%s' for allocation '%s' was ACCEPTED by node '%s' "
                        "(remains DISPATCHED)",
                        payload.command_id,
                        payload.allocation_id,
                        node_id,
                    )
                elif payload.status == COMMAND_STATUS_REJECTED:
                    logger.warning(
                        "Command '%s' for allocation '%s' was REJECTED by node '%s': "
                        "code=%s msg=%s",
                        payload.command_id,
                        payload.allocation_id,
                        node_id,
                        payload.error_code,
                        payload.error_message,
                    )
                    allocation_service.record_failed(
                        conn,
                        payload.allocation_id,
                        failure_code=payload.error_code or "COMMAND_REJECTED",
                        failure_message=payload.error_message or "Node agent rejected command.",
                    )
        except AllocationNotFoundError:
            logger.warning("COMMAND_ACK referenced unknown allocation '%s'", payload.allocation_id)
        except Exception as exc:
            logger.error("Error processing COMMAND_ACK for node '%s': %s", node_id, exc)

    async def _handle_worker_status(
        self,
        node_id: str,
        envelope: AgentEnvelope,
    ) -> None:
        """Process WORKER_STATUS:

        - STARTED -> allocation actual_state = STARTED
        - ENDED -> allocation actual_state = ENDED
        - FAILED -> allocation actual_state = FAILED
        """
        try:
            if isinstance(envelope.payload, WorkerStatusPayload):
                payload = envelope.payload
            elif isinstance(envelope.payload, dict):
                payload = WorkerStatusPayload.from_dict(envelope.payload)
            else:
                raise TypeError(f"Unexpected payload type: {type(envelope.payload).__name__}")
        except Exception as exc:
            logger.warning("Invalid WORKER_STATUS payload from node '%s': %s", node_id, exc)
            return

        try:
            with db.transaction() as conn:
                alloc = allocation_service.get_allocation(conn, payload.allocation_id)
                if alloc["node_id"] != node_id:
                    logger.warning(
                        "WORKER_STATUS allocation '%s' belongs to node '%s', not sender '%s'",
                        payload.allocation_id,
                        alloc["node_id"],
                        node_id,
                    )
                    return

                st = payload.actual_state
                if st == WORKER_ACTUAL_STATE_STARTED:
                    allocation_service.record_started(conn, payload.allocation_id)
                elif st == WORKER_ACTUAL_STATE_ENDED:
                    allocation_service.record_ended(conn, payload.allocation_id)
                elif st == WORKER_ACTUAL_STATE_FAILED:
                    allocation_service.record_failed(
                        conn,
                        payload.allocation_id,
                        failure_code=payload.failure_code,
                        failure_message=payload.failure_message,
                    )
        except AllocationNotFoundError:
            logger.warning(
                "WORKER_STATUS referenced unknown allocation '%s'", payload.allocation_id
            )
        except Exception as exc:
            logger.error("Error processing WORKER_STATUS for node '%s': %s", node_id, exc)

    # ─── Outbound Command Dispatch ────────────────────────────────────────────

    async def async_send_start_worker(
        self,
        node_id: str,
        *,
        command: StartWorkerPayload,
    ) -> bool:
        """Asynchronously dispatch START_WORKER command to target node agent."""
        with self._lock:
            ws = self._active_connections.get(node_id)

        if ws is None:
            logger.warning(
                "Cannot dispatch START_WORKER: node '%s' is not connected via WSS", node_id
            )
            return False

        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            message_id=f"msg-{uuid.uuid4().hex[:12]}",
            correlation_id=command.command_id,
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=command.to_dict(),
        )

        try:
            await ws.send_text(env.to_json())
            logger.info(
                "Dispatched START_WORKER command '%s' (allocation '%s') to node '%s'",
                command.command_id,
                command.allocation_id,
                node_id,
            )
            return True
        except Exception as exc:
            logger.error("Failed transmitting START_WORKER to node '%s': %s", node_id, exc)
            with self._lock:
                if self._active_connections.get(node_id) is ws:
                    self._active_connections.pop(node_id, None)
            return False

    async def async_send_stop_worker(
        self,
        node_id: str,
        *,
        command: StopWorkerPayload,
    ) -> bool:
        """Asynchronously dispatch STOP_WORKER command to target node agent."""
        with self._lock:
            ws = self._active_connections.get(node_id)

        if ws is None:
            logger.warning(
                "Cannot dispatch STOP_WORKER: node '%s' is not connected via WSS", node_id
            )
            return False

        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            message_id=f"msg-{uuid.uuid4().hex[:12]}",
            correlation_id=command.command_id,
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=command.to_dict(),
        )

        try:
            await ws.send_text(env.to_json())
            logger.info(
                "Dispatched STOP_WORKER command '%s' (allocation '%s') to node '%s'",
                command.command_id,
                command.allocation_id,
                node_id,
            )
            return True
        except Exception as exc:
            logger.error("Failed transmitting STOP_WORKER to node '%s': %s", node_id, exc)
            with self._lock:
                if self._active_connections.get(node_id) is ws:
                    self._active_connections.pop(node_id, None)
            return False

    def send_start_worker(
        self,
        node_id: str,
        *,
        command: StartWorkerPayload,
    ) -> bool:
        """Synchronous bridge for NodeControlGatewayProtocol."""
        return self._sync_dispatch(self.async_send_start_worker(node_id, command=command))

    def send_stop_worker(
        self,
        node_id: str,
        *,
        command: StopWorkerPayload,
    ) -> bool:
        """Synchronous bridge for NodeControlGatewayProtocol."""
        return self._sync_dispatch(self.async_send_stop_worker(node_id, command=command))

    def _sync_dispatch(self, coro: Any) -> bool:
        """Execute coroutine safely whether running from inside or outside an event loop."""
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                current = asyncio.get_running_loop()
            except RuntimeError:
                current = None

            if current is loop:
                # Same loop thread: must not block thread; run task
                loop.create_task(coro)
                # Wait briefly if possible, or return True optimistic
                return True
            else:
                # Separate worker thread: use run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                try:
                    return future.result(timeout=5.0)
                except Exception as exc:
                    logger.error("Sync dispatch timeout or failure: %s", exc)
                    return False
        else:
            try:
                return asyncio.run(coro)
            except Exception as exc:
                logger.error("Asyncio.run dispatch error: %s", exc)
                return False

    # ─── Revocation & Connection Drop ─────────────────────────────────────────

    async def async_close_node_connection(self, node_id: str) -> None:
        """Close active WSS connection for a revoked node without modifying attempts/workers."""
        ws: WebSocket | None = None
        with self._lock:
            ws = self._active_connections.pop(node_id, None)

        if ws is not None:
            logger.info("Closing active WSS connection for revoked node '%s'", node_id)
            with contextlib.suppress(Exception):
                await ws.close(
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Node credentials revoked",
                )

    def close_node_connection(self, node_id: str) -> None:
        """Synchronous wrapper for closing a node connection."""
        self._sync_dispatch(self.async_close_node_connection(node_id))

    async def close_all_connections(self) -> None:
        """Clean up all active WebSocket connections on application shutdown."""
        with self._lock:
            conns = list(self._active_connections.items())
            self._active_connections.clear()

        for _n_id, ws in conns:
            with contextlib.suppress(Exception):
                await ws.close(code=status.WS_1000_NORMAL_CLOSURE, reason="Server shutdown")


# ─── Gateway Singleton ────────────────────────────────────────────────────────

_GATEWAY_INSTANCE: NodeControlGateway | None = None


def get_node_control_gateway() -> NodeControlGateway:
    """Retrieve or initialize the global NodeControlGateway singleton."""
    global _GATEWAY_INSTANCE
    if _GATEWAY_INSTANCE is None:
        _GATEWAY_INSTANCE = NodeControlGateway()
    return _GATEWAY_INSTANCE


def init_node_control_gateway() -> NodeControlGateway:
    """Initialize singleton and register it with the running asyncio loop."""
    gw = get_node_control_gateway()
    try:
        loop = asyncio.get_running_loop()
        gw.set_event_loop(loop)
    except RuntimeError:
        pass
    return gw
