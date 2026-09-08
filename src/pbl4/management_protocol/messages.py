"""Canonical MCP/1 envelope, payload schemas and correlation helpers."""

# ruff: noqa: RUF012

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from pbl4.common.errors import ProtocolError
from pbl4.management_protocol.constants import (
    COMMAND_RESULT_STATUSES,
    EVENT_SEVERITIES,
    MCP_PROTOCOL_VERSION,
    McpMessageType,
)

_MISSING = object()


def _valid(value: object, kind: object) -> bool:
    if kind == "string":
        return isinstance(value, str) and bool(value) and len(value) <= 16384
    if kind == "int":
        return type(value) is int
    if kind == "nonnegative_int":
        return type(value) is int and value >= 0
    if kind == "positive_int":
        return type(value) is int and value > 0
    if kind == "bool":
        return type(value) is bool
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "int_list":
        return isinstance(value, list) and bool(value) and all(type(item) is int for item in value)
    if isinstance(kind, tuple) and kind[0] == "nullable":
        return value is None or _valid(value, kind[1])
    return False


_FORBIDDEN_DATA_KEYS = frozenset(
    {
        "gradient_bytes",
        "parameter_bytes",
        "tensor_bytes",
        "raw_gradient",
        "raw_parameters",
        "gradient_chunks",
        "parameter_chunks",
    }
)


