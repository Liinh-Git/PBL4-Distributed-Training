"""Bounded logical DTP tensor transfer assembly and atomic sending."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from pbl4.common.errors import ProtocolError
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    NO_OPERATION,
    NO_TENSOR,
    TENSOR_ENCODING_FP32_LE_V1,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
)
from pbl4.protocol.messages import GradientEnd, GradientMeta, ParameterMeta
from pbl4.protocol.parameter_manifest import ParameterManifest
from pbl4.protocol.tensor_codec import TensorCodec


@dataclass(frozen=True, slots=True)
class TransferIdentity:
    session_id: int
    worker_id: int
    operation_id: int
    tensor_id: int

    def __post_init__(self) -> None:
        fields = (
            ("session_id", self.session_id, 2**64 - 1),
            ("worker_id", self.worker_id, 2**32 - 1),
            ("operation_id", self.operation_id, 2**64 - 1),
            ("tensor_id", self.tensor_id, 2**32 - 1),
        )
        for name, value, maximum in fields:
            if type(value) is not int or not 0 <= value <= maximum:
                raise ProtocolError(f"{name} is outside its DTP wire width")
        if self.session_id == UNBOUND_SESSION:
            raise ProtocolError("Tensor transfer requires a bound session_id")
        if self.worker_id == UNASSIGNED_WORKER_ID:
            raise ProtocolError("Tensor transfer requires an assigned worker_id")
        if self.tensor_id == NO_TENSOR:
            raise ProtocolError("Tensor transfer requires a concrete tensor_id")


@dataclass(frozen=True, slots=True)
class CompletedTensorTransfer:
    kind: str
    identity: TransferIdentity
    metadata: dict[str, object]
    data: bytes


class TensorTransferAssembler:
    """Assemble one connection's active transfer without Runtime semantics."""

    def __init__(
        self,
        manifest: ParameterManifest,
        *,
        max_model_bytes: int,
        max_tensor_chunk_bytes: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    ) -> None:
        if max_model_bytes < manifest.total_bytes:
            raise ProtocolError("Configured max_model_bytes is smaller than the manifest")
        if type(max_tensor_chunk_bytes) is not int or max_tensor_chunk_bytes <= 0:
            raise ProtocolError("max_tensor_chunk_bytes must be positive")
        self._manifest = manifest
        self._max_model_bytes = max_model_bytes
        self._max_chunk = max_tensor_chunk_bytes
        self.discard()

    @property
    def active(self) -> bool:
        return self._identity is not None

    def begin_gradient(self, identity: TransferIdentity, meta: GradientMeta) -> None:
        try:
            self._begin("gradient", identity, meta.to_dict())
        except ProtocolError:
            self.discard()
            raise

    def begin_parameter(self, identity: TransferIdentity, meta: ParameterMeta) -> None:
        try:
            self._begin("parameter", identity, meta.to_dict())
        except ProtocolError:
            self.discard()
            raise

    def _begin(self, kind: str, identity: TransferIdentity, metadata: dict[str, object]) -> None:
        if self.active:
            raise ProtocolError("A tensor transfer is already active on this connection")
        if metadata["parameter_manifest_hash"] != self._manifest.parameter_manifest_hash:
            raise ProtocolError("Tensor transfer Parameter Manifest mismatch")
        if metadata["tensor_encoding"] != TENSOR_ENCODING_FP32_LE_V1:
            raise ProtocolError("Unsupported tensor encoding")
        if metadata["total_numel"] != self._manifest.total_numel:
            raise ProtocolError("Tensor transfer total_numel mismatch")
        total_bytes = metadata["total_bytes"]
        chunk_count = metadata["chunk_count"]
        if total_bytes != self._manifest.total_bytes or total_bytes > self._max_model_bytes:
            raise ProtocolError("Tensor transfer total_bytes is unsafe or mismatched")
        minimum_chunks = math.ceil(total_bytes / self._max_chunk)
        if not minimum_chunks <= chunk_count <= total_bytes:
            raise ProtocolError("Tensor transfer chunk_count is impossible")
        self._kind = kind
        self._identity = identity
        self._metadata = dict(metadata)
        self._chunks = []
        self._received_bytes = 0

    def add_chunk(
        self, identity: TransferIdentity, chunk_index: int, payload: bytes
    ) -> CompletedTensorTransfer | None:
        try:
            return self._add_chunk(identity, chunk_index, payload)
        except ProtocolError:
            self.discard()
            raise

    def _add_chunk(
        self, identity: TransferIdentity, chunk_index: int, payload: bytes
    ) -> CompletedTensorTransfer | None:
        self._require_identity(identity)
        if type(chunk_index) is not int or chunk_index != len(self._chunks):
            raise ProtocolError("Tensor chunks must be unique, zero-based and continuous")
        raw = bytes(payload)
        if not raw or len(raw) > self._max_chunk:
            raise ProtocolError("Tensor chunk is empty or exceeds negotiated limit")
        expected_count = self._metadata["chunk_count"]
        if chunk_index >= expected_count:
            raise ProtocolError("Tensor chunk index exceeds declared chunk_count")
        if self._received_bytes + len(raw) > self._metadata["total_bytes"]:
            raise ProtocolError("Tensor transfer byte overflow")
        self._chunks.append(raw)
        self._received_bytes += len(raw)
        if self._kind == "parameter" and len(self._chunks) == expected_count:
            return self._complete()
        return None

    def end_gradient(self, identity: TransferIdentity, end: GradientEnd) -> CompletedTensorTransfer:
        try:
            return self._end_gradient(identity, end)
        except ProtocolError:
            self.discard()
            raise

    def _end_gradient(
        self, identity: TransferIdentity, end: GradientEnd
    ) -> CompletedTensorTransfer:
        self._require_identity(identity)
        if self._kind != "gradient":
            raise ProtocolError("GRADIENT_END cannot terminate a parameter transfer")
        values = end.to_dict()
        if (
            values["total_bytes"] != self._metadata["total_bytes"]
            or values["chunk_count"] != self._metadata["chunk_count"]
        ):
            raise ProtocolError("GRADIENT_END totals do not match GRADIENT_META")
        completed = self._complete()
        digest = values.get("gradient_sha256")
        if digest is not None and hashlib.sha256(completed.data).hexdigest() != digest.lower():
            self.discard()
            raise ProtocolError("Gradient SHA-256 mismatch")
        return completed

    def _complete(self) -> CompletedTensorTransfer:
        if len(self._chunks) != self._metadata["chunk_count"]:
            raise ProtocolError("Tensor transfer is missing chunks")
        if self._received_bytes != self._metadata["total_bytes"]:
            raise ProtocolError("Tensor transfer total byte mismatch")
        raw = TensorCodec.validate_buffer(
            b"".join(self._chunks), self._manifest, max_model_bytes=self._max_model_bytes
        )
        result = CompletedTensorTransfer(self._kind, self._identity, dict(self._metadata), raw)
        self.discard()
        return result

    def _require_identity(self, identity: TransferIdentity) -> None:
        if not self.active:
            raise ProtocolError("Tensor chunk/end arrived before metadata")
        if identity != self._identity:
            raise ProtocolError("Tensor transfer identity mismatch")

    def discard(self) -> None:
        """Discard partial state on disconnect, timeout, protocol error or termination."""
        self._kind: str = ""
        self._identity: TransferIdentity | None = None
        self._metadata: dict[str, object] = {}
        self._chunks: list[bytes] = []
        self._received_bytes = 0


