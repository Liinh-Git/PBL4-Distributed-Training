"""MCP Client Port — boundary interface for MCP/1 runtime communication.

CANONICAL REFERENCES:
- 02. MCP-1 (Management Control Protocol)
- 04. Cấu trúc mã nguồn (Dependency directions: management_backend → gateways)
- docs/IMPLEMENTATION_CONTRACT.md

CONCURRENCY RULE:
- This file defines the port boundary and a testing fake for Management Backend.
- Do NOT touch or replicate Lâm's MCP/1 binary wire codec in management_protocol.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import logging
import math
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import (
    CorrelationTracker,
    DatasetBuildResolved,
    GetState,
    McpEnvelope,
    McpError,
    MgmtHello,
)
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_client import TcpClient

logger = logging.getLogger(__name__)

McpMessageHandler = Callable[[str, dict[str, Any]], None]
DatasetResolver = Callable[[dict[str, Any]], dict[str, object]]


class McpClientPort(ABC):
    """Abstract port for MCP/1 transport and command dispatch."""

    @abstractmethod
    def connect(self) -> bool:
        """Attempt connection and handshake with Runtime MCP/1 endpoint."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and clean up transport resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection and handshake are currently active."""

    @abstractmethod
    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Send a control command packet to Runtime via MCP/1."""

    @abstractmethod
    def request_state(self) -> dict[str, Any] | None:
        """Request immediate STATE_SNAPSHOT from Runtime."""

    @abstractmethod
    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        """Register handler for inbound semantic messages (HELLO_ACK, SNAPSHOT, RESULT, EVENT)."""

    @abstractmethod
    def set_dataset_resolver(self, resolver: DatasetResolver | None) -> None:
        """Register the Backend catalog resolver for Runtime-originated requests."""

    @property
    def runtime_instance_id(self) -> str | None:
        """Return runtime instance ID if connected and known."""
        return None


class TruthfulDisconnectedMcpPort(McpClientPort):
    """Truthful production port when Lâm's MCP/1 client is not integrated.

    Never pretends to be connected. Truthfully returns disconnected and drops commands.
    """

    def __init__(self) -> None:
        self._handler: McpMessageHandler | None = None

    def set_dataset_resolver(self, resolver: DatasetResolver | None) -> None:
        return None

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def connect(self) -> bool:
        logger.info(
            "TruthfulDisconnectedMcpPort: MCP/1 endpoint not integrated; staying disconnected."
        )
        return False

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return False

    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        logger.warning(
            "TruthfulDisconnectedMcpPort: MCP/1 not connected. Command %s (%s) dropped.",
            command_id,
            command_type,
        )
        return False

    def request_state(self) -> dict[str, Any] | None:
        return None


class FakeMcpClientPort(McpClientPort):
    """In-memory fake port for standalone verification and unit tests."""

    def __init__(
        self,
        initially_connected: bool = False,
        auto_accept_commands: bool = True,
    ) -> None:
        self._connected = initially_connected
        self._auto_accept_commands = auto_accept_commands
        self.dispatched_commands: list[dict[str, Any]] = []
        self.snapshot_to_return: dict[str, Any] | None = None
        self._handler: McpMessageHandler | None = None
        self._dataset_resolver: DatasetResolver | None = None

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def set_dataset_resolver(self, resolver: DatasetResolver | None) -> None:
        self._dataset_resolver = resolver

    def simulate_inbound(self, msg_type: str, payload: dict[str, Any]) -> None:
        """Deliver an inbound semantic message to the registered gateway handler."""
        if self._handler:
            self._handler(msg_type, payload)

    def simulate_hello_ack(self, payload: dict[str, Any] | None = None) -> None:
        self.simulate_inbound("MGMT_HELLO_ACK", payload or {})

    def simulate_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.simulate_inbound("STATE_SNAPSHOT", snapshot)

    def simulate_command_result(
        self,
        command_id: str,
        status: str = "ACCEPTED",
        *,
        target_type: str = "ATTEMPT",
        target_id: str = "attempt-test",
        result_code: str = "COMMAND_ACCEPTED",
        message: str = "Command accepted.",
    ) -> None:
        self.simulate_inbound(
            "COMMAND_RESULT",
            {
                "command_id": command_id,
                "target_type": target_type,
                "target_id": target_id,
                "status": status,
                "result_code": result_code,
                "message": message,
            },
        )

    def simulate_runtime_event(self, event: dict[str, Any]) -> None:
        self.simulate_inbound("RUNTIME_EVENT", event)

    def connect(self) -> bool:
        self._connected = True
        logger.info("FakeMcpClientPort connected.")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("FakeMcpClientPort disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if not self._connected:
            logger.warning(
                "FakeMcpClientPort: Not connected, dropped command %s (%s)",
                command_id,
                command_type,
            )
            return False

        record = {
            "command_type": command_type,
            "command_id": command_id,
            "target_id": target_id,
            "payload": payload or {},
        }
        self.dispatched_commands.append(record)
        logger.info("FakeMcpClientPort dispatched: %s", record)

        if self._auto_accept_commands and self._handler:
            # Auto-respond with ACCEPTED so tests don't time out
            self.simulate_command_result(
                command_id=command_id,
                status="ACCEPTED",
                target_id=target_id,
            )
        return True

    def request_state(self) -> dict[str, Any] | None:
        if not self._connected:
            return None
        return self.snapshot_to_return


class RealMcpClientPort(McpClientPort):
    """Threaded MCP/1 TCP client with exact correlation and safe reconnects."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        backend_instance_id: str | None = None,
        timeout: float = 5.0,
        reconnect_interval: float = 1.0,
        probe_interval: float = 15.0,
        probe_timeout: float = 15.0,
    ) -> None:
        for value in (timeout, reconnect_interval, probe_interval, probe_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("MCP timeouts and intervals must be finite and positive")
        self._probe_interval = probe_interval
        self._probe_timeout = probe_timeout
        self._state_lock = threading.RLock()
        self._delivery_context = threading.local()
        self._probe_stop = threading.Event()
        self._probe_thread: threading.Thread | None = None
        self._host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        self._port = port
        self._backend_instance_id = backend_instance_id or f"backend-{uuid4()}"
        self._timeout = timeout
        self._reconnect_interval = reconnect_interval
        self._client: TcpClient | None = None
        self._handler: McpMessageHandler | None = None
        self._dataset_resolver: DatasetResolver | None = None
        self._runtime_instance_id: str | None = None
        self._connected = threading.Event()
        self._closing = threading.Event()
        self._send_lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._correlation_lock = threading.Lock()
        self._tracker = CorrelationTracker()
        self._waiters: dict[str, concurrent.futures.Future[McpEnvelope]] = {}
        self._reader: threading.Thread | None = None
        self._reconnector: threading.Thread | None = None
        self._dispatch_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pbl4-mcp-projection"
        )

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def set_dataset_resolver(self, resolver: DatasetResolver | None) -> None:
        self._dataset_resolver = resolver

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def runtime_instance_id(self) -> str | None:
        return self._runtime_instance_id if self._connected.is_set() else None

    def connect(self) -> bool:
        """Connect and complete MGMT_HELLO; safe after an explicit disconnect."""
        return self._connect(automatic=False)

    def _connect(self, *, automatic: bool) -> bool:
        """Connect and complete MGMT_HELLO; safe to call again after disconnect."""
        with self._connect_lock:
            # Explicit connect after disconnect remains supported.
            with self._state_lock:
                if automatic and self._closing.is_set():
                    return False
                if not automatic:
                    self._closing.clear()
            if self.is_connected:
                return True
            self._close_socket()
            client = TcpClient(self._host, self._port, timeout=None, connect_timeout=self._timeout)
            try:
                client.connect()
            except TransportError:
                return False
            with self._state_lock:
                if self._closing.is_set():
                    client.disconnect()
                    return False
                self._client = client
                self._tracker = CorrelationTracker()
            self._reader = threading.Thread(
                target=self._read_loop,
                args=(client, self._tracker),
                name="pbl4-mcp-client-reader",
                daemon=True,
            )
            self._reader.start()
            hello = MgmtHello.from_dict(
                {
                    "backend_instance_id": self._backend_instance_id,
                    "supported_protocol_versions": [1],
                    "last_known_runtime_instance_id": self._runtime_instance_id,
                    "last_known_attempt_id": None,
                    "last_seen_runtime_event_seq": None,
                }
            )
            try:
                response = self._request(
                    "MGMT_HELLO",
                    hello.to_dict(),
                    timeout=self._timeout,
                    expected_client=client,
                )
            except Exception:
                self._connection_lost(client)
                return False
            if response.message_type != "MGMT_HELLO_ACK":
                self._connection_lost(client)
                return False
            with self._state_lock:
                if self._client is not client or self._closing.is_set():
                    return False
                self._runtime_instance_id = str(response.payload.runtime_instance_id)
                self._connected.set()
                self._dispatch(response, client)
                self._start_probe(client)
            return True

    def start_reconnecting(self) -> None:
        with self._state_lock:
            if self._reconnector is not None and self._reconnector.is_alive():
                return
            self._closing.clear()
            self._reconnector = threading.Thread(
                target=self._reconnect_loop,
                name="pbl4-mcp-client-reconnect",
                daemon=True,
            )
            self._reconnector.start()

    def _reconnect_loop(self) -> None:
        while not self._closing.wait(self._reconnect_interval):
            if not self.is_connected:
                self._connect(automatic=True)

    def disconnect(self) -> None:
        with self._state_lock:
            self._closing.set()
            self._connection_lost()
        for thread in (self._reconnector, self._probe_thread, self._reader):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._reconnector = None

    def _close_socket(self) -> None:
        self._connection_lost()

    def _start_probe(self, client: TcpClient) -> None:
        stop = threading.Event()
        self._probe_stop = stop

        def monitor() -> None:
            while not stop.wait(self._probe_interval):
                try:
                    response = self._request(
                        "GET_STATE",
                        GetState.from_dict({}).to_dict(),
                        timeout=self._probe_timeout,
                        expected_client=client,
                    )
                    if response.message_type != "STATE_SNAPSHOT":
                        raise ProtocolError("Expected probe STATE_SNAPSHOT")
                except Exception:
                    self._connection_lost(client, "MCP probe failed")
                    return

        self._probe_thread = threading.Thread(
            target=monitor,
            name="pbl4-mcp-probe",
            daemon=True,
        )
        self._probe_thread.start()

    def _new_envelope(
        self,
        message_type: str,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
        runtime_instance_id: str | None = None,
    ) -> McpEnvelope:
        return McpEnvelope(
            message_type=message_type,
            message_id=str(uuid4()),
            correlation_id=correlation_id,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id=(
                self._runtime_instance_id
                if runtime_instance_id is None and message_type != "MGMT_HELLO"
                else runtime_instance_id
            ),
            payload=payload,
        )

    def _write(self, envelope: McpEnvelope, expected_client: TcpClient | None = None) -> None:
        with self._state_lock:
            client = expected_client or self._client
            if client is None or self._client is not client:
                raise TransportError("MCP client is disconnected or superseded")
        with self._send_lock:
            with self._state_lock:
                if self._client is not client:
                    raise TransportError("MCP connection superseded")
            McpCodec.write_message(
                client.sock,
                lambda sock, data: send_all(sock, data, timeout=self._timeout),
                envelope,
            )

    def _request(
        self,
        message_type: str,
        payload: dict[str, object],
        *,
        timeout: float,
        expected_client: TcpClient | None = None,
    ) -> McpEnvelope:
        future: concurrent.futures.Future[McpEnvelope] = concurrent.futures.Future()
        with self._state_lock:
            client = (
                expected_client or getattr(self._delivery_context, "client", None) or self._client
            )
            if client is None or self._client is not client:
                raise TransportError("MCP connection superseded")
            envelope = self._new_envelope(message_type, payload)
            with self._correlation_lock:
                self._tracker.register_request(envelope)
                self._waiters[envelope.message_id] = future

        # Also bound writes for ordinary requests, not only background probes.
        def expire() -> None:
            with self._state_lock:
                if not future.done():
                    self._connection_lost(client, f"MCP {message_type} timed out")

        deadline = threading.Timer(timeout, expire)
        deadline.daemon = True
        deadline.start()
        started = time.monotonic()
        try:
            self._write(envelope, client)
            response = future.result(timeout=max(0, timeout - (time.monotonic() - started)))
            with self._state_lock:
                if self._client is not client:
                    raise TransportError("MCP response belongs to a superseded connection")
            return response
        except Exception:
            self._connection_lost(client, "MCP request failed")
            raise
        finally:
            deadline.cancel()

    def request_state(self) -> dict[str, Any] | None:
        if not self.is_connected:
            return None
        try:
            response = self._request(
                "GET_STATE", GetState.from_dict({}).to_dict(), timeout=self._timeout
            )
        except Exception:
            return None
        if response.message_type != "STATE_SNAPSHOT":
            return None
        return response.payload.to_dict()

    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        del command_id, target_id
        client = None
        try:
            with self._state_lock:
                client = getattr(self._delivery_context, "client", None) or self._client
                if (
                    not self.is_connected
                    or payload is None
                    or client is None
                    or self._client is not client
                ):
                    return False
                envelope = self._new_envelope(command_type, payload)
                with self._correlation_lock:
                    self._tracker.register_request(envelope)
            self._write(envelope, client)
            return True
        except Exception:
            self._connection_lost(client)
            return False

    def _read_loop(self, client: TcpClient, tracker: CorrelationTracker) -> None:
        try:
            while self._client is client:
                envelope = McpCodec.read_message(client.sock, recv_exact)
                if envelope.message_type == "RESOLVE_DATASET_BUILD":
                    threading.Thread(
                        target=self._serve_dataset_resolution,
                        args=(envelope, client),
                        daemon=True,
                    ).start()
                    continue
                correlation_id = envelope.correlation_id
                if correlation_id is not None:
                    with self._state_lock:
                        if self._client is not client:
                            return
                        with self._correlation_lock:
                            tracker.accept(envelope)
                            future = self._waiters.pop(correlation_id, None)
                    if future is not None and not future.done():
                        future.set_result(envelope)
                        continue
                self._dispatch(envelope, client)
        except Exception as exc:
            if not self._closing.is_set():
                logger.warning("MCP reader disconnected: %s", exc)
        finally:
            self._connection_lost(client)

    def _dispatch(self, envelope: McpEnvelope, client: TcpClient | None = None) -> None:
        handler = self._handler
        if handler is None:
            return

        # Keep semantic delivery in TCP receive order. Reader/correlation and
        # dataset resolution stay independent so handlers may request state.
        def deliver() -> None:
            with self._state_lock:
                if client is not None and self._client is not client:
                    return
            self._delivery_context.client = client
            try:
                handler(envelope.message_type, envelope.payload.to_dict())
            finally:
                self._delivery_context.client = None

        self._dispatch_executor.submit(deliver)

    def _serve_dataset_resolution(self, request: McpEnvelope, client: TcpClient) -> None:
        try:
            if self._dataset_resolver is None:
                raise ProtocolError("Backend dataset resolver is not configured")
            payload = DatasetBuildResolved.from_dict(
                self._dataset_resolver(request.payload.to_dict())
            ).to_dict()
            response = self._new_envelope(
                "DATASET_BUILD_RESOLVED",
                payload,
                correlation_id=request.message_id,
            )
        except Exception as exc:
            response = self._new_envelope(
                "ERROR",
                McpError.from_dict(
                    {
                        "code": "DATASET_RESOLUTION_FAILED",
                        "category": "CATALOG",
                        "message": str(exc),
                        "details": {},
                    }
                ).to_dict(),
                correlation_id=request.message_id,
            )
        with contextlib.suppress(Exception):
            self._write(response, client)

    def _connection_lost(
        self,
        expected_client: TcpClient | None = None,
        reason: str = "MCP connection closed",
    ) -> None:
        with self._state_lock:
            if expected_client is not None and self._client is not expected_client:
                return
            client, self._client = self._client, None
            was_connected = self._connected.is_set()
            self._connected.clear()
            self._probe_stop.set()
            with self._correlation_lock:
                waiters = list(self._waiters.values())
                self._waiters.clear()
                self._tracker = CorrelationTracker()
            # Queue before the next HELLO to preserve semantic delivery order.
            if was_connected and self._handler is not None:
                self._dispatch_executor.submit(self._handler, "DISCONNECTED", {})
        if client is not None:
            logger.info("MCP connection closed: %s", reason)
            client.disconnect()
        for future in waiters:
            with contextlib.suppress(concurrent.futures.InvalidStateError):
                future.set_exception(TransportError(reason))
