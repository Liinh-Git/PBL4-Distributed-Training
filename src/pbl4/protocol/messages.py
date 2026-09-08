"""Canonical DTP/1 control/meta DTO schemas and frame helpers."""

# ruff: noqa: RUF012

from __future__ import annotations

import json
import math
import zlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from pbl4.common.errors import ProtocolError
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DTP_PROTOCOL_VERSION,
    KNOWN_MESSAGE_TYPES,
    MAGIC,
    MESSAGE_TYPE_DATASET_ASSIGNMENT,
    MESSAGE_TYPE_EPOCH_END,
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_GRADIENT_END,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_MODEL_INIT,
    MESSAGE_TYPE_MODEL_MANIFEST,
    MESSAGE_TYPE_PARAMETER_APPLIED,
    MESSAGE_TYPE_PARAMETER_META,
    MESSAGE_TYPE_READY,
    MESSAGE_TYPE_SHARD_ERROR,
    MESSAGE_TYPE_SHARD_READY,
    MESSAGE_TYPE_STEP_START,
    MESSAGE_TYPE_STOP,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    TENSOR_ENCODING_FP32_LE_V1,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
    MessageType,
)
from pbl4.protocol.header import DTPHeader
from pbl4.protocol.parameter_manifest import ParameterManifest

JsonType = object
_MISSING = object()


def _is_type(value: object, expected: object) -> bool:
    if expected == "int":
        return type(value) is int
    if expected == "positive_int":
        return type(value) is int and value > 0
    if expected == "nonnegative_int":
        return type(value) is int and value >= 0
    if expected == "number":
        return (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        )
    if expected == "string":
        return isinstance(value, str) and bool(value) and len(value) <= 4096
    if expected == "bool":
        return type(value) is bool
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string_list":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and bool(item) for item in value)
        )
    if expected == "int_list":
        return isinstance(value, list) and bool(value) and all(type(item) is int for item in value)
    if expected == "uint64_string":
        return (
            isinstance(value, str)
            and value.isascii()
            and value.isdigit()
            and 0 < int(value) < 2**64
        )
    if isinstance(expected, tuple) and expected and expected[0] == "nullable":
        return value is None or _is_type(value, expected[1])
    return False


