"""Runtime-side MCP/1 TCP endpoint, isolated from training correctness."""

from __future__ import annotations

import concurrent.futures
import contextlib
import logging
import socket
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import (
    CommandResult,
    CorrelationTracker,
    DatasetBuildResolved,
    McpEnvelope,
    McpError,
    MgmtHelloAck,
    ResolveDatasetBuild,
    RuntimeEvent,
    StateSnapshot,
)
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_server import TcpServer

logger = logging.getLogger(__name__)

SnapshotProvider = Callable[[], dict[str, object]]
CommandHandler = Callable[[str, dict[str, object]], dict[str, object]]


def _inactive_snapshot(runtime_instance_id: str) -> dict[str, object]:
    return {
        "runtime_instance_id": runtime_instance_id,
        "active_job_id": None,
        "active_attempt_id": None,
        "attempt_state": None,
        "training_strategy": None,
        "checkpoint_policy": None,
        "epoch": None,
        "current_operation_id": None,
        "current_batch_ordinal": None,
        "model_version": None,
        "workers": [],
        "strategy_state": {},
        "checkpoint_state": None,
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": None,
        "dataset_manifest_hash": None,
        "last_runtime_event_seq": 0,
        "management_event_gap_count": 0,
        "captured_at": datetime.now(UTC).isoformat(),
    }


