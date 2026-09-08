"""Framework-neutral contiguous little-endian FP32 tensor codec."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence

from pbl4.common.errors import ProtocolError
from pbl4.protocol.constants import DEFAULT_MAX_TENSOR_CHUNK_BYTES, FLOAT32_BYTES
from pbl4.protocol.parameter_manifest import ParameterManifest


class TensorCodec:
    """Encode, validate, chunk and reassemble canonical FP32 buffers."""

    @staticmethod
    def encode(values: Iterable[float], *, expected_numel: int | None = None) -> bytes:
        packed = bytearray()
        count = 0
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProtocolError("Tensor values must be real numbers")
            number = float(value)
            if not math.isfinite(number):
                raise ProtocolError("Tensor values must be finite")
            try:
                packed.extend(struct.pack("<f", number))
            except (OverflowError, struct.error) as exc:
                raise ProtocolError("Tensor value is outside finite float32 range") from exc
            count += 1
        if expected_numel is not None and count != expected_numel:
            raise ProtocolError("Tensor element count mismatch")
        return bytes(packed)

    @staticmethod
    def decode(buffer: bytes | bytearray | memoryview) -> tuple[float, ...]:
        raw = bytes(buffer)
        if not raw or len(raw) % FLOAT32_BYTES:
            raise ProtocolError("Canonical tensor buffer must be nonempty whole FP32 values")
        values = tuple(item[0] for item in struct.iter_unpack("<f", raw))
        if not all(math.isfinite(value) for value in values):
            raise ProtocolError("Canonical tensor buffer contains NaN or Infinity")
        return values

    @staticmethod
    def validate_buffer(
        buffer: bytes | bytearray | memoryview,
        manifest: ParameterManifest,
        *,
        max_model_bytes: int | None = None,
    ) -> bytes:
        raw = bytes(buffer)
        if len(raw) != manifest.total_bytes:
            raise ProtocolError("Tensor byte count does not match Parameter Manifest")
        if max_model_bytes is not None and len(raw) > max_model_bytes:
            raise ProtocolError("Tensor exceeds configured max_model_bytes")
        TensorCodec.decode(raw)
        return raw

    @staticmethod
    def chunk(
        buffer: bytes | bytearray | memoryview,
        chunk_size: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    ) -> tuple[bytes, ...]:
        if type(chunk_size) is not int or chunk_size <= 0:
            raise ProtocolError("chunk_size must be a positive integer")
        raw = bytes(buffer)
        if not raw:
            raise ProtocolError("Cannot chunk an empty tensor buffer")
        return tuple(raw[index : index + chunk_size] for index in range(0, len(raw), chunk_size))

    @staticmethod
    def reassemble(
        chunks: Sequence[bytes],
        *,
        expected_total_bytes: int,
        expected_chunk_count: int,
        max_chunk_bytes: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    ) -> bytes:
        if len(chunks) != expected_chunk_count or expected_chunk_count <= 0:
            raise ProtocolError("Tensor chunk count mismatch")
        if any(not chunk or len(chunk) > max_chunk_bytes for chunk in chunks):
            raise ProtocolError("Tensor chunk is empty or exceeds the negotiated limit")
        raw = b"".join(chunks)
        if len(raw) != expected_total_bytes:
            raise ProtocolError("Reassembled tensor byte count mismatch")
        return raw