def _validate_json(value: object, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError(f"{path} contains NaN or Infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProtocolError(f"{path} keys must be strings")
            if key.lower() in _FORBIDDEN_DATA_KEYS:
                raise ProtocolError("MCP/1 must not carry raw training tensor data")
            _validate_json(item, f"{path}.{key}")
        return
    raise ProtocolError(f"{path} contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class McpPayload:
    values: dict[str, object]
    MESSAGE_TYPE: ClassVar[McpMessageType]
    REQUIRED: ClassVar[dict[str, object]] = {}
    OPTIONAL: ClassVar[dict[str, object]] = {}
    ENUMS: ClassVar[dict[str, frozenset[object]]] = {}

    def __post_init__(self) -> None:
        if not isinstance(self.values, dict):
            raise ProtocolError("MCP payload must be a JSON object")
        data = dict(self.values)
        _validate_json(data)
        allowed = set(self.REQUIRED) | set(self.OPTIONAL)
        if set(data) - allowed:
            raise ProtocolError(f"{type(self).__name__} contains unknown fields")
        missing = set(self.REQUIRED) - set(data)
        if missing:
            raise ProtocolError(f"{type(self).__name__} missing fields: {sorted(missing)}")
        for name, kind in {**self.REQUIRED, **self.OPTIONAL}.items():
            value = data.get(name, _MISSING)
            if value is not _MISSING and not _valid(value, kind):
                raise ProtocolError(f"{type(self).__name__}.{name} has wrong type or range")
        for name, choices in self.ENUMS.items():
            if name in data and data[name] not in choices:
                raise ProtocolError(f"{type(self).__name__}.{name} has invalid enum value")
        self._validate(data)
        object.__setattr__(self, "values", MappingProxyType(data))

    def _validate(self, data: dict[str, object]) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        values = object.__getattribute__(self, "values")
        try:
            return values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self) -> dict[str, object]:
        return dict(self.values)

    @classmethod
    def from_dict(cls, value: object) -> McpPayload:
        if not isinstance(value, dict):
            raise ProtocolError("MCP payload must be a JSON object")
        return cls(value)


class MgmtHello(McpPayload):
    MESSAGE_TYPE = McpMessageType.MGMT_HELLO
    REQUIRED = {"backend_instance_id": "string", "supported_protocol_versions": "int_list"}
    OPTIONAL = {
        "last_known_runtime_instance_id": ("nullable", "string"),
        "last_known_attempt_id": ("nullable", "string"),
        "last_seen_runtime_event_seq": ("nullable", "nonnegative_int"),
    }

    def _validate(self, data: dict[str, object]) -> None:
        if MCP_PROTOCOL_VERSION not in data["supported_protocol_versions"]:
            raise ProtocolError("MGMT_HELLO must support MCP/1")


class MgmtHelloAck(McpPayload):
    MESSAGE_TYPE = McpMessageType.MGMT_HELLO_ACK
    REQUIRED = {
        "runtime_instance_id": "string",
        "selected_protocol_version": "int",
        "runtime_boot_time": "string",
        "active_attempt_id": ("nullable", "string"),
        "active_job_id": ("nullable", "string"),
        "active_attempt_state": ("nullable", "string"),
        "last_runtime_event_seq": "nonnegative_int",
        "snapshot_required": "bool",
    }

    def _validate(self, data: dict[str, object]) -> None:
        if (
            data["selected_protocol_version"] != MCP_PROTOCOL_VERSION
            or data["snapshot_required"] is not True
        ):
            raise ProtocolError("MGMT_HELLO_ACK must select V1 and require a snapshot")


class GetState(McpPayload):
    MESSAGE_TYPE = McpMessageType.GET_STATE


class StateSnapshot(McpPayload):
    MESSAGE_TYPE = McpMessageType.STATE_SNAPSHOT
    REQUIRED = {
        "runtime_instance_id": "string",
        "active_job_id": ("nullable", "string"),
        "active_attempt_id": ("nullable", "string"),
        "attempt_state": ("nullable", "string"),
        "training_strategy": ("nullable", "string"),
        "checkpoint_policy": ("nullable", "string"),
        "epoch": ("nullable", "nonnegative_int"),
        "current_operation_id": ("nullable", "nonnegative_int"),
        "current_batch_ordinal": ("nullable", "nonnegative_int"),
        "model_version": ("nullable", "nonnegative_int"),
        "workers": "array",
        "strategy_state": "object",
        "checkpoint_state": ("nullable", "string"),
        "latest_checkpoint_id": ("nullable", "string"),
        "recovery_cursor": "object",
        "dataset_build_id": ("nullable", "string"),
        "dataset_manifest_hash": ("nullable", "string"),
        "last_runtime_event_seq": "nonnegative_int",
        "management_event_gap_count": "nonnegative_int",
        "captured_at": "string",
    }

    def _validate(self, data: dict[str, object]) -> None:
        required_worker = {
            "worker_id",
            "session_id",
            "node_label",
            "state",
            "last_heartbeat_at",
            "shard_id",
            "local_model_version",
        }
        for worker in data["workers"]:
            if not isinstance(worker, dict) or set(worker) != required_worker:
                raise ProtocolError("STATE_SNAPSHOT worker projection has invalid fields")
            _validate_json(worker, "payload.workers")


class StartAttempt(McpPayload):
    MESSAGE_TYPE = McpMessageType.START_ATTEMPT
    REQUIRED = {
        "command_id": "string",
        "job_id": "string",
        "attempt_id": "string",
        "execution_mode": "string",
        "resolved_contract": "object",
        "contract_hash": "string",
        "resume_from_checkpoint_id": ("nullable", "string"),
        "requested_at": "string",
    }
    ENUMS = {"execution_mode": frozenset({"FRESH", "RETRY_FROM_START", "RESUME"})}

    def _validate(self, data: dict[str, object]) -> None:
        if (data["execution_mode"] == "RESUME") != (data["resume_from_checkpoint_id"] is not None):
            raise ProtocolError("START_ATTEMPT resume identity does not match execution_mode")


class AbortAttempt(McpPayload):
    MESSAGE_TYPE = McpMessageType.ABORT_ATTEMPT
    REQUIRED = {
        "command_id": "string",
        "job_id": "string",
        "attempt_id": "string",
        "reason": "string",
        "requested_at": "string",
    }


class RequestCheckpoint(McpPayload):
    MESSAGE_TYPE = McpMessageType.REQUEST_CHECKPOINT
    REQUIRED = {
        "command_id": "string",
        "job_id": "string",
        "attempt_id": "string",
        "reason": "string",
    }
    OPTIONAL = {"requested_at": "string"}


class ResolveDatasetBuild(McpPayload):
    MESSAGE_TYPE = McpMessageType.RESOLVE_DATASET_BUILD
    REQUIRED = {
        "job_id": "string",
        "attempt_id": "string",
        "dataset_build_id": "string",
        "expected_dataset_manifest_hash": "string",
    }


class DatasetBuildResolved(McpPayload):
    MESSAGE_TYPE = McpMessageType.DATASET_BUILD_RESOLVED
    REQUIRED = {
        "dataset_build_id": "string",
        "state": "string",
        "manifest_uri": "string",
        "artifact_base_url": "string",
        "dataset_manifest_hash": "string",
        "profile": "string",
        "shard_count": "positive_int",
        "batch_size": "positive_int",
        "catalog_version": "positive_int",
    }
    ENUMS = {"state": frozenset({"READY"})}


class CommandResult(McpPayload):
    MESSAGE_TYPE = McpMessageType.COMMAND_RESULT
    REQUIRED = {
        "command_id": "string",
        "target_type": "string",
        "target_id": "string",
        "status": "string",
        "result_code": "string",
        "message": "string",
        "attempt_id": ("nullable", "string"),
        "effective_at": "string",
        "completed_at": ("nullable", "string"),
    }
    ENUMS = {"status": COMMAND_RESULT_STATUSES}

    def _validate(self, data: dict[str, object]) -> None:
        if data["result_code"] == "NO_OP" and data["status"] != "SUCCEEDED":
            raise ProtocolError("NO_OP is only valid as a SUCCEEDED result_code")


class RuntimeEvent(McpPayload):
    MESSAGE_TYPE = McpMessageType.RUNTIME_EVENT
    REQUIRED = {
        "attempt_id": "string",
        "job_id": "string",
        "runtime_event_seq": "positive_int",
        "event_type": "string",
        "event_schema_version": "positive_int",
        "occurred_at": "string",
        "source_component": "string",
        "severity": "string",
        "details": "object",
    }
    ENUMS = {"severity": EVENT_SEVERITIES}


class McpError(McpPayload):
    MESSAGE_TYPE = McpMessageType.ERROR
    REQUIRED = {"code": "string", "category": "string", "message": "string", "details": "object"}


PAYLOAD_TYPES: dict[str, type[McpPayload]] = {
    str(cls.MESSAGE_TYPE): cls
    for cls in (
        MgmtHello,
        MgmtHelloAck,
        GetState,
        StateSnapshot,
        StartAttempt,
        AbortAttempt,
        RequestCheckpoint,
        ResolveDatasetBuild,
        DatasetBuildResolved,
        CommandResult,
        RuntimeEvent,
        McpError,
    )
}

_REQUEST_TYPES = frozenset(
    {
        McpMessageType.MGMT_HELLO,
        McpMessageType.GET_STATE,
        McpMessageType.START_ATTEMPT,
        McpMessageType.ABORT_ATTEMPT,
        McpMessageType.REQUEST_CHECKPOINT,
        McpMessageType.RESOLVE_DATASET_BUILD,
    }
)
_RESPONSE_TYPES = frozenset(
    {
        McpMessageType.MGMT_HELLO_ACK,
        McpMessageType.STATE_SNAPSHOT,
        McpMessageType.DATASET_BUILD_RESOLVED,
        McpMessageType.COMMAND_RESULT,
    }
)


@dataclass(frozen=True, slots=True)
class McpEnvelope:
    message_type: str
    message_id: str
    correlation_id: str | None
    sent_at: str
    runtime_instance_id: str | None
    payload: dict[str, object] | McpPayload
    protocol_version: int = MCP_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != MCP_PROTOCOL_VERSION or type(self.protocol_version) is not int:
            raise ProtocolError("MCP protocol_version must be integer 1")
        try:
            kind = McpMessageType(self.message_type)
        except ValueError as exc:
            raise ProtocolError(f"Unknown MCP message_type {self.message_type!r}") from exc
        if not isinstance(self.message_id, str) or not self.message_id:
            raise ProtocolError("MCP message_id must be a non-empty string")
        if not isinstance(self.sent_at, str) or not self.sent_at:
            raise ProtocolError("MCP sent_at must be a non-empty string")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str) or not self.correlation_id
        ):
            raise ProtocolError("MCP correlation_id must be null or a non-empty string")
        if kind in _REQUEST_TYPES or kind == McpMessageType.RUNTIME_EVENT:
            if self.correlation_id is not None:
                raise ProtocolError("MCP request/unsolicited event correlation_id must be null")
        elif kind in _RESPONSE_TYPES and self.correlation_id is None:
            raise ProtocolError("MCP response correlation_id must reference its request")
        if kind == McpMessageType.MGMT_HELLO:
            if self.runtime_instance_id is not None and not isinstance(
                self.runtime_instance_id, str
            ):
                raise ProtocolError("MGMT_HELLO runtime_instance_id must be null or string")
        elif not isinstance(self.runtime_instance_id, str) or not self.runtime_instance_id:
            raise ProtocolError("Post-handshake MCP message requires runtime_instance_id")
        payload_cls = PAYLOAD_TYPES[str(kind)]
        payload = (
            self.payload
            if isinstance(self.payload, payload_cls)
            else payload_cls.from_dict(self.payload)
        )
        object.__setattr__(self, "message_type", str(kind))
        object.__setattr__(self, "payload", payload)

    def to_dict(self) -> dict[str, object]:
        payload = (
            self.payload.to_dict() if isinstance(self.payload, McpPayload) else dict(self.payload)
        )
        return {
            "protocol_version": self.protocol_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "sent_at": self.sent_at,
            "runtime_instance_id": self.runtime_instance_id,
            "payload": payload,
        }

    @classmethod
    def from_dict(cls, data: object) -> McpEnvelope:
        if not isinstance(data, dict):
            raise ProtocolError("MCP message root must be a JSON object")
        expected = {
            "protocol_version",
            "message_type",
            "message_id",
            "correlation_id",
            "sent_at",
            "runtime_instance_id",
            "payload",
        }
        if set(data) != expected:
            raise ProtocolError("MCP envelope fields do not match the V1 schema")
        return cls(**data)