class LogicalTransferSender:
    """Hold one per-connection lock across every frame in a logical transfer."""

    def __init__(
        self,
        send_frame: Callable[[Any, DTPFrame], None],
        *,
        lock: Any | None = None,
    ) -> None:
        self._send_frame = send_frame
        self._lock = lock if lock is not None else Lock()

    def send_frame(self, sock: Any, frame: DTPFrame) -> None:
        with self._lock:
            self._send_frame(sock, frame)

    def send_transfer(self, sock: Any, frames: Iterable[DTPFrame]) -> None:
        sequence = tuple(frames)
        if len(sequence) < 2:
            raise ProtocolError("A logical tensor transfer requires metadata and chunk frames")
        with self._lock:
            for frame in sequence:
                self._send_frame(sock, frame)


def build_tensor_transfer_frames(
    *,
    kind: str,
    identity: TransferIdentity,
    metadata: GradientMeta | ParameterMeta,
    data: bytes,
    chunk_size: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    gradient_end: GradientEnd | None = None,
) -> tuple[DTPFrame, ...]:
    """Build one immutable logical transfer suitable for transaction sending."""
    from pbl4.protocol.constants import (
        MESSAGE_TYPE_GRADIENT_CHUNK,
        MESSAGE_TYPE_PARAMETER_CHUNK,
        NO_CHUNK,
    )
    from pbl4.protocol.messages import build_control_frame, build_frame

    if kind not in {"gradient", "parameter"}:
        raise ProtocolError("Unknown tensor transfer kind")
    if kind == "gradient" and not isinstance(metadata, GradientMeta):
        raise ProtocolError("Gradient transfer requires GradientMeta")
    if kind == "parameter" and not isinstance(metadata, ParameterMeta):
        raise ProtocolError("Parameter transfer requires ParameterMeta")
    if kind == "gradient" and identity.operation_id == NO_OPERATION:
        raise ProtocolError("Gradient transfer requires a concrete operation_id")
    chunks = TensorCodec.chunk(data, chunk_size)
    if metadata.chunk_count != len(chunks) or metadata.total_bytes != len(data):
        raise ProtocolError("Metadata does not describe the immutable tensor snapshot")
    common = {
        "session_id": identity.session_id,
        "worker_id": identity.worker_id,
        "operation_id": identity.operation_id,
        "tensor_id": identity.tensor_id,
    }
    frames = [build_control_frame(metadata, chunk_index=NO_CHUNK, **common)]
    chunk_type = MESSAGE_TYPE_GRADIENT_CHUNK if kind == "gradient" else MESSAGE_TYPE_PARAMETER_CHUNK
    frames.extend(
        build_frame(chunk_type, chunk, chunk_index=index, **common)
        for index, chunk in enumerate(chunks)
    )
    if kind == "gradient":
        if gradient_end is None:
            raise ProtocolError("Gradient transfer requires GRADIENT_END")
        frames.append(build_control_frame(gradient_end, chunk_index=NO_CHUNK, **common))
    elif gradient_end is not None:
        raise ProtocolError("Parameter transfer has no END message in DTP/1")
    return tuple(frames)
