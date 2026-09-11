"""Thin DTP/1 TCP composition around Runtime-owned session and training cores."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    MESSAGE_TYPE_GRADIENT_CHUNK,
    MESSAGE_TYPE_GRADIENT_END,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_MODEL_INIT,
    MESSAGE_TYPE_MODEL_MANIFEST,
    MESSAGE_TYPE_PARAMETER_APPLIED,
    MESSAGE_TYPE_PARAMETER_CHUNK,
    MESSAGE_TYPE_PARAMETER_META,
    MESSAGE_TYPE_READY,
    MESSAGE_TYPE_SHARD_ERROR,
    MESSAGE_TYPE_SHARD_READY,
    NO_OPERATION,
)
from pbl4.protocol.messages import (
    DatasetAssignment,
    DtpControlMessage,
    GradientEnd,
    GradientMeta,
    Heartbeat,
    Hello,
    HelloAck,
    ModelManifest,
    ParameterMeta,
    Ready,
    StepStart,
    Stop,
    build_control_frame,
    decode_control_message,
)
from pbl4.protocol.messages import ParameterApplied as WireParameterApplied
from pbl4.protocol.parameter_manifest import ParameterManifest
from pbl4.protocol.session import ConnectionPhase, ConnectionProtocolValidator, PeerRole
from pbl4.protocol.transfer import (
    CompletedTensorTransfer,
    LogicalTransferSender,
    TensorTransferAssembler,
    TransferIdentity,
    build_tensor_transfer_frames,
)
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_server import TcpServer

GradientHandler = Callable[[Contribution], None]
ParameterAppliedHandler = Callable[[ParameterApplied], None]
ModelInitHandler = Callable[[CompletedTensorTransfer], None]
DisconnectHandler = Callable[[int, int], None]


@dataclass(slots=True)
class _Connection:
    sock: socket.socket
    session_id: int
    worker_id: int
    validator: ConnectionProtocolValidator
    assembler: TensorTransferAssembler
    sender: LogicalTransferSender
    node_label: str
    protocol_version: int
    connected_at: str
    last_heartbeat_at: str
    terminal_stop_sent: bool = False
    shard_id: int | None = None
    local_model_version: int | None = None


class ParameterServer:
    """Own TCP sessions and map only complete DTP objects into Runtime types."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        attempt_id: str,
        job_id: str,
        expected_workers: int,
        manifest: ParameterManifest,
        registry: WorkerRegistry,
        gradient_handler: GradientHandler | None = None,
        parameter_applied_handler: ParameterAppliedHandler | None = None,
        model_init_handler: ModelInitHandler | None = None,
        disconnect_handler: DisconnectHandler | None = None,
        heartbeat_interval_ms: int = 5_000,
        heartbeat_timeout_ms: int = 15_000,
        max_tensor_chunk_bytes: int = 1024 * 1024,
    ) -> None:
        if heartbeat_timeout_ms <= heartbeat_interval_ms:
            raise ValueError("heartbeat timeout must exceed interval")
        self.attempt_id = attempt_id
        self.job_id = job_id
        self.expected_workers = expected_workers
        self.manifest = manifest
        self.registry = registry
        self._gradient_handler = gradient_handler
        self._parameter_applied_handler = parameter_applied_handler
        self._model_init_handler = model_init_handler
        self._disconnect_handler = disconnect_handler
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._heartbeat_timeout_ms = heartbeat_timeout_ms
        self._max_chunk = max_tensor_chunk_bytes
        self._server = TcpServer(host, port, self._serve_connection)
        self._lock = threading.Lock()
        self._connections: dict[int, _Connection] = {}
        self._manifest_workers: set[int] = set()
        self._next_session_id = 1
        self._membership_changed = threading.Condition(self._lock)

    @property
    def bound_address(self) -> tuple[str, int] | None:
        return self._server.bound_address

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()

    def wait_for_workers(self, count: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._membership_changed:
            while len(self._connections) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._membership_changed.wait(remaining)
            return True

    def worker_ids(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(sorted(self._connections))

    def worker_snapshots(self) -> tuple[dict[str, object], ...]:
        """Return management metadata without exposing live socket objects."""
        sessions = {item.worker_id: item for item in self.registry.snapshot()}
        with self._lock:
            return tuple(
                {
                    "worker_id": worker_id,
                    "session_id": connection.session_id,
                    "node_label": connection.node_label,
                    "state": sessions[worker_id].state.value,
                    "protocol_version": connection.protocol_version,
                    "connected_at": connection.connected_at,
                    "last_heartbeat_at": connection.last_heartbeat_at,
                    "shard_id": connection.shard_id,
                    "local_model_version": connection.local_model_version,
                }
                for worker_id, connection in sorted(self._connections.items())
                if worker_id in sessions
            )

    def wait_for_manifests(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._membership_changed:
            while len(self._manifest_workers) < self.expected_workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._membership_changed.wait(remaining)
            return True

    def _serve_connection(self, sock: socket.socket, _address: tuple[str, int]) -> None:
        connection: _Connection | None = None
        try:
            first = DTPFrame.read_from(sock, recv_exact)
            if first.header.message_type != MESSAGE_TYPE_HELLO:
                raise ProtocolError("First DTP frame must be HELLO")
            hello = decode_control_message(first.header.message_type, first.payload)
            if not isinstance(hello, Hello):
                raise ProtocolError("Invalid HELLO payload")
            validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
            validator.validate(first.header, hello)

            with self._membership_changed:
                session_id = self._next_session_id
                self._next_session_id += 1
                registered = self.registry.register(session_id, time.monotonic())
                self.registry.transition(
                    registered.worker_id,
                    session_id,
                    SessionState.REGISTERING,
                    time.monotonic(),
                )
                self.registry.transition(
                    registered.worker_id,
                    session_id,
                    SessionState.PROVISIONING,
                    time.monotonic(),
                )
                validator.bind(session_id, registered.worker_id)
                connected_at = datetime.now(UTC).isoformat()
                connection = _Connection(
                    sock=sock,
                    session_id=session_id,
                    worker_id=registered.worker_id,
                    validator=validator,
                    assembler=TensorTransferAssembler(
                        self.manifest,
                        max_model_bytes=self.manifest.total_bytes,
                        max_tensor_chunk_bytes=self._max_chunk,
                    ),
                    sender=LogicalTransferSender(self._write_frame),
                    node_label=str(hello.node_label),
                    protocol_version=1,
                    connected_at=connected_at,
                    last_heartbeat_at=connected_at,
                )
                self._connections[registered.worker_id] = connection
                self._membership_changed.notify_all()

            ack = HelloAck.from_dict(
                {
                    "attempt_id": self.attempt_id,
                    "job_id": self.job_id,
                    "session_id": str(session_id),
                    "worker_id": connection.worker_id,
                    "expected_workers": self.expected_workers,
                    "training_strategy": "strict_bsp",
                    "heartbeat_interval_ms": self._heartbeat_interval_ms,
                    "heartbeat_timeout_ms": self._heartbeat_timeout_ms,
                    "tensor_encoding": "fp32_le_v1",
                    "max_tensor_chunk_bytes": self._max_chunk,
                    "server_protocol_version": 1,
                }
            )
            self._send_control(connection, ack)
            try:
                self._read_bound(connection)
            except TransportError:
                with self._lock:
                    terminal_stop_sent = connection.terminal_stop_sent
                if not terminal_stop_sent:
                    raise
        finally:
            if connection is not None:
                connection.assembler.discard()
                with self._membership_changed:
                    self._connections.pop(connection.worker_id, None)
                    self._manifest_workers.discard(connection.worker_id)
                    self._membership_changed.notify_all()
                with contextlib.suppress(ValueError):
                    self.registry.transition(
                        connection.worker_id,
                        connection.session_id,
                        SessionState.DISCONNECTED,
                        time.monotonic(),
                    )
                if self._disconnect_handler is not None:
                    self._disconnect_handler(connection.worker_id, connection.session_id)

    def _read_bound(self, connection: _Connection) -> None:
        while True:
            frame = DTPFrame.read_from(
                connection.sock,
                recv_exact,
                bound_identity=(connection.session_id, connection.worker_id),
            )
            message: DtpControlMessage | None = None
            if frame.header.message_type not in {
                MESSAGE_TYPE_GRADIENT_CHUNK,
                MESSAGE_TYPE_PARAMETER_CHUNK,
            }:
                message = decode_control_message(frame.header.message_type, frame.payload)
            connection.validator.validate(frame.header, message)
            # Canonical liveness advances on every valid DTP message, not only
            # explicit HEARTBEAT frames.
            self.registry.heartbeat(connection.worker_id, connection.session_id, time.monotonic())
            with self._lock:
                connection.last_heartbeat_at = datetime.now(UTC).isoformat()
            identity = (
                TransferIdentity(
                    frame.header.session_id,
                    frame.header.worker_id,
                    frame.header.operation_id,
                    frame.header.tensor_id,
                )
                if frame.header.message_type
                in {
                    MESSAGE_TYPE_GRADIENT_META,
                    MESSAGE_TYPE_GRADIENT_CHUNK,
                    MESSAGE_TYPE_GRADIENT_END,
                    MESSAGE_TYPE_PARAMETER_META,
                    MESSAGE_TYPE_PARAMETER_CHUNK,
                }
                else None
            )

            if frame.header.message_type == MESSAGE_TYPE_SHARD_READY:
                assert message is not None
                connection.shard_id = int(message.shard_id)
                self.registry.transition(
                    connection.worker_id,
                    connection.session_id,
                    SessionState.SHARD_READY,
                    time.monotonic(),
                )
                connection.validator.set_phase(ConnectionPhase.SHARD_READY)
            elif frame.header.message_type == MESSAGE_TYPE_SHARD_ERROR:
                raise ProtocolError("Worker reported shard provisioning failure")
            elif frame.header.message_type == MESSAGE_TYPE_MODEL_MANIFEST:
                assert isinstance(message, ModelManifest)
                if message.to_dict() != self.manifest.to_dict():
                    raise ProtocolError("Worker Parameter Manifest does not match Runtime")
                with self._membership_changed:
                    self._manifest_workers.add(connection.worker_id)
                    self._membership_changed.notify_all()
                connection.validator.set_phase(ConnectionPhase.INITIALIZING)
            elif frame.header.message_type == MESSAGE_TYPE_MODEL_INIT:
                if connection.worker_id != 0:
                    raise ProtocolError("Only worker 0 may announce MODEL_INIT")
                with self._lock:
                    if connection.worker_id not in self._manifest_workers:
                        raise ProtocolError("MODEL_INIT requires the sender's verified manifest")
            elif frame.header.message_type == MESSAGE_TYPE_PARAMETER_META:
                assert identity is not None and isinstance(message, ParameterMeta)
                connection.assembler.begin_parameter(identity, message)
            elif frame.header.message_type == MESSAGE_TYPE_PARAMETER_CHUNK:
                assert identity is not None
                complete = connection.assembler.add_chunk(
                    identity, frame.header.chunk_index, frame.payload
                )
                if complete is not None and self._model_init_handler is not None:
                    self._model_init_handler(complete)
            elif frame.header.message_type == MESSAGE_TYPE_READY:
                assert isinstance(message, Ready)
                connection.local_model_version = int(message.model_version)
                self.registry.transition(
                    connection.worker_id,
                    connection.session_id,
                    SessionState.READY,
                    time.monotonic(),
                )
                connection.validator.set_phase(ConnectionPhase.READY)
            elif frame.header.message_type == MESSAGE_TYPE_HEARTBEAT:
                assert isinstance(message, Heartbeat)
                self.registry.heartbeat(
                    connection.worker_id, connection.session_id, time.monotonic()
                )
                connection.local_model_version = int(message.local_model_version)
            elif frame.header.message_type == MESSAGE_TYPE_GRADIENT_META:
                assert identity is not None and isinstance(message, GradientMeta)
                connection.assembler.begin_gradient(identity, message)
            elif frame.header.message_type == MESSAGE_TYPE_GRADIENT_CHUNK:
                assert identity is not None
                connection.assembler.add_chunk(identity, frame.header.chunk_index, frame.payload)
            elif frame.header.message_type == MESSAGE_TYPE_GRADIENT_END:
                assert identity is not None and isinstance(message, GradientEnd)
                complete = connection.assembler.end_gradient(identity, message)
                connection.validator.set_phase(ConnectionPhase.WAITING_PARAMETER)
                if self._gradient_handler is not None:
                    self._gradient_handler(self._to_contribution(complete))
            elif frame.header.message_type == MESSAGE_TYPE_PARAMETER_APPLIED:
                assert isinstance(message, WireParameterApplied)
                if self._parameter_applied_handler is not None:
                    self._parameter_applied_handler(
                        ParameterApplied(
                            attempt_id=message.attempt_id,
                            session_id=connection.session_id,
                            worker_id=connection.worker_id,
                            operation_id=frame.header.operation_id,
                            step_id=message.source_step_id,
                            model_version=message.model_version,
                        )
                    )
                connection.validator.set_phase(ConnectionPhase.WAITING_NEXT)

    def _to_contribution(self, transfer: CompletedTensorTransfer) -> Contribution:
        meta = transfer.metadata
        identity = transfer.identity
        return Contribution.from_gradient(
            np.frombuffer(transfer.data, dtype="<f4").astype(np.float32, copy=True),
            attempt_id=str(meta["attempt_id"]),
            session_id=identity.session_id,
            worker_id=identity.worker_id,
            operation_id=identity.operation_id,
            step_id=identity.operation_id,
            model_version=int(meta["model_version"]),
            shard_id=int(meta["shard_id"]),
            batch_id=int(meta["batch_id"]),
            batch_ordinal=int(meta["batch_ordinal"]),
            sample_count=int(meta["sample_count"]),
            parameter_manifest_hash=str(meta["parameter_manifest_hash"]),
            tensor_id=identity.tensor_id,
        )

    @staticmethod
    def _write_frame(sock: socket.socket, frame: DTPFrame) -> None:
        frame.write_to(sock, send_all)

    def _connection(self, worker_id: int) -> _Connection:
        with self._lock:
            try:
                return self._connections[worker_id]
            except KeyError as exc:
                raise ValueError(f"Worker {worker_id} is not connected") from exc

    def _send_control(
        self,
        connection: _Connection,
        message: DtpControlMessage,
        *,
        operation_id: int = NO_OPERATION,
    ) -> None:
        frame = build_control_frame(
            message,
            session_id=connection.session_id,
            worker_id=connection.worker_id,
            operation_id=operation_id,
        )
        connection.sender.send_frame(connection.sock, frame)

    def send_dataset_assignment(self, worker_id: int, assignment: DatasetAssignment) -> None:
        self._send_control(self._connection(worker_id), assignment)

    def mark_model_syncing(self) -> None:
        """Apply the Runtime-owned semantic transition after manifest admission."""
        with self._lock:
            if len(self._manifest_workers) != self.expected_workers:
                raise ValueError("Full Parameter Manifest membership is not ready")
        for session in self.registry.snapshot():
            if session.state == SessionState.SHARD_READY:
                self.registry.transition(
                    session.worker_id,
                    session.session_id,
                    SessionState.MODEL_SYNCING,
                    time.monotonic(),
                )

    def send_step_start(self, worker_id: int, operation_id: int, step: StepStart) -> None:
        connection = self._connection(worker_id)
        connection.validator.set_phase(ConnectionPhase.UPLOADING)
        self._send_control(connection, step, operation_id=operation_id)

    def broadcast_parameters(
        self,
        data: bytes,
        *,
        operation_id: int,
        source_step_id: int,
        model_version: int,
        tensor_id: int = 0,
        initialization: bool = False,
    ) -> None:
        for worker_id in self.worker_ids():
            connection = self._connection(worker_id)
            chunks = (len(data) + self._max_chunk - 1) // self._max_chunk
            meta = ParameterMeta.from_dict(
                {
                    "transfer_purpose": "model_update",
                    "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
                    "total_numel": self.manifest.total_numel,
                    "total_bytes": self.manifest.total_bytes,
                    "chunk_count": chunks,
                    "tensor_encoding": "fp32_le_v1",
                    "attempt_id": self.attempt_id,
                    "source_step_id": source_step_id,
                    "model_version_out": model_version,
                }
            )
            identity = TransferIdentity(connection.session_id, worker_id, operation_id, tensor_id)
            frames = build_tensor_transfer_frames(
                kind="parameter",
                identity=identity,
                metadata=meta,
                data=data,
                chunk_size=self._max_chunk,
            )
            if not initialization:
                connection.validator.set_phase(ConnectionPhase.APPLYING)
            connection.sender.send_transfer(connection.sock, frames)

    def send_stop(self, *, attempt_state: str, reason_code: str, reason: str) -> None:
        message = Stop.from_dict(
            {
                "reason_code": reason_code,
                "reason": reason,
                "attempt_state": attempt_state,
                "whether_reconnect_allowed": False,
            }
        )
        for worker_id in self.worker_ids():
            connection: _Connection | None = None
            try:
                connection = self._connection(worker_id)
                with self._lock:
                    connection.terminal_stop_sent = True
                self._send_control(connection, message)
            except Exception:
                if connection is not None:
                    with self._lock:
                        connection.terminal_stop_sent = False
