"""Outbound WebSocket control client for Node Agent.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md.

Responsibilities:
- Establish outbound WSS connection to Backend NodeControlGateway at:
  `/ws/v1/nodes/{node_id}/control`
- Authenticate via `Authorization: Bearer <node_secret>` strictly.
- Never log node_secret or worker_join_token in plaintext.
- Handshake: send AGENT_HELLO, receive HELLO_ACK.
- Report only active (STARTING / RUNNING) allocations in AGENT_HELLO.
- Heartbeat loop: periodic HEARTBEAT with active_allocations_count.
- Telemetry loop: periodic RESOURCE_SNAPSHOT with CPU, RAM, and GPU metrics.
- Worker monitoring loop: detect unexpected process exit outside stop flow and report WORKER_STATUS FAILED.
- Command receive loop:
  * START_WORKER -> idempotent spawn via WorkerProcessSupervisor -> COMMAND_ACK -> WORKER_STATUS STARTED.
  * Duplicate START_WORKER on active allocation -> COMMAND_ACK ACCEPTED (no-op, no duplicate process).
  * Duplicate START_WORKER on terminal allocation -> COMMAND_ACK REJECTED.
  * STOP_WORKER -> graceful stop via WorkerProcessSupervisor -> COMMAND_ACK -> WORKER_STATUS ENDED.
- Worker survival invariant:
  * Network disconnect / Agent reconnect MUST NOT terminate or kill Worker processes.
  * Reconnect with bounded exponential backoff.
- Pure control plane: NEVER touches database, DTP/1, tensors, or gradients.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import platform
from typing import Any
import uuid

import websockets

from pbl4 import PACKAGE_VERSION
from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    ERROR_CODE_UNKNOWN_COMMAND_TYPE,
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
    ActiveAllocationItem,
    AgentEnvelope,
    AgentHelloPayload,
    AgentMessageError,
    CommandAckPayload,
    HeartbeatPayload,
    HelloAckPayload,
    StartWorkerPayload,
    StopWorkerPayload,
    WorkerStatusPayload,
    parse_agent_envelope,
)
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.identity import NodeIdentity
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    LOCAL_STATE_STOPPED,
    WorkerProcessSupervisor,
)
from pbl4.node_agent.telemetry import sample_resources

logger = logging.getLogger(__name__)


def get_control_ws_url(backend_url: str, node_id: str) -> str:
    """Build canonical outbound WebSocket URL for node control."""
    url = backend_url.strip().rstrip("/")
    if url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    elif not url.startswith("ws://") and not url.startswith("wss://"):
        url = f"ws://{url}"
    return f"{url}/ws/v1/nodes/{node_id}/control"


def get_connect_headers_kwargs(headers: dict[str, str]) -> dict[str, Any]:
    """Provide version-compatible header argument for websockets.connect."""
    sig = inspect.signature(websockets.connect)
    if "additional_headers" in sig.parameters:
        return {"additional_headers": headers}
    return {"extra_headers": headers}


class NodeAgentClient:
    """Outbound WebSocket control client connecting Node Agent to Management Backend."""

    def __init__(
        self,
        config: NodeAgentConfig,
        identity: NodeIdentity,
        supervisor: WorkerProcessSupervisor,
    ) -> None:
        self.config = config
        self.identity = identity
        self.supervisor = supervisor

        self._stopped = False
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._current_ws: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._send_lock = asyncio.Lock()

        self._heartbeat_interval: float = config.heartbeat_interval_seconds
        self._telemetry_interval: float = config.telemetry_interval_seconds
        self._reported_failures: set[str] = set()
        self._active_tasks: set[asyncio.Task[Any]] = set()

    @property
    def is_connected(self) -> bool:
        """True if client currently holds an active, authenticated control session."""
        return self._connected_event.is_set()

    @property
    def ws_url(self) -> str:
        """Target WebSocket endpoint for this Node."""
        return get_control_ws_url(self.config.backend_url, self.identity.node_id)

    def stop(self) -> None:
        """Signal client to stop running and cleanly disconnect WSS.

        Worker survival invariant:
        Never terminates or kills Worker processes when stopping the agent client.
        """
        self._stopped = True
        self._stop_event.set()
        self._connected_event.clear()
        ws = self._current_ws
        loop = self._loop
        if ws is not None and loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(lambda: asyncio.create_task(ws.close()))
            except Exception:
                pass

    async def run(self) -> None:
        """Alias for start()."""
        await self.start()

    async def start(self) -> None:
        """Run the client connection loop with bounded exponential backoff.

        Worker survival invariant:
        Disconnecting or reconnecting does NOT touch running worker processes.
        """
        reconnect_delay = self.config.reconnect_min_seconds
        self._stopped = False
        self._stop_event.clear()

        logger.info(
            "NodeAgentClient starting for node_id='%s' (backend: %s)",
            self.identity.node_id,
            self.ws_url,
        )

        while not self._stopped:
            try:
                headers = {"Authorization": f"Bearer {self.identity.node_secret}"}
                kwargs = get_connect_headers_kwargs(headers)
                async with websockets.connect(self.ws_url, **kwargs) as ws:
                    self._current_ws = ws
                    # Reset backoff upon successful connection
                    reconnect_delay = self.config.reconnect_min_seconds
                    logger.info("Connected to Management Backend at %s", self.ws_url)
                    await self._run_session(ws)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._connected_event.clear()
                self._current_ws = None
                if self._stopped:
                    break
                logger.warning(
                    "WSS connection error for node '%s': %s. Reconnecting in %.2fs...",
                    self.identity.node_id,
                    exc,
                    reconnect_delay,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=reconnect_delay)
                    break
                except asyncio.TimeoutError:
                    pass
                reconnect_delay = min(reconnect_delay * 2.0, self.config.reconnect_max_seconds)
            finally:
                self._connected_event.clear()
                self._current_ws = None

        logger.info("NodeAgentClient stopped for node_id='%s'", self.identity.node_id)

    async def _run_session(self, ws: Any) -> None:
        """Execute the handshake and concurrent loops for a live WebSocket connection."""
        self._loop = asyncio.get_running_loop()
        # 1. Send AGENT_HELLO
        await self._send_agent_hello(ws)

        # 2. Wait for HELLO_ACK
        raw_ack = await ws.recv()
        envelope = parse_agent_envelope(raw_ack)
        if envelope.message_type != MESSAGE_TYPE_HELLO_ACK:
            raise AgentMessageError(f"Expected HELLO_ACK from Backend, got '{envelope.message_type}'")

        if isinstance(envelope.payload, HelloAckPayload):
            ack_payload = envelope.payload
        elif isinstance(envelope.payload, dict):
            ack_payload = HelloAckPayload.from_dict(envelope.payload)
        else:
            raise AgentMessageError("Invalid HELLO_ACK payload structure")

        self._heartbeat_interval = ack_payload.heartbeat_interval_seconds
        self._telemetry_interval = ack_payload.telemetry_interval_seconds
        logger.info(
            "Received HELLO_ACK: heartbeat_interval=%.1fs, telemetry_interval=%.1fs",
            self._heartbeat_interval,
            self._telemetry_interval,
        )

        # 3. Report any previously failed workers (e.g. reconciled on startup)
        await self._check_reconciled_failures(ws)

        self._connected_event.set()

        # 4. Launch concurrent tasks
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws), name="agent-heartbeat")
        telemetry_task = asyncio.create_task(self._telemetry_loop(ws), name="agent-telemetry")
        monitor_task = asyncio.create_task(self._monitor_loop(ws), name="agent-monitor")
        receive_task = asyncio.create_task(self._receive_loop(ws), name="agent-receive")

        tasks = [heartbeat_task, telemetry_task, monitor_task, receive_task]
        self._active_tasks = set(tasks)

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for t in done:
                if not t.cancelled():
                    exc = t.exception()
                    if exc is not None:
                        raise exc
        finally:
            self._connected_event.clear()
            for t in tasks:
                if not t.done():
                    t.cancel()
            self._active_tasks.clear()

    async def _send_envelope(self, ws: Any, envelope: AgentEnvelope) -> None:
        """Send an agent envelope over WebSocket with thread/task lock protection."""
        async with self._send_lock:
            # We never log raw json that might contain secrets
            json_text = envelope.to_json(redact=False)
            await ws.send(json_text)

    async def _send_agent_hello(self, ws: Any) -> None:
        """Send AGENT_HELLO announcing active allocations and host platform."""
        active_items: list[ActiveAllocationItem] = []
        for r in self.supervisor.list_records():
            # Invariant: ONLY advertise STARTING and RUNNING allocations
            if r.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING):
                active_items.append(
                    ActiveAllocationItem(
                        allocation_id=r.allocation_id,
                        attempt_id=r.attempt_id,
                        local_state=r.local_state,
                        pid=r.pid,
                    )
                )

        hello_payload = AgentHelloPayload(
            agent_version=PACKAGE_VERSION,
            platform=f"{platform.system()}-{platform.release()}-{platform.machine()}",
            active_allocations=tuple(active_items),
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_AGENT_HELLO,
            node_id=self.identity.node_id,
            payload=hello_payload,
        )
        await self._send_envelope(ws, env)
        logger.info(
            "Sent AGENT_HELLO (version=%s, active_allocations=%d)",
            PACKAGE_VERSION,
            len(active_items),
        )

    async def _check_reconciled_failures(self, ws: Any) -> None:
        """Report any workers that were marked FAILED prior to or during reconnect."""
        for r in self.supervisor.list_records():
            if r.local_state == LOCAL_STATE_FAILED and r.allocation_id not in self._reported_failures:
                self._reported_failures.add(r.allocation_id)
                status_payload = WorkerStatusPayload(
                    allocation_id=r.allocation_id,
                    attempt_id=r.attempt_id,
                    actual_state=WORKER_ACTUAL_STATE_FAILED,
                    exit_code=r.exit_code,
                    failure_code="WORKER_RECONCILE_FAILED",
                    failure_message="Worker process terminated while offline or failed reconciliation",
                )
                env = AgentEnvelope(
                    message_type=MESSAGE_TYPE_WORKER_STATUS,
                    node_id=self.identity.node_id,
                    payload=status_payload,
                )
                await self._send_envelope(ws, env)
                logger.info(
                    "Reported reconciled failure for allocation '%s' (exit_code=%s)",
                    r.allocation_id,
                    r.exit_code,
                )

    async def _receive_loop(self, ws: Any) -> None:
        """Receive and route incoming control plane envelopes from Backend."""
        while not self._stopped:
            raw_text = await ws.recv()
            try:
                envelope = parse_agent_envelope(raw_text)
            except Exception as exc:
                logger.warning("Failed parsing incoming envelope: %s", exc)
                continue

            if envelope.node_id != self.identity.node_id:
                logger.warning(
                    "Ignoring envelope for mismatched node_id: expected '%s', got '%s'",
                    self.identity.node_id,
                    envelope.node_id,
                )
                continue

            if envelope.message_type == MESSAGE_TYPE_COMMAND:
                await self._handle_command(ws, envelope)
            else:
                logger.debug("Received unhandled message type '%s'", envelope.message_type)

    async def _handle_command(self, ws: Any, envelope: AgentEnvelope) -> None:
        """Route COMMAND envelope to START_WORKER or STOP_WORKER handler."""
        payload = envelope.payload
        if isinstance(payload, StartWorkerPayload):
            await self._handle_start_worker(ws, envelope, payload)
        elif isinstance(payload, StopWorkerPayload):
            await self._handle_stop_worker(ws, envelope, payload)
        else:
            logger.warning("Received COMMAND with unknown payload: %r", payload)
            ack_payload = CommandAckPayload(
                command_id=envelope.correlation_id or envelope.message_id,
                allocation_id=getattr(payload, "allocation_id", "unknown"),
                status=COMMAND_STATUS_REJECTED,
                error_code=ERROR_CODE_UNKNOWN_COMMAND_TYPE,
                error_message="Unknown command type",
            )
            ack_env = AgentEnvelope(
                message_type=MESSAGE_TYPE_COMMAND_ACK,
                node_id=self.identity.node_id,
                correlation_id=envelope.correlation_id or envelope.message_id,
                payload=ack_payload,
            )
            await self._send_envelope(ws, ack_env)

    async def _handle_start_worker(
        self,
        ws: Any,
        envelope: AgentEnvelope,
        cmd: StartWorkerPayload,
    ) -> None:
        """Handle START_WORKER command: spawn worker process and reply with ACK + WORKER_STATUS."""
        logger.info(
            "Handling START_WORKER command_id='%s' for allocation_id='%s' (attempt_id='%s')",
            cmd.command_id,
            cmd.allocation_id,
            cmd.attempt_id,
        )

        existing = self.supervisor.get_record(cmd.allocation_id)
        is_new = existing is None

        status, error_code = self.supervisor.spawn_worker(cmd)

        error_message: str | None = None
        if error_code is not None:
            error_message = f"Worker spawn failed with {error_code}"

        ack_payload = CommandAckPayload(
            command_id=cmd.command_id,
            allocation_id=cmd.allocation_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )
        ack_env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND_ACK,
            node_id=self.identity.node_id,
            correlation_id=cmd.command_id,
            payload=ack_payload,
        )
        await self._send_envelope(ws, ack_env)

        # If spawn was successful and this was a new process (not duplicate no-op), report WORKER_STATUS STARTED
        if status == COMMAND_STATUS_ACCEPTED and is_new:
            status_payload = WorkerStatusPayload(
                allocation_id=cmd.allocation_id,
                attempt_id=cmd.attempt_id,
                actual_state=WORKER_ACTUAL_STATE_STARTED,
            )
            status_env = AgentEnvelope(
                message_type=MESSAGE_TYPE_WORKER_STATUS,
                node_id=self.identity.node_id,
                correlation_id=cmd.command_id,
                payload=status_payload,
            )
            await self._send_envelope(ws, status_env)
            logger.info("Reported WORKER_STATUS STARTED for allocation '%s'", cmd.allocation_id)

    async def _handle_stop_worker(
        self,
        ws: Any,
        envelope: AgentEnvelope,
        cmd: StopWorkerPayload,
    ) -> None:
        """Handle STOP_WORKER command: stop worker process gracefully and reply with ACK + WORKER_STATUS."""
        logger.info(
            "Handling STOP_WORKER command_id='%s' for allocation_id='%s' (force=%s)",
            cmd.command_id,
            cmd.allocation_id,
            cmd.force,
        )

        record_before = self.supervisor.get_record(cmd.allocation_id)
        status, error_code = self.supervisor.stop_worker(
            cmd.allocation_id,
            grace_period_seconds=cmd.grace_period_seconds,
            force=cmd.force,
        )

        error_message: str | None = None
        if error_code is not None:
            error_message = f"Worker stop failed with {error_code}"

        ack_payload = CommandAckPayload(
            command_id=cmd.command_id,
            allocation_id=cmd.allocation_id,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )
        ack_env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND_ACK,
            node_id=self.identity.node_id,
            correlation_id=cmd.command_id,
            payload=ack_payload,
        )
        await self._send_envelope(ws, ack_env)

        # After stop, report WORKER_STATUS ENDED (or FAILED if stop failed abnormally)
        if status == COMMAND_STATUS_ACCEPTED and record_before is not None:
            updated = self.supervisor.get_record(cmd.allocation_id)
            if updated is not None:
                if updated.local_state == LOCAL_STATE_STOPPED:
                    status_payload = WorkerStatusPayload(
                        allocation_id=cmd.allocation_id,
                        attempt_id=record_before.attempt_id,
                        actual_state=WORKER_ACTUAL_STATE_ENDED,
                        exit_code=updated.exit_code,
                    )
                    status_env = AgentEnvelope(
                        message_type=MESSAGE_TYPE_WORKER_STATUS,
                        node_id=self.identity.node_id,
                        correlation_id=cmd.command_id,
                        payload=status_payload,
                    )
                    await self._send_envelope(ws, status_env)
                    logger.info("Reported WORKER_STATUS ENDED for allocation '%s'", cmd.allocation_id)
                elif updated.local_state == LOCAL_STATE_FAILED:
                    status_payload = WorkerStatusPayload(
                        allocation_id=cmd.allocation_id,
                        attempt_id=record_before.attempt_id,
                        actual_state=WORKER_ACTUAL_STATE_FAILED,
                        exit_code=updated.exit_code,
                        failure_code="WORKER_STOP_FAILED",
                        failure_message="Worker process entered FAILED state during stop",
                    )
                    status_env = AgentEnvelope(
                        message_type=MESSAGE_TYPE_WORKER_STATUS,
                        node_id=self.identity.node_id,
                        correlation_id=cmd.command_id,
                        payload=status_payload,
                    )
                    await self._send_envelope(ws, status_env)

    async def _monitor_loop(self, ws: Any) -> None:
        """Periodically poll supervisor for unexpected worker process terminations."""
        while not self._stopped:
            try:
                await asyncio.sleep(1.0)
                records = self.supervisor.poll()
                for r in records:
                    if r.local_state == LOCAL_STATE_FAILED and r.allocation_id not in self._reported_failures:
                        self._reported_failures.add(r.allocation_id)
                        status_payload = WorkerStatusPayload(
                            allocation_id=r.allocation_id,
                            attempt_id=r.attempt_id,
                            actual_state=WORKER_ACTUAL_STATE_FAILED,
                            exit_code=r.exit_code,
                            failure_code="WORKER_PROCESS_CRASHED",
                            failure_message=f"Worker process exited unexpectedly (code {r.exit_code})",
                        )
                        env = AgentEnvelope(
                            message_type=MESSAGE_TYPE_WORKER_STATUS,
                            node_id=self.identity.node_id,
                            payload=status_payload,
                        )
                        await self._send_envelope(ws, env)
                        logger.warning(
                            "Reported unexpected exit for allocation '%s' (exit_code=%s)",
                            r.allocation_id,
                            r.exit_code,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in worker monitor loop: %s", exc)

    async def _heartbeat_loop(self, ws: Any) -> None:
        """Periodically send HEARTBEAT message to Backend."""
        while not self._stopped:
            try:
                active_count = sum(
                    1
                    for r in self.supervisor.list_records()
                    if r.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING)
                )
                hb_payload = HeartbeatPayload(active_allocations_count=active_count)
                env = AgentEnvelope(
                    message_type=MESSAGE_TYPE_HEARTBEAT,
                    node_id=self.identity.node_id,
                    payload=hb_payload,
                )
                await self._send_envelope(ws, env)
                logger.debug("Sent HEARTBEAT: active_allocations_count=%d", active_count)
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in heartbeat loop: %s", exc)
                raise exc

    async def _telemetry_loop(self, ws: Any) -> None:
        """Periodically sample host resources and send RESOURCE_SNAPSHOT to Backend."""
        while not self._stopped:
            try:
                snapshot = sample_resources()
                env = AgentEnvelope(
                    message_type=MESSAGE_TYPE_RESOURCE_SNAPSHOT,
                    node_id=self.identity.node_id,
                    payload=snapshot,
                )
                await self._send_envelope(ws, env)
                logger.debug("Sent RESOURCE_SNAPSHOT: CPU=%.1f%%", snapshot.cpu_utilization_pct)
                await asyncio.sleep(self._telemetry_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error in telemetry loop: %s", exc)
                raise exc
