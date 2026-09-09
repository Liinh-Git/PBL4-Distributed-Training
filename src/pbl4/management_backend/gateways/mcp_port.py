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
import threading
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
    ) -> None:
        self._host = host
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

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def set_dataset_resolver(self, resolver: DatasetResolver | None) -> None:
        self._dataset_resolver = resolver

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def connect(self) -> bool:
        """Connect and complete MGMT_HELLO; safe to call again after disconnect."""
        with self._connect_lock:
            if self.is_connected:
                return True
            self._close_socket()
            client = TcpClient(self._host, self._port, timeout=None, connect_timeout=self._timeout)
            try:
                client.connect()
            except TransportError:
                return False
            self._client = client
            self._tracker = CorrelationTracker()
            self._reader = threading.Thread(
                target=self._read_loop,
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
                response = self._request("MGMT_HELLO", hello.to_dict(), timeout=self._timeout)
            except Exception:
                self._close_socket()
                return False
            if response.message_type != "MGMT_HELLO_ACK":
                self._close_socket()
                return False
            self._runtime_instance_id = str(response.payload.runtime_instance_id)
            self._connected.set()
            self._dispatch(response)
            return True

    def start_reconnecting(self) -> None:
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
                self.connect()

    def disconnect(self) -> None:
        self._closing.set()
        self._connected.clear()
        self._close_socket()
        reconnect = self._reconnector
        if reconnect is not None and reconnect is not threading.current_thread():
            reconnect.join(timeout=2.0)
        self._reconnector = None

    def _close_socket(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.disconnect()

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

    def _write(self, envelope: McpEnvelope) -> None:
        client = self._client
        if client is None:
            raise TransportError("MCP client is disconnected")
        with self._send_lock:
            McpCodec.write_message(client.sock, send_all, envelope)

    def _request(
        self, message_type: str, payload: dict[str, object], *, timeout: float
    ) -> McpEnvelope:
        envelope = self._new_envelope(message_type, payload)
        future: concurrent.futures.Future[McpEnvelope] = concurrent.futures.Future()
        with self._correlation_lock:
            self._tracker.register_request(envelope)
            self._waiters[envelope.message_id] = future
        try:
            self._write(envelope)
            return future.result(timeout=timeout)
        except Exception:
            with self._correlation_lock:
                self._waiters.pop(envelope.message_id, None)
            raise

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
        if not self.is_connected or payload is None:
            return False
        envelope = self._new_envelope(command_type, payload)
        try:
            with self._correlation_lock:
                self._tracker.register_request(envelope)
            self._write(envelope)
            return True
        except Exception:
            self._connection_lost()
            return False

    def _read_loop(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            while self._client is client:
                envelope = McpCodec.read_message(client.sock, recv_exact)
                if envelope.message_type == "RESOLVE_DATASET_BUILD":
                    threading.Thread(
                        target=self._serve_dataset_resolution,
                        args=(envelope,),
                        daemon=True,
                    ).start()
                    continue
                correlation_id = envelope.correlation_id
                if correlation_id is not None:
                    with self._correlation_lock:
                        self._tracker.accept(envelope)
                        future = self._waiters.pop(correlation_id, None)
                    if future is not None and not future.done():
                        future.set_result(envelope)
                        continue
                self._dispatch(envelope)
        except Exception as exc:
            if not self._closing.is_set():
                logger.warning("MCP reader disconnected: %s", exc)
        finally:
            self._connection_lost(client)

    def _dispatch(self, envelope: McpEnvelope) -> None:
        handler = self._handler
        if handler is None:
            return
        threading.Thread(
            target=handler,
            args=(envelope.message_type, envelope.payload.to_dict()),
            daemon=True,
        ).start()

    def _serve_dataset_resolution(self, request: McpEnvelope) -> None:
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
            self._write(response)

    def _connection_lost(self, expected_client: TcpClient | None = None) -> None:
        if expected_client is not None and self._client is not expected_client:
            return
        was_connected = self._connected.is_set()
        self._connected.clear()
        self._close_socket()
        with self._correlation_lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for future in waiters:
            if not future.done():
                future.set_exception(TransportError("MCP connection closed"))
        if was_connected and self._handler is not None:
            self._handler("DISCONNECTED", {})
