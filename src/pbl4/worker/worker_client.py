"""Worker-side DTP/1 TCP composition; local compute remains in TrainingLoop."""

from __future__ import annotations

import contextlib
import hashlib
import socket
import threading
from collections.abc import Callable
from uuid import uuid4

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    MESSAGE_TYPE_PARAMETER_CHUNK,
    MESSAGE_TYPE_PARAMETER_META,
    NO_OPERATION,
)
from pbl4.protocol.messages import (
    DtpControlMessage,
    GradientEnd,
    GradientMeta,
    Hello,
    HelloAck,
    ModelInit,
    ModelManifest,
    ParameterApplied,
    ParameterMeta,
    Ready,
    ShardReady,
    StepStart,
    build_control_frame,
    decode_control_message,
)
from pbl4.protocol.parameter_manifest import ParameterManifest
from pbl4.protocol.session import ConnectionPhase, ConnectionProtocolValidator, PeerRole
from pbl4.protocol.transfer import (
    CompletedTensorTransfer,
    LogicalTransferSender,
    TensorTransferAssembler,
    TransferIdentity,
    build_tensor_transfer_frames,
)
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_client import TcpClient

MessageHandler = Callable[[DtpControlMessage, int], None]
ParameterHandler = Callable[[CompletedTensorTransfer], None]
DisconnectHandler = Callable[[], None]


