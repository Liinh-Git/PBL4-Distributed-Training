"""MCP/1 wire message definitions and payload schemas.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Wire-level command, response, and event envelope schemas for MCP/1.
- Serialization-neutral data contracts between Runtime and Management Backend.

MUST NOT OWN
------------
- Network socket I/O (owned by ManagementEndpoint in Runtime and RuntimeGateway in Backend).
- PostgreSQL data persistence or REST API conversion.
- Training tensor transport (training flows exclusively over DTP/1).

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 message definitions are strictly wire-format DTOs.
- No direct imports of Runtime training internals or Backend database models.

IMPLEMENTATION STATUS
---------------------
Implemented per the approved MCP/1 wire specification. Every envelope carries
the seven mandatory top-level snake_case fields; unknown extra fields are
tolerated and ignored. ``payload`` must be a JSON object.
"""

from __future__ import annotations

from dataclasses import dataclass

from pbl4.common.errors import ProtocolError
from pbl4.management_protocol.constants import MCP_PROTOCOL_VERSION

_REQUIRED_FIELDS: tuple[str, ...] = (
    "protocol_version",
    "message_type",
    "message_id",
    "correlation_id",
    "sent_at",
    "runtime_instance_id",
    "payload",
)


@dataclass(frozen=True, slots=True)
class McpEnvelope:
    """Wire-format MCP/1 JSON envelope (serialization-neutral DTO).

    All seven fields are mandatory top-level snake_case keys:
    ``protocol_version`` (int, always 1), ``message_type``, ``message_id``,
    ``correlation_id``, ``sent_at``, ``runtime_instance_id`` (strings), and
    ``payload`` (a JSON object). ``correlation_id`` may be an empty string when
    no correlation applies; the other string fields must be non-empty.
    """

    message_type: str
    message_id: str
    correlation_id: str
    sent_at: str
    runtime_instance_id: str
    payload: dict[str, object]
    protocol_version: int = MCP_PROTOCOL_VERSION

    def to_dict(self) -> dict[str, object]:
        """Project the envelope to its canonical top-level JSON object form."""
        return {
            "protocol_version": self.protocol_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "sent_at": self.sent_at,
            "runtime_instance_id": self.runtime_instance_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: object) -> McpEnvelope:
        """Validate a decoded JSON object and project it into an envelope.

        Raises:
            ProtocolError: if the object shape violates the MCP/1 envelope
                contract (non-object root, missing fields, wrong types, or an
                unsupported protocol_version).
        """
        if not isinstance(data, dict):
            raise ProtocolError("MCP message root must be a JSON object")
        missing = [field for field in _REQUIRED_FIELDS if field not in data]
        if missing:
            raise ProtocolError(f"MCP message missing required fields: {', '.join(missing)}")
        protocol_version = data["protocol_version"]
        if (
            isinstance(protocol_version, bool)
            or not isinstance(protocol_version, int)
            or protocol_version != MCP_PROTOCOL_VERSION
        ):
            raise ProtocolError(f"MCP protocol_version must be the integer {MCP_PROTOCOL_VERSION}")
        for field_name in ("message_type", "message_id", "sent_at", "runtime_instance_id"):
            value = data[field_name]
            if not isinstance(value, str) or not value:
                raise ProtocolError(f"MCP field {field_name!r} must be a non-empty string")
        correlation_id = data["correlation_id"]
        if not isinstance(correlation_id, str):
            raise ProtocolError("MCP field 'correlation_id' must be a string")
        payload = data["payload"]
        if not isinstance(payload, dict):
            raise ProtocolError("MCP field 'payload' must be a JSON object")
        return cls(
            message_type=data["message_type"],
            message_id=data["message_id"],
            correlation_id=correlation_id,
            sent_at=data["sent_at"],
            runtime_instance_id=data["runtime_instance_id"],
            payload=payload,
            protocol_version=protocol_version,
        )
