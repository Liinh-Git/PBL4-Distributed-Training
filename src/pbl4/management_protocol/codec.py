"""MCP/1 wire codec — serialization and deserialization of management frames.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Framing and serialization of MCP/1 messages (length prefix and UTF-8 JSON payload).
- Deserialization and wire validation of incoming MCP/1 frames.
- Envelope contract validation (seven mandatory top-level fields).

MUST NOT OWN
------------
- Network transport or socket I/O (delegated to transport layer; socket access is
  injected into read_message/write_message as callables).
- Runtime state machine or command execution logic.
- Management Backend service or persistence handling.

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 codec is a pure wire-format parser with zero runtime, backend, or db dependencies.
- Frames are [4-byte unsigned big-endian json_length][json_length UTF-8 JSON bytes].
- json_length == 0 or above the configured maximum, invalid UTF-8/JSON, a non-object
  root, or an invalid envelope must fail with ProtocolError (callers then disconnect).

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib only (struct + json). Zero framework and zero
transport imports; socket access is dependency-injected.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Callable
from typing import Any

from pbl4.common.errors import ProtocolError
from pbl4.management_protocol.constants import (
    DEFAULT_MAX_MESSAGE_BYTES,
    LENGTH_PREFIX_BYTES,
)
from pbl4.management_protocol.messages import McpEnvelope

_LENGTH_PREFIX_STRUCT = struct.Struct(">I")

if _LENGTH_PREFIX_STRUCT.size != LENGTH_PREFIX_BYTES:
    raise RuntimeError(
        f"MCP length prefix layout is {_LENGTH_PREFIX_STRUCT.size} bytes; "
        f"wire spec requires {LENGTH_PREFIX_BYTES}"
    )


def _parse_body(body: bytes) -> McpEnvelope:
    """Decode UTF-8 JSON bytes into a validated MCP/1 envelope."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"MCP body is not valid UTF-8 JSON: {exc}") from exc
    return McpEnvelope.from_dict(data)


class McpCodec:
    """Encode and decode MCP/1 wire messages."""

    @staticmethod
    def encode(
        envelope: McpEnvelope,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> bytes:
        """Serialize an envelope to [4-byte big-endian length][UTF-8 JSON bytes].

        Raises:
            ProtocolError: if the JSON body is empty or exceeds
                ``max_message_bytes``.
        """
        body = json.dumps(envelope.to_dict(), ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if not 0 < len(body) <= max_message_bytes:
            raise ProtocolError(f"MCP JSON body length {len(body)} outside 1..{max_message_bytes}")
        return _LENGTH_PREFIX_STRUCT.pack(len(body)) + body

    @staticmethod
    def decode(
        data: bytes,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> McpEnvelope:
        """Decode one complete MCP/1 frame from raw bytes.

        Raises:
            ProtocolError: on truncated prefix, zero/oversized length, length
                mismatch, invalid UTF-8/JSON, or an invalid envelope.
        """
        if len(data) < LENGTH_PREFIX_BYTES:
            raise ProtocolError(
                f"MCP frame truncated: {len(data)} bytes is smaller than the "
                f"{LENGTH_PREFIX_BYTES}-byte length prefix"
            )
        (length,) = _LENGTH_PREFIX_STRUCT.unpack(data[:LENGTH_PREFIX_BYTES])
        if length == 0:
            raise ProtocolError("MCP json_length must be greater than 0")
        if length > max_message_bytes:
            raise ProtocolError(f"MCP json_length {length} exceeds limit {max_message_bytes}")
        body = data[LENGTH_PREFIX_BYTES:]
        if len(body) != length:
            raise ProtocolError(f"MCP frame declares {length} JSON bytes, got {len(body)}")
        return _parse_body(body)

    @staticmethod
    def read_message(
        sock: Any,
        recv_exact_fn: Callable[[Any, int], bytes],
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> McpEnvelope:
        """Read one MCP/1 frame via the injected exact-byte reader.

        Reads the 4-byte length prefix first, then exactly ``json_length``
        bytes, then parses and validates the JSON envelope.

        Raises:
            ProtocolError: on zero/oversized length, invalid UTF-8/JSON, or an
                invalid envelope (callers must treat this as fatal for the
                connection).
            TransportError: propagated from ``recv_exact_fn`` on EOF/timeout.
        """
        prefix = recv_exact_fn(sock, LENGTH_PREFIX_BYTES)
        (length,) = _LENGTH_PREFIX_STRUCT.unpack(prefix)
        if length == 0:
            raise ProtocolError("MCP json_length must be greater than 0")
        if length > max_message_bytes:
            raise ProtocolError(f"MCP json_length {length} exceeds limit {max_message_bytes}")
        body = recv_exact_fn(sock, length)
        return _parse_body(body)

    @staticmethod
    def write_message(
        sock: Any,
        send_fn: Callable[[Any, bytes], None],
        envelope: McpEnvelope,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> None:
        """Push one MCP/1 frame through the injected send function."""
        send_fn(sock, McpCodec.encode(envelope, max_message_bytes=max_message_bytes))