class ManagementEndpoint:
    """One-listener MCP endpoint with correlated bidirectional requests."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        runtime_instance_id: str | None = None,
        snapshot_provider: SnapshotProvider | None = None,
        command_handler: CommandHandler | None = None,
        request_timeout: float = 5.0,
        send_timeout: float | None = None,
    ) -> None:
        self.runtime_instance_id = runtime_instance_id or f"runtime-{uuid4()}"
        self._boot_time = datetime.now(UTC).isoformat()
        self._snapshot_provider = snapshot_provider or (
            lambda: _inactive_snapshot(self.runtime_instance_id)
        )
        self._command_handler = command_handler
        self._request_timeout = request_timeout
        self.send_timeout = send_timeout if send_timeout is not None else request_timeout
        self._server = TcpServer(host, port, self._serve_connection)
        self._connection_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._correlation_lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._backend_connected = threading.Event()
        self._tracker = CorrelationTracker()
        self._waiters: dict[str, concurrent.futures.Future[McpEnvelope]] = {}
        self._command_lock = threading.Lock()
        self._command_results: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._in_flight_commands: dict[str, concurrent.futures.Future[dict[str, object]]] = {}
        self._max_cached_commands = 1024

    @property
    def bound_address(self) -> tuple[str, int] | None:
        return self._server.bound_address

    @property
    def backend_connected(self) -> bool:
        return self._backend_connected.is_set()

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._disconnect_socket(reason="MCP endpoint stopped")
        self._server.stop()

    def _disconnect_socket(self, sock: socket.socket | None = None, reason: str = "") -> None:
        with self._connection_lock:
            target = self._sock
            if sock is not None and target is not sock:
                return
            self._sock = None
            self._backend_connected.clear()
        if target is not None:
            with contextlib.suppress(OSError):
                target.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                target.close()
        self._fail_waiters(reason or "Management Backend disconnected")

    def _envelope(
        self,
        message_type: str,
        payload: dict[str, object],
        *,
        correlation_id: str | None = None,
    ) -> McpEnvelope:
        return McpEnvelope(
            message_type=message_type,
            message_id=str(uuid4()),
            correlation_id=correlation_id,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id=self.runtime_instance_id,
            payload=payload,
        )

    def _write(self, envelope: McpEnvelope) -> None:
        with self._connection_lock:
            sock = self._sock
        if sock is None:
            raise TransportError("Management Backend is disconnected")
        with self._send_lock:
            try:
                McpCodec.write_message(
                    sock,
                    lambda s, d: send_all(s, d, timeout=self.send_timeout),
                    envelope,
                )
            except TransportError as exc:
                self._disconnect_socket(sock, f"Write error: {exc}")
                raise

    def _serve_connection(self, sock: socket.socket, _address: tuple[str, int]) -> None:
        with self._connection_lock:
            previous = self._sock
            self._sock = sock
        if previous is not None and previous is not sock:
            with contextlib.suppress(OSError):
                previous.shutdown(socket.SHUT_RDWR)
        self._tracker = CorrelationTracker()
        try:
            while True:
                envelope = McpCodec.read_message(sock, recv_exact)
                if envelope.correlation_id is not None:
                    with self._correlation_lock:
                        self._tracker.accept(envelope)
                        waiter = self._waiters.pop(envelope.correlation_id, None)
                    if waiter is not None and not waiter.done():
                        waiter.set_result(envelope)
                        continue
                self._handle_request(envelope)
        except TransportError:
            logger.info("Management client disconnected")
        except Exception as exc:
            logger.exception("MCP connection loop error: %s", exc)
        finally:
            should_fail = False
            with self._connection_lock:
                if self._sock is sock:
                    self._sock = None
                    self._backend_connected.clear()
                    should_fail = True
            if should_fail:
                self._fail_waiters("Management Backend disconnected")

    def _handle_request(self, request: McpEnvelope) -> None:
        if request.message_type == "MGMT_HELLO":
            snapshot = StateSnapshot.from_dict(self._snapshot_provider()).to_dict()
            ack = MgmtHelloAck.from_dict(
                {
                    "runtime_instance_id": self.runtime_instance_id,
                    "selected_protocol_version": 1,
                    "runtime_boot_time": self._boot_time,
                    "active_attempt_id": snapshot["active_attempt_id"],
                    "active_job_id": snapshot["active_job_id"],
                    "active_attempt_state": snapshot["attempt_state"],
                    "snapshot_required": True,
                    "last_runtime_event_seq": snapshot["last_runtime_event_seq"],
                }
            )
            self._write(
                self._envelope("MGMT_HELLO_ACK", ack.to_dict(), correlation_id=request.message_id)
            )
            self._backend_connected.set()
            return
        if not self.backend_connected:
            raise ProtocolError("MCP command arrived before MGMT_HELLO")
        if request.message_type == "GET_STATE":
            snapshot = StateSnapshot.from_dict(self._snapshot_provider())
            self._write(
                self._envelope(
                    "STATE_SNAPSHOT", snapshot.to_dict(), correlation_id=request.message_id
                )
            )
            return
        if request.message_type in {"START_ATTEMPT", "ABORT_ATTEMPT", "REQUEST_CHECKPOINT"}:
            threading.Thread(
                target=self._serve_command,
                args=(request,),
                name="pbl4-mcp-command",
                daemon=True,
            ).start()
            return
        raise ProtocolError(f"Unsupported Backend request {request.message_type}")

    def _serve_command(self, request: McpEnvelope) -> None:
        payload = request.payload.to_dict()
        command_id = str(payload.get("command_id"))

        with self._command_lock:
            if command_id in self._command_results:
                cached_result = self._command_results[command_id]
                canonical = CommandResult.from_dict(cached_result)
                response = self._envelope(
                    "COMMAND_RESULT", canonical.to_dict(), correlation_id=request.message_id
                )
                with contextlib.suppress(Exception):
                    self._write(response)
                return

            if command_id in self._in_flight_commands:
                future = self._in_flight_commands[command_id]
                in_flight = None
            else:
                future = None
                in_flight = concurrent.futures.Future()
                self._in_flight_commands[command_id] = in_flight

        if future is not None:
            try:
                result = future.result(timeout=self._request_timeout)
                canonical = CommandResult.from_dict(result)
                response = self._envelope(
                    "COMMAND_RESULT", canonical.to_dict(), correlation_id=request.message_id
                )
            except Exception as exc:
                response = self._error_response(request.message_id, "COMMAND_FAILED", str(exc))
            with contextlib.suppress(Exception):
                self._write(response)
            return

        try:
            if self._command_handler is None:
                result = {
                    "command_id": payload["command_id"],
                    "target_type": "ATTEMPT",
                    "target_id": payload["attempt_id"],
                    "status": "REJECTED",
                    "result_code": "RUNTIME_NOT_COMPOSED",
                    "message": "Runtime command handler is not configured.",
                    "attempt_id": payload["attempt_id"],
                }
            else:
                result = self._command_handler(request.message_type, payload)
            canonical = CommandResult.from_dict(result)
            with self._command_lock:
                self._command_results[command_id] = canonical.to_dict()
                if len(self._command_results) > self._max_cached_commands:
                    self._command_results.popitem(last=False)
            if in_flight is not None:
                in_flight.set_result(canonical.to_dict())
            response = self._envelope(
                "COMMAND_RESULT", canonical.to_dict(), correlation_id=request.message_id
            )
        except Exception as exc:
            if in_flight is not None:
                in_flight.set_exception(exc)
            response = self._error_response(request.message_id, "COMMAND_FAILED", str(exc))
        finally:
            with self._command_lock:
                self._in_flight_commands.pop(command_id, None)

        with contextlib.suppress(Exception):
            self._write(response)

    def _error_response(self, correlation_id: str, code: str, message: str) -> McpEnvelope:
        payload = McpError.from_dict(
            {"code": code, "category": "RUNTIME", "message": message, "details": {}}
        )
        return self._envelope("ERROR", payload.to_dict(), correlation_id=correlation_id)

    def resolve_dataset_build(self, request: dict[str, object]) -> dict[str, object]:
        """Ask Backend catalog for location metadata; manifest bytes remain HTTP-only."""
        payload = ResolveDatasetBuild.from_dict(request)
        envelope = self._envelope("RESOLVE_DATASET_BUILD", payload.to_dict())
        future: concurrent.futures.Future[McpEnvelope] = concurrent.futures.Future()
        with self._correlation_lock:
            self._tracker.register_request(envelope)
            self._waiters[envelope.message_id] = future
        try:
            self._write(envelope)
            response = future.result(timeout=self._request_timeout)
        except Exception:
            with self._correlation_lock:
                self._waiters.pop(envelope.message_id, None)
            raise
        if response.message_type == "ERROR":
            raise ProtocolError(str(response.payload.message))
        return DatasetBuildResolved.from_dict(response.payload.to_dict()).to_dict()

    def send_runtime_event(self, event: dict[str, object]) -> bool:
        """Best-effort non-barrier event forwarding; false never changes training state."""
        if not self.backend_connected:
            return False
        try:
            payload = RuntimeEvent.from_dict(event)
            self._write(self._envelope("RUNTIME_EVENT", payload.to_dict()))
            return True
        except Exception:
            return False

    def _fail_waiters(self, message: str) -> None:
        with self._correlation_lock:
            waiters = list(self._waiters.values())
            self._waiters.clear()
        for waiter in waiters:
            if not waiter.done():
                waiter.set_exception(TransportError(message))
        with self._command_lock:
            in_flight = list(self._in_flight_commands.values())
            self._in_flight_commands.clear()
        for fut in in_flight:
            if not fut.done():
                fut.set_exception(TransportError(message))