class WorkerClient:
    """Persistent, fully networked DTP client shared by every worker rank."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        node_label: str,
        manifest: ParameterManifest,
        message_handler: MessageHandler | None = None,
        parameter_handler: ParameterHandler | None = None,
        disconnect_handler: DisconnectHandler | None = None,
    ) -> None:
        self._transport = TcpClient(host, port, timeout=None, connect_timeout=5.0)
        self.node_label = node_label
        self.manifest = manifest
        self._message_handler = message_handler
        self._parameter_handler = parameter_handler
        self._disconnect_handler = disconnect_handler
        self._validator = ConnectionProtocolValidator(inbound_peer=PeerRole.RUNTIME)
        self._assembler = TensorTransferAssembler(manifest, max_model_bytes=manifest.total_bytes)
        self._sender = LogicalTransferSender(self._write_frame)
        self._reader: threading.Thread | None = None
        self._closing = threading.Event()
        self.session_id: int | None = None
        self.worker_id: int | None = None
        self.attempt_id: str | None = None
        self.job_id: str | None = None
        self.expected_workers: int | None = None
        self.max_tensor_chunk_bytes = 1024 * 1024

    @property
    def connected(self) -> bool:
        return self._transport.connected and self.session_id is not None

    def connect(self) -> HelloAck:
        self._transport.connect()
        hello = Hello.from_dict(
            {
                "node_label": self.node_label,
                "client_instance_id": str(uuid4()),
                "role": "worker",
                "protocol_version": 1,
                "framework_adapter": "pytorch",
                "supported_tensor_encoding": ["fp32_le_v1"],
                "supported_strategy_capabilities": ["strict_bsp"],
            }
        )
        self._write_frame(
            self._transport.sock,
            build_control_frame(hello),
        )
        frame = DTPFrame.read_from(self._transport.sock, recv_exact)
        message = decode_control_message(frame.header.message_type, frame.payload)
        if not isinstance(message, HelloAck):
            raise ProtocolError("Runtime did not reply with HELLO_ACK")
        self.session_id = int(message.session_id)
        self.worker_id = int(message.worker_id)
        self.attempt_id = str(message.attempt_id)
        self.job_id = str(message.job_id)
        self.expected_workers = int(message.expected_workers)
        self.max_tensor_chunk_bytes = int(message.max_tensor_chunk_bytes)
        self._validator.validate(frame.header, message)
        self._validator.bind(self.session_id, self.worker_id)
        self._closing.clear()
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"pbl4-worker-{self.worker_id}-dtp-reader",
            daemon=True,
        )
        self._reader.start()
        return message

    def disconnect(self) -> None:
        self._closing.set()
        self._assembler.discard()
        self._transport.disconnect()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        self._reader = None

    def _identity(self) -> tuple[int, int]:
        if self.session_id is None or self.worker_id is None:
            raise TransportError("Worker is not registered")
        return self.session_id, self.worker_id

    @staticmethod
    def _write_frame(sock: socket.socket, frame: DTPFrame) -> None:
        frame.write_to(sock, send_all)

    def _send_control(
        self, message: DtpControlMessage, *, operation_id: int = NO_OPERATION
    ) -> None:
        session_id, worker_id = self._identity()
        self._sender.send_frame(
            self._transport.sock,
            build_control_frame(
                message,
                session_id=session_id,
                worker_id=worker_id,
                operation_id=operation_id,
            ),
        )

    def send_shard_ready(self, ready: ShardReady) -> None:
        self._send_control(ready)
        self._validator.set_phase(ConnectionPhase.SHARD_READY)

    def send_model_manifest(self) -> None:
        self._send_control(ModelManifest.from_dict(self.manifest.to_dict()))
        self._validator.set_phase(ConnectionPhase.INITIALIZING)

    def send_model_init(self, data: bytes, *, initialization_seed: int, tensor_id: int = 0) -> None:
        session_id, worker_id = self._identity()
        if worker_id != 0:
            raise ProtocolError("Only assigned worker 0 may send MODEL_INIT")
        self._send_control(
            ModelInit.from_dict(
                {
                    "initialization_seed": initialization_seed,
                    "target_model_version": 0,
                    "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
                    "total_bytes": self.manifest.total_bytes,
                    "initialization_policy_version": 1,
                }
            )
        )
        chunk_count = (len(data) + self.max_tensor_chunk_bytes - 1) // self.max_tensor_chunk_bytes
        meta = ParameterMeta.from_dict(
            {
                "transfer_purpose": "model_init",
                "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
                "total_numel": self.manifest.total_numel,
                "total_bytes": self.manifest.total_bytes,
                "chunk_count": chunk_count,
                "tensor_encoding": "fp32_le_v1",
                "model_version": 0,
            }
        )
        identity = TransferIdentity(session_id, worker_id, NO_OPERATION, tensor_id)
        frames = build_tensor_transfer_frames(
            kind="parameter",
            identity=identity,
            metadata=meta,
            data=data,
            chunk_size=self.max_tensor_chunk_bytes,
        )
        self._sender.send_transfer(self._transport.sock, frames)

    def send_ready(self, *, model_version: int, dataset_build_id: str, shard_id: int) -> None:
        self._send_control(
            Ready.from_dict(
                {
                    "model_version": model_version,
                    "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
                    "dataset_build_id": dataset_build_id,
                    "shard_id": shard_id,
                }
            )
        )
        self._validator.set_phase(ConnectionPhase.READY)

    def send_gradient(
        self,
        data: bytes,
        *,
        operation_id: int,
        model_version: int,
        shard_id: int,
        batch_id: int,
        batch_ordinal: int,
        sample_count: int,
        tensor_id: int = 0,
        loss: float | None = None,
    ) -> None:
        session_id, worker_id = self._identity()
        chunk_count = (len(data) + self.max_tensor_chunk_bytes - 1) // self.max_tensor_chunk_bytes
        values: dict[str, object] = {
            "attempt_id": self.attempt_id,
            "model_version": model_version,
            "shard_id": shard_id,
            "batch_id": batch_id,
            "batch_ordinal": batch_ordinal,
            "sample_count": sample_count,
            "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
            "tensor_encoding": "fp32_le_v1",
            "total_numel": self.manifest.total_numel,
            "total_bytes": self.manifest.total_bytes,
            "chunk_count": chunk_count,
        }
        if loss is not None:
            values["loss"] = loss
        meta = GradientMeta.from_dict(values)
        end = GradientEnd.from_dict(
            {
                "total_bytes": len(data),
                "chunk_count": chunk_count,
                "transfer_complete": True,
                "gradient_sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        identity = TransferIdentity(session_id, worker_id, operation_id, tensor_id)
        frames = build_tensor_transfer_frames(
            kind="gradient",
            identity=identity,
            metadata=meta,
            data=data,
            chunk_size=self.max_tensor_chunk_bytes,
            gradient_end=end,
        )
        self._sender.send_transfer(self._transport.sock, frames)
        self._validator.set_phase(ConnectionPhase.WAITING_PARAMETER)

    def send_parameter_applied(
        self, *, operation_id: int, source_step_id: int, model_version: int
    ) -> None:
        self._send_control(
            ParameterApplied.from_dict(
                {
                    "attempt_id": self.attempt_id,
                    "model_version": model_version,
                    "parameter_manifest_hash": self.manifest.parameter_manifest_hash,
                    "apply_ok": True,
                    "source_step_id": source_step_id,
                }
            ),
            operation_id=operation_id,
        )
        self._validator.set_phase(ConnectionPhase.WAITING_NEXT)

    def _read_loop(self) -> None:
        try:
            while not self._closing.is_set():
                session_id, worker_id = self._identity()
                frame = DTPFrame.read_from(
                    self._transport.sock,
                    recv_exact,
                    bound_identity=(session_id, worker_id),
                )
                message: DtpControlMessage | None = None
                if frame.header.message_type != MESSAGE_TYPE_PARAMETER_CHUNK:
                    message = decode_control_message(frame.header.message_type, frame.payload)
                self._validator.validate(frame.header, message)
                identity = (
                    TransferIdentity(
                        frame.header.session_id,
                        frame.header.worker_id,
                        frame.header.operation_id,
                        frame.header.tensor_id,
                    )
                    if frame.header.message_type
                    in {MESSAGE_TYPE_PARAMETER_META, MESSAGE_TYPE_PARAMETER_CHUNK}
                    else None
                )
                if frame.header.message_type == MESSAGE_TYPE_PARAMETER_META:
                    assert identity is not None and isinstance(message, ParameterMeta)
                    self._assembler.begin_parameter(identity, message)
                elif frame.header.message_type == MESSAGE_TYPE_PARAMETER_CHUNK:
                    assert identity is not None
                    complete = self._assembler.add_chunk(
                        identity, frame.header.chunk_index, frame.payload
                    )
                    if complete is not None:
                        self._validator.set_phase(ConnectionPhase.APPLYING)
                        if self._parameter_handler is not None:
                            self._parameter_handler(complete)
                elif isinstance(message, StepStart):
                    self._validator.set_phase(ConnectionPhase.UPLOADING)
                    if self._message_handler is not None:
                        self._message_handler(message, frame.header.operation_id)
                elif message is not None and self._message_handler is not None:
                    self._message_handler(message, frame.header.operation_id)
        except Exception:
            if not self._closing.is_set() and self._disconnect_handler is not None:
                self._disconnect_handler()
        finally:
            self._assembler.discard()
            with contextlib.suppress(Exception):
                self._transport.disconnect()