def _validate_json(value: object, path: str = "payload") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
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
                raise ProtocolError(f"{path} object keys must be strings")
            _validate_json(item, f"{path}.{key}")
        return
    raise ProtocolError(f"{path} contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class DtpControlMessage:
    """Immutable schema-validated control/meta payload."""

    values: dict[str, object]
    MESSAGE_TYPE: ClassVar[int]
    REQUIRED: ClassVar[dict[str, object]] = {}
    OPTIONAL: ClassVar[dict[str, object]] = {}
    ENUMS: ClassVar[dict[str, frozenset[object]]] = {}

    def __post_init__(self) -> None:
        if not isinstance(self.values, dict):
            raise ProtocolError("DTP control payload must be one JSON object")
        data = dict(self.values)
        _validate_json(data)
        allowed = set(self.REQUIRED) | set(self.OPTIONAL)
        if set(data) - allowed:
            raise ProtocolError(
                f"{type(self).__name__} has unknown fields: {sorted(set(data) - allowed)}"
            )
        missing = set(self.REQUIRED) - set(data)
        if missing:
            raise ProtocolError(f"{type(self).__name__} missing fields: {sorted(missing)}")
        for name, expected in {**self.REQUIRED, **self.OPTIONAL}.items():
            value = data.get(name, _MISSING)
            if value is not _MISSING and not _is_type(value, expected):
                raise ProtocolError(f"{type(self).__name__}.{name} has the wrong type or range")
        for name, choices in self.ENUMS.items():
            if name in data and data[name] not in choices:
                raise ProtocolError(f"{type(self).__name__}.{name} is not a canonical enum value")
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

    def to_bytes(self) -> bytes:
        try:
            return json.dumps(
                self.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"Invalid DTP JSON payload: {exc}") from exc

    @classmethod
    def from_dict(cls, value: object) -> DtpControlMessage:
        if not isinstance(value, dict):
            raise ProtocolError("DTP control payload must be one JSON object")
        return cls(value)


class Hello(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_HELLO
    REQUIRED = {
        "node_label": "string",
        "client_instance_id": "string",
        "role": "string",
        "protocol_version": "int",
        "framework_adapter": "string",
        "supported_tensor_encoding": "string_list",
        "supported_strategy_capabilities": "string_list",
    }
    ENUMS = {"role": frozenset({"worker"})}

    def _validate(self, data: dict[str, object]) -> None:
        if data["protocol_version"] != DTP_PROTOCOL_VERSION:
            raise ProtocolError("HELLO protocol_version must be 1")
        if TENSOR_ENCODING_FP32_LE_V1 not in data["supported_tensor_encoding"]:
            raise ProtocolError("HELLO must advertise fp32_le_v1")


class HelloAck(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_HELLO_ACK
    REQUIRED = {
        "attempt_id": "string",
        "job_id": "string",
        "session_id": "uint64_string",
        "worker_id": "nonnegative_int",
        "expected_workers": "positive_int",
        "training_strategy": "string",
        "heartbeat_interval_ms": "positive_int",
        "heartbeat_timeout_ms": "positive_int",
        "tensor_encoding": "string",
        "max_tensor_chunk_bytes": "positive_int",
        "server_protocol_version": "int",
    }

    def _validate(self, data: dict[str, object]) -> None:
        if data["worker_id"] == UNASSIGNED_WORKER_ID:
            raise ProtocolError("HELLO_ACK contains an invalid assigned identity")
        if data["heartbeat_timeout_ms"] <= data["heartbeat_interval_ms"]:
            raise ProtocolError("Heartbeat timeout must exceed interval")
        if data["tensor_encoding"] != TENSOR_ENCODING_FP32_LE_V1:
            raise ProtocolError("Unsupported HELLO_ACK tensor encoding")
        if data["server_protocol_version"] != DTP_PROTOCOL_VERSION:
            raise ProtocolError("Unsupported server protocol version")


class DatasetAssignment(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_DATASET_ASSIGNMENT
    REQUIRED = {
        "dataset_build_id": "string",
        "dataset_manifest_hash": "string",
        "shard_id": "nonnegative_int",
        "artifact_base_url": "string",
        "root_manifest_path": "string",
        "expected_shard_count": "positive_int",
        "profile": "string",
    }


class ShardReady(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_SHARD_READY
    REQUIRED = {
        "dataset_build_id": "string",
        "dataset_manifest_hash": "string",
        "shard_id": "nonnegative_int",
        "shard_manifest_hash": "string",
        "verified_batch_count": "positive_int",
        "verified_sample_count": "positive_int",
        "cache_key": "string",
        "completed_at": "string",
    }


class ShardError(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_SHARD_ERROR
    REQUIRED = {
        "error_code": "string",
        "stage": "string",
        "retryable": "bool",
        "message": "string",
    }
    ENUMS = {"stage": frozenset({"DOWNLOADING", "VERIFYING"})}


class ModelManifest(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_MODEL_MANIFEST
    REQUIRED = {
        "parameter_manifest_hash": "string",
        "schema_version": "positive_int",
        "total_numel": "positive_int",
        "total_bytes": "positive_int",
        "parameters": "array",
    }

    def __post_init__(self) -> None:
        if not isinstance(self.values, dict):
            raise ProtocolError("MODEL_MANIFEST payload must be an object")
        ParameterManifest.from_dict(self.values)
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


class ModelInit(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_MODEL_INIT
    REQUIRED = {
        "initialization_seed": "int",
        "target_model_version": "nonnegative_int",
        "parameter_manifest_hash": "string",
        "total_bytes": "positive_int",
        "initialization_policy_version": "positive_int",
    }

    def _validate(self, data: dict[str, object]) -> None:
        if data["target_model_version"] != 0:
            raise ProtocolError("Fresh MODEL_INIT target_model_version must be zero")


class ParameterMeta(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_PARAMETER_META
    REQUIRED = {
        "transfer_purpose": "string",
        "parameter_manifest_hash": "string",
        "total_numel": "positive_int",
        "total_bytes": "positive_int",
        "chunk_count": "positive_int",
        "tensor_encoding": "string",
    }
    OPTIONAL = {
        "attempt_id": "string",
        "model_version": "nonnegative_int",
        "source_step_id": "nonnegative_int",
        "model_version_out": "nonnegative_int",
    }
    ENUMS = {"transfer_purpose": frozenset({"model_init", "model_update"})}

    def _validate(self, data: dict[str, object]) -> None:
        if data["tensor_encoding"] != TENSOR_ENCODING_FP32_LE_V1:
            raise ProtocolError("PARAMETER_META tensor_encoding must be fp32_le_v1")
        purpose = data["transfer_purpose"]
        required = (
            {"model_version"}
            if purpose == "model_init"
            else {
                "attempt_id",
                "source_step_id",
                "model_version_out",
            }
        )
        forbidden = (
            {"attempt_id", "source_step_id", "model_version_out"}
            if purpose == "model_init"
            else {"model_version"}
        )
        if not required <= set(data) or forbidden & set(data):
            raise ProtocolError("PARAMETER_META fields do not match transfer_purpose")


class Ready(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_READY
    REQUIRED = {
        "model_version": "nonnegative_int",
        "parameter_manifest_hash": "string",
        "dataset_build_id": "string",
        "shard_id": "nonnegative_int",
    }


class StepStart(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_STEP_START
    REQUIRED = {
        "attempt_id": "string",
        "epoch": "nonnegative_int",
        "step_id": "nonnegative_int",
        "batch_ordinal": "nonnegative_int",
        "model_version": "nonnegative_int",
        "shard_id": "nonnegative_int",
        "batch_id": "nonnegative_int",
        "expected_sample_count": "positive_int",
        "training_strategy": "string",
        "parameter_manifest_hash": "string",
    }
    ENUMS = {"training_strategy": frozenset({"strict_bsp"})}


class GradientMeta(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_GRADIENT_META
    REQUIRED = {
        "attempt_id": "string",
        "model_version": "nonnegative_int",
        "shard_id": "nonnegative_int",
        "batch_id": "nonnegative_int",
        "batch_ordinal": "nonnegative_int",
        "sample_count": "positive_int",
        "parameter_manifest_hash": "string",
        "tensor_encoding": "string",
        "total_numel": "positive_int",
        "total_bytes": "positive_int",
        "chunk_count": "positive_int",
    }
    OPTIONAL = {"loss": "number", "compute_ms": "number"}

    def _validate(self, data: dict[str, object]) -> None:
        if data["tensor_encoding"] != TENSOR_ENCODING_FP32_LE_V1:
            raise ProtocolError("GRADIENT_META tensor_encoding must be fp32_le_v1")


class GradientEnd(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_GRADIENT_END
    REQUIRED = {
        "total_bytes": "positive_int",
        "chunk_count": "positive_int",
        "transfer_complete": "bool",
    }
    OPTIONAL = {"gradient_sha256": "string"}

    def _validate(self, data: dict[str, object]) -> None:
        if data["transfer_complete"] is not True:
            raise ProtocolError("GRADIENT_END transfer_complete must be true")


class ParameterApplied(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_PARAMETER_APPLIED
    REQUIRED = {
        "attempt_id": "string",
        "model_version": "nonnegative_int",
        "parameter_manifest_hash": "string",
        "apply_ok": "bool",
        "source_step_id": "nonnegative_int",
    }
    OPTIONAL = {"apply_ms": "number"}

    def _validate(self, data: dict[str, object]) -> None:
        if data["apply_ok"] is not True:
            raise ProtocolError("PARAMETER_APPLIED is only an ACK when apply_ok is true")


class Heartbeat(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_HEARTBEAT
    REQUIRED = {
        "attempt_id": "string",
        "local_model_version": "nonnegative_int",
        "last_completed_operation_id": ("nullable", "nonnegative_int"),
        "recovery_cursor": "object",
        "monotonic_timestamp_ms": "number",
    }
    OPTIONAL = {
        "worker_state": "string",
        "server_state": "string",
        "last_completed_step_id": ("nullable", "nonnegative_int"),
    }

    def _validate(self, data: dict[str, object]) -> None:
        if ("worker_state" in data) == ("server_state" in data):
            raise ProtocolError("HEARTBEAT requires exactly one of worker_state/server_state")


class EpochEnd(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_EPOCH_END
    REQUIRED = {
        "attempt_id": "string",
        "completed_epoch": "nonnegative_int",
        "next_epoch": ("nullable", "nonnegative_int"),
        "training_complete": "bool",
        "latest_checkpoint_id": ("nullable", "string"),
    }


class Stop(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_STOP
    REQUIRED = {
        "reason_code": "string",
        "reason": "string",
        "attempt_state": "string",
        "whether_reconnect_allowed": "bool",
    }


class Error(DtpControlMessage):
    MESSAGE_TYPE = MESSAGE_TYPE_ERROR
    REQUIRED = {
        "error_code": "string",
        "scope": "string",
        "severity": "string",
        "message": "string",
        "retryable": "bool",
    }
    OPTIONAL = {
        "related_message_type": "string",
        "operation_id": "nonnegative_int",
        "model_version": "nonnegative_int",
        "tensor_id": "nonnegative_int",
        "step_id": "nonnegative_int",
    }
    ENUMS = {
        "scope": frozenset({"MESSAGE", "SESSION", "ATTEMPT"}),
        "severity": frozenset({"INFO", "WARNING", "ERROR", "CRITICAL"}),
    }


CONTROL_MESSAGE_CLASSES: dict[int, type[DtpControlMessage]] = {
    cls.MESSAGE_TYPE: cls
    for cls in (
        Hello,
        HelloAck,
        DatasetAssignment,
        ShardReady,
        ShardError,
        ModelManifest,
        ModelInit,
        ParameterMeta,
        Ready,
        StepStart,
        GradientMeta,
        GradientEnd,
        ParameterApplied,
        Heartbeat,
        EpochEnd,
        Stop,
        Error,
    )
}


def decode_control_message(message_type: int, payload: bytes) -> DtpControlMessage:
    cls = CONTROL_MESSAGE_CLASSES.get(message_type)
    if cls is None:
        raise ProtocolError("DTP message type does not carry a control JSON payload")
    try:
        data = json.loads(
            payload.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolError(f"DTP payload is not valid finite UTF-8 JSON: {exc}") from exc
    return cls.from_dict(data)


def message_type_name(message_type: int) -> str:
    try:
        return MessageType(message_type).name
    except ValueError:
        return f"UNKNOWN(0x{message_type:04X})"


def build_frame(
    message_type: int,
    payload: bytes = b"",
    *,
    session_id: int = UNBOUND_SESSION,
    worker_id: int = UNASSIGNED_WORKER_ID,
    operation_id: int = NO_OPERATION,
    tensor_id: int = NO_TENSOR,
    chunk_index: int = NO_CHUNK,
    flags: int = 0,
) -> DTPFrame:
    if message_type not in KNOWN_MESSAGE_TYPES:
        raise ProtocolError(f"Unknown DTP message_type 0x{message_type:04X}")
    header = DTPHeader(
        magic=MAGIC,
        protocol_version=DTP_PROTOCOL_VERSION,
        message_type=message_type,
        flags=flags,
        session_id=session_id,
        worker_id=worker_id,
        operation_id=operation_id,
        tensor_id=tensor_id,
        chunk_index=chunk_index,
        payload_length=len(payload),
        payload_crc32=zlib.crc32(payload) & 0xFFFFFFFF,
    )
    header.validate_protocol()
    return DTPFrame(header, payload)


def build_control_frame(message: DtpControlMessage, **identity: int) -> DTPFrame:
    return build_frame(message.MESSAGE_TYPE, message.to_bytes(), **identity)


# Explicit DTO aliases for integration code that prefers the Message suffix.
HelloMessage = Hello
HelloAckMessage = HelloAck
DatasetAssignmentMessage = DatasetAssignment
ShardReadyMessage = ShardReady
ShardErrorMessage = ShardError
ModelManifestMessage = ModelManifest
ModelInitMessage = ModelInit
ParameterMetaMessage = ParameterMeta
ReadyMessage = Ready
StepStartMessage = StepStart
GradientMetaMessage = GradientMeta
GradientEndMessage = GradientEnd
ParameterAppliedMessage = ParameterApplied
HeartbeatMessage = Heartbeat
EpochEndMessage = EpochEnd
StopMessage = Stop
ErrorMessage = Error