class CorrelationTracker:
    """Bounded in-memory wire correlation; command idempotency stays elsewhere."""

    def __init__(self, max_pending: int = 1024) -> None:
        if type(max_pending) is not int or max_pending <= 0:
            raise ValueError("max_pending must be positive")
        self._max_pending = max_pending
        self._pending: dict[str, str] = {}

    def register_request(self, envelope: McpEnvelope) -> None:
        if McpMessageType(envelope.message_type) not in _REQUEST_TYPES:
            raise ProtocolError("Only MCP requests can be registered for correlation")
        if envelope.message_id in self._pending:
            raise ProtocolError("Duplicate MCP request message_id")
        if len(self._pending) >= self._max_pending:
            raise ProtocolError("MCP pending correlation limit reached")
        self._pending[envelope.message_id] = envelope.message_type

    def accept(self, envelope: McpEnvelope) -> str | None:
        if envelope.message_type == McpMessageType.RUNTIME_EVENT:
            return None
        if envelope.correlation_id is None:
            raise ProtocolError("Expected an MCP response")
        try:
            return self._pending.pop(envelope.correlation_id)
        except KeyError as exc:
            raise ProtocolError("MCP response has unknown correlation_id") from exc


def runtime_event_envelope(
    event: object,
    *,
    message_id: str,
    sent_at: str,
    runtime_instance_id: str,
) -> McpEnvelope:
    """Map a Linh-style RuntimeEvent without importing Runtime."""
    fields = (
        "attempt_id",
        "job_id",
        "runtime_event_seq",
        "event_type",
        "event_schema_version",
        "occurred_at",
        "source_component",
        "severity",
        "details",
    )
    try:
        payload = {name: getattr(event, name) for name in fields}
    except AttributeError as exc:
        raise ProtocolError("RuntimeEvent mapper input is missing a canonical field") from exc
    return McpEnvelope(
        message_type=McpMessageType.RUNTIME_EVENT,
        message_id=message_id,
        correlation_id=None,
        sent_at=sent_at,
        runtime_instance_id=runtime_instance_id,
        payload=payload,
    )
