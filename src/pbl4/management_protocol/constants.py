"""MCP/1 wire protocol constants.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Wire-level protocol constants for MCP/1.
- Frame formatting constants (4-byte big-endian length prefix).
- Default maximum MCP/1 JSON body size.

MUST NOT OWN
------------
- Runtime or Parameter Server implementation details.
- Management Backend service or repository imports.
- Database queries, REST status codes, or HTTP semantics.
- Raw tensor / gradient payload definitions.

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 is dedicated to management, telemetry, and control signaling.
- Zero imports of runtime, management_backend, worker, torch, or database libraries.

IMPLEMENTATION STATUS
---------------------
Implemented per the approved MCP/1 wire specification: each frame is a 4-byte
unsigned big-endian json_length followed by json_length bytes of UTF-8 JSON.
"""

from __future__ import annotations

from enum import StrEnum

# MCP/1 protocol version carried in every JSON envelope
MCP_PROTOCOL_VERSION: int = 1

# Frame format: 4-byte unsigned big-endian length prefix + UTF-8 JSON body
LENGTH_PREFIX_BYTES: int = 4

# Default upper bound for a single MCP/1 JSON body (4 MiB)
DEFAULT_MAX_MESSAGE_BYTES: int = 4 * 1024 * 1024


class McpMessageType(StrEnum):
    MGMT_HELLO = "MGMT_HELLO"
    MGMT_HELLO_ACK = "MGMT_HELLO_ACK"
    GET_STATE = "GET_STATE"
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    START_ATTEMPT = "START_ATTEMPT"
    ABORT_ATTEMPT = "ABORT_ATTEMPT"
    REQUEST_CHECKPOINT = "REQUEST_CHECKPOINT"
    RESOLVE_DATASET_BUILD = "RESOLVE_DATASET_BUILD"
    DATASET_BUILD_RESOLVED = "DATASET_BUILD_RESOLVED"
    COMMAND_RESULT = "COMMAND_RESULT"
    RUNTIME_EVENT = "RUNTIME_EVENT"
    ERROR = "ERROR"


COMMAND_RESULT_STATUSES: frozenset[str] = frozenset(
    {"ACCEPTED", "DEFERRED", "SUCCEEDED", "REJECTED", "FAILED"}
)
EVENT_SEVERITIES: frozenset[str] = frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"})


COMMAND_RESULT_STATUSES: frozenset[str] = frozenset(
    {"ACCEPTED", "DEFERRED", "SUCCEEDED", "REJECTED", "FAILED"}
)
EVENT_SEVERITIES: frozenset[str] = frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"})
