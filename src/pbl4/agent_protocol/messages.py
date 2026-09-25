"""Wire schemas and JSON message envelopes for Backend <-> Node Agent WSS control.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md
This package is pure wire schema. It must NOT import node_agent, management_backend,
runtime, worker, database libraries, torch, or web frameworks.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from pbl4.common.errors import ProtocolError


class AgentMessageError(ProtocolError):
    """Exception raised when an agent protocol message or envelope fails validation."""


# ─── Protocol Constants ──────────────────────────────────────────────────────

AGENT_PROTOCOL_VERSION: int = 1

MESSAGE_TYPE_AGENT_HELLO: str = "AGENT_HELLO"
MESSAGE_TYPE_HELLO_ACK: str = "HELLO_ACK"
MESSAGE_TYPE_HEARTBEAT: str = "HEARTBEAT"
MESSAGE_TYPE_RESOURCE_SNAPSHOT: str = "RESOURCE_SNAPSHOT"
MESSAGE_TYPE_COMMAND: str = "COMMAND"
MESSAGE_TYPE_COMMAND_ACK: str = "COMMAND_ACK"
MESSAGE_TYPE_WORKER_STATUS: str = "WORKER_STATUS"

VALID_MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        MESSAGE_TYPE_AGENT_HELLO,
        MESSAGE_TYPE_HELLO_ACK,
        MESSAGE_TYPE_HEARTBEAT,
        MESSAGE_TYPE_RESOURCE_SNAPSHOT,
        MESSAGE_TYPE_COMMAND,
        MESSAGE_TYPE_COMMAND_ACK,
        MESSAGE_TYPE_WORKER_STATUS,
    }
)

ALLOWED_ENVELOPE_ROOT_KEYS: frozenset[str] = frozenset(
    {
        "protocol_version",
        "message_type",
        "message_id",
        "correlation_id",
        "node_id",
        "sent_at",
        "payload",
    }
)

FORBIDDEN_DATA_PLANE_FIELD_PATTERNS: tuple[str, ...] = (
    "tensor",
    "tensors",
    "gradient",
    "gradients",
    "raw_tensor",
    "parameter_chunks",
    "gradient_chunks",
    "weights",
)

COMMAND_TYPE_START_WORKER: str = "START_WORKER"
COMMAND_TYPE_STOP_WORKER: str = "STOP_WORKER"
VALID_COMMAND_TYPES: frozenset[str] = frozenset(
    {COMMAND_TYPE_START_WORKER, COMMAND_TYPE_STOP_WORKER}
)

COMMAND_STATUS_ACCEPTED: str = "ACCEPTED"
COMMAND_STATUS_REJECTED: str = "REJECTED"
VALID_COMMAND_STATUSES: frozenset[str] = frozenset(
    {COMMAND_STATUS_ACCEPTED, COMMAND_STATUS_REJECTED}
)

WORKER_ACTUAL_STATE_STARTED: str = "STARTED"
WORKER_ACTUAL_STATE_ENDED: str = "ENDED"
WORKER_ACTUAL_STATE_FAILED: str = "FAILED"
VALID_WORKER_ACTUAL_STATES: frozenset[str] = frozenset(
    {
        WORKER_ACTUAL_STATE_STARTED,
        WORKER_ACTUAL_STATE_ENDED,
        WORKER_ACTUAL_STATE_FAILED,
    }
)

# Active allocations reported in AGENT_HELLO must only be STARTING or RUNNING
ACTIVE_ALLOCATION_LOCAL_STATES: frozenset[str] = frozenset({"STARTING", "RUNNING"})

# Error / failure codes used in COMMAND_ACK and WORKER_STATUS
ERROR_CODE_ALLOCATION_NOT_FOUND: str = "ALLOCATION_NOT_FOUND"
ERROR_CODE_ALLOCATION_ALREADY_ACTIVE: str = "ALLOCATION_ALREADY_ACTIVE"
ERROR_CODE_WORKER_SPAWN_FAILED: str = "WORKER_SPAWN_FAILED"
ERROR_CODE_WORKER_STOP_FAILED: str = "WORKER_STOP_FAILED"
ERROR_CODE_INVALID_COMMAND_PAYLOAD: str = "INVALID_COMMAND_PAYLOAD"
ERROR_CODE_UNKNOWN_COMMAND_TYPE: str = "UNKNOWN_COMMAND_TYPE"


# ─── Payload Models ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ActiveAllocationItem:
    """An active allocation running locally on the Node reported during AGENT_HELLO."""

    allocation_id: str
    attempt_id: str
    local_state: str
    pid: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise AgentMessageError("allocation_id must be a non-empty string")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise AgentMessageError("attempt_id must be a non-empty string")
        if self.local_state not in ACTIVE_ALLOCATION_LOCAL_STATES:
            raise AgentMessageError(
                "active_allocations local_state must be STARTING or RUNNING, "
                f"got '{self.local_state}'. "
                "STOPPED/FAILED allocations must not be advertised as active."
            )
        if self.pid is not None and (
            not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0
        ):
            raise AgentMessageError("pid must be a positive integer or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "attempt_id": self.attempt_id,
            "local_state": self.local_state,
            "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveAllocationItem:
        if not isinstance(data, dict):
            raise AgentMessageError("ActiveAllocationItem must be a dictionary")
        return cls(
            allocation_id=data.get("allocation_id", ""),
            attempt_id=data.get("attempt_id", ""),
            local_state=data.get("local_state", ""),
            pid=data.get("pid"),
        )


@dataclass(frozen=True, slots=True)
class AgentHelloPayload:
    """Payload for AGENT_HELLO message."""

    agent_version: str
    platform: str
    active_allocations: tuple[ActiveAllocationItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.agent_version, str) or not self.agent_version:
            raise AgentMessageError("agent_version must be a non-empty string")
        if not isinstance(self.platform, str) or not self.platform:
            raise AgentMessageError("platform must be a non-empty string")
        if not isinstance(self.active_allocations, (tuple, list)):
            raise AgentMessageError("active_allocations must be a list of ActiveAllocationItem")
        for item in self.active_allocations:
            if not isinstance(item, ActiveAllocationItem):
                raise AgentMessageError("Each active_allocations item must be ActiveAllocationItem")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_version": self.agent_version,
            "platform": self.platform,
            "active_allocations": [item.to_dict() for item in self.active_allocations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentHelloPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("AgentHelloPayload must be a dictionary")
        allocations_raw = data.get("active_allocations", [])
        if not isinstance(allocations_raw, list):
            raise AgentMessageError("active_allocations must be a list")
        allocations = tuple(ActiveAllocationItem.from_dict(item) for item in allocations_raw)
        return cls(
            agent_version=data.get("agent_version", ""),
            platform=data.get("platform", ""),
            active_allocations=allocations,
        )


@dataclass(frozen=True, slots=True)
class HelloAckPayload:
    """Payload for HELLO_ACK message from Backend."""

    heartbeat_interval_seconds: float
    telemetry_interval_seconds: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.heartbeat_interval_seconds, (int, float))
            or self.heartbeat_interval_seconds <= 0
        ):
            raise AgentMessageError("heartbeat_interval_seconds must be a positive number")
        if (
            not isinstance(self.telemetry_interval_seconds, (int, float))
            or self.telemetry_interval_seconds <= 0
        ):
            raise AgentMessageError("telemetry_interval_seconds must be a positive number")

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeat_interval_seconds": float(self.heartbeat_interval_seconds),
            "telemetry_interval_seconds": float(self.telemetry_interval_seconds),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HelloAckPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("HelloAckPayload must be a dictionary")
        return cls(
            heartbeat_interval_seconds=data.get("heartbeat_interval_seconds", 0.0),
            telemetry_interval_seconds=data.get("telemetry_interval_seconds", 0.0),
        )


@dataclass(frozen=True, slots=True)
class HeartbeatPayload:
    """Payload for periodic HEARTBEAT message from Agent."""

    active_allocations_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.active_allocations_count, int)
            or isinstance(self.active_allocations_count, bool)
            or self.active_allocations_count < 0
        ):
            raise AgentMessageError("active_allocations_count must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {"active_allocations_count": self.active_allocations_count}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeartbeatPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("HeartbeatPayload must be a dictionary")
        count = data.get("active_allocations_count")
        if count is None:
            raise AgentMessageError("active_allocations_count is required")
        return cls(active_allocations_count=count)


@dataclass(frozen=True, slots=True)
class GpuSnapshotItem:
    """Resource snapshot for a single GPU device on the Node."""

    index: int
    gpu_utilization_pct: float | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.index, int) or isinstance(self.index, bool) or self.index < 0:
            raise AgentMessageError("gpu index must be a non-negative integer")
        if self.gpu_utilization_pct is not None and not isinstance(
            self.gpu_utilization_pct, (int, float)
        ):
            raise AgentMessageError("gpu_utilization_pct must be numeric or None")
        if self.vram_used_bytes is not None and (
            not isinstance(self.vram_used_bytes, int)
            or isinstance(self.vram_used_bytes, bool)
            or self.vram_used_bytes < 0
        ):
            raise AgentMessageError("vram_used_bytes must be a non-negative integer or None")
        if self.vram_total_bytes is not None and (
            not isinstance(self.vram_total_bytes, int)
            or isinstance(self.vram_total_bytes, bool)
            or self.vram_total_bytes < 0
        ):
            raise AgentMessageError("vram_total_bytes must be a non-negative integer or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "gpu_utilization_pct": self.gpu_utilization_pct,
            "vram_used_bytes": self.vram_used_bytes,
            "vram_total_bytes": self.vram_total_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GpuSnapshotItem:
        if not isinstance(data, dict):
            raise AgentMessageError("GpuSnapshotItem must be a dictionary")
        if "index" not in data:
            raise AgentMessageError("index is required in GpuSnapshotItem")
        return cls(
            index=data["index"],
            gpu_utilization_pct=data.get("gpu_utilization_pct"),
            vram_used_bytes=data.get("vram_used_bytes"),
            vram_total_bytes=data.get("vram_total_bytes"),
        )


@dataclass(frozen=True, slots=True)
class ResourceSnapshotPayload:
    """Periodic telemetry report on host CPU, RAM, and GPU status."""

    cpu_utilization_pct: float
    ram_used_bytes: int
    ram_total_bytes: int
    gpus: tuple[GpuSnapshotItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.cpu_utilization_pct, (int, float)):
            raise AgentMessageError("cpu_utilization_pct must be numeric")
        if (
            not isinstance(self.ram_used_bytes, int)
            or isinstance(self.ram_used_bytes, bool)
            or self.ram_used_bytes < 0
        ):
            raise AgentMessageError("ram_used_bytes must be a non-negative integer")
        if (
            not isinstance(self.ram_total_bytes, int)
            or isinstance(self.ram_total_bytes, bool)
            or self.ram_total_bytes < 0
        ):
            raise AgentMessageError("ram_total_bytes must be a non-negative integer")
        if not isinstance(self.gpus, (tuple, list)):
            raise AgentMessageError("gpus must be a list of GpuSnapshotItem")
        for g in self.gpus:
            if not isinstance(g, GpuSnapshotItem):
                raise AgentMessageError("Each item in gpus must be a GpuSnapshotItem")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_utilization_pct": float(self.cpu_utilization_pct),
            "ram_used_bytes": self.ram_used_bytes,
            "ram_total_bytes": self.ram_total_bytes,
            "gpus": [g.to_dict() for g in self.gpus],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceSnapshotPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("ResourceSnapshotPayload must be a dictionary")
        gpus_raw = data.get("gpus", [])
        if not isinstance(gpus_raw, list):
            raise AgentMessageError("gpus must be a list")
        return cls(
            cpu_utilization_pct=data.get("cpu_utilization_pct", 0.0),
            ram_used_bytes=data.get("ram_used_bytes", 0),
            ram_total_bytes=data.get("ram_total_bytes", 0),
            gpus=tuple(GpuSnapshotItem.from_dict(g) for g in gpus_raw),
        )


@dataclass(frozen=True, slots=True)
class StartWorkerPayload:
    """Payload for COMMAND START_WORKER dispatched by Backend."""

    command_id: str
    allocation_id: str
    attempt_id: str
    runtime_host: str
    runtime_port: int
    device: str
    initialization_seed: int
    worker_join_token: str
    command_type: str = COMMAND_TYPE_START_WORKER

    def __post_init__(self) -> None:
        if self.command_type != COMMAND_TYPE_START_WORKER:
            raise AgentMessageError(
                f"Expected command_type '{COMMAND_TYPE_START_WORKER}', got '{self.command_type}'"
            )
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AgentMessageError("command_id must be a non-empty string")
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise AgentMessageError("allocation_id must be a non-empty string")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise AgentMessageError("attempt_id must be a non-empty string")
        if not isinstance(self.runtime_host, str) or not self.runtime_host:
            raise AgentMessageError("runtime_host must be a non-empty string")
        if (
            not isinstance(self.runtime_port, int)
            or isinstance(self.runtime_port, bool)
            or self.runtime_port <= 0
            or self.runtime_port > 65535
        ):
            raise AgentMessageError("runtime_port must be an integer between 1 and 65535")
        if not isinstance(self.device, str) or not self.device:
            raise AgentMessageError("device must be a non-empty string (e.g. 'cpu', 'cuda:0')")
        if not isinstance(self.initialization_seed, int) or isinstance(
            self.initialization_seed, bool
        ):
            raise AgentMessageError("initialization_seed must be an integer")
        if not isinstance(self.worker_join_token, str) or not self.worker_join_token:
            raise AgentMessageError("worker_join_token must be a non-empty string")

    def __repr__(self) -> str:
        # Mandatory credential redaction
        return (
            f"StartWorkerPayload(command_id={self.command_id!r}, "
            f"command_type={self.command_type!r}, "
            f"allocation_id={self.allocation_id!r}, "
            f"attempt_id={self.attempt_id!r}, "
            f"runtime_host={self.runtime_host!r}, "
            f"runtime_port={self.runtime_port!r}, "
            f"device={self.device!r}, "
            f"initialization_seed={self.initialization_seed!r}, "
            f"worker_join_token='***REDACTED***')"
        )

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "allocation_id": self.allocation_id,
            "attempt_id": self.attempt_id,
            "runtime_host": self.runtime_host,
            "runtime_port": self.runtime_port,
            "device": self.device,
            "initialization_seed": self.initialization_seed,
            "worker_join_token": "***REDACTED***" if redact else self.worker_join_token,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StartWorkerPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("StartWorkerPayload must be a dictionary")
        return cls(
            command_id=data.get("command_id", ""),
            allocation_id=data.get("allocation_id", ""),
            attempt_id=data.get("attempt_id", ""),
            runtime_host=data.get("runtime_host", ""),
            runtime_port=data.get("runtime_port", 0),
            device=data.get("device", ""),
            initialization_seed=data.get("initialization_seed", 0),
            worker_join_token=data.get("worker_join_token", ""),
            command_type=data.get("command_type", COMMAND_TYPE_START_WORKER),
        )


@dataclass(frozen=True, slots=True)
class StopWorkerPayload:
    """Payload for COMMAND STOP_WORKER dispatched by Backend."""

    command_id: str
    allocation_id: str
    grace_period_seconds: float = 10.0
    force: bool = False
    command_type: str = COMMAND_TYPE_STOP_WORKER

    def __post_init__(self) -> None:
        if self.command_type != COMMAND_TYPE_STOP_WORKER:
            raise AgentMessageError(
                f"Expected command_type '{COMMAND_TYPE_STOP_WORKER}', got '{self.command_type}'"
            )
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AgentMessageError("command_id must be a non-empty string")
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise AgentMessageError("allocation_id must be a non-empty string")
        if not isinstance(self.grace_period_seconds, (int, float)) or self.grace_period_seconds < 0:
            raise AgentMessageError("grace_period_seconds must be a non-negative number")
        if not isinstance(self.force, bool):
            raise AgentMessageError("force must be a boolean")

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "command_type": self.command_type,
            "allocation_id": self.allocation_id,
            "grace_period_seconds": float(self.grace_period_seconds),
            "force": self.force,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopWorkerPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("StopWorkerPayload must be a dictionary")
        return cls(
            command_id=data.get("command_id", ""),
            allocation_id=data.get("allocation_id", ""),
            grace_period_seconds=data.get("grace_period_seconds", 10.0),
            force=data.get("force", False),
            command_type=data.get("command_type", COMMAND_TYPE_STOP_WORKER),
        )


@dataclass(frozen=True, slots=True)
class CommandAckPayload:
    """Payload for COMMAND_ACK message acknowledging a received command."""

    command_id: str
    allocation_id: str
    status: str
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or not self.command_id:
            raise AgentMessageError("command_id must be a non-empty string")
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise AgentMessageError("allocation_id must be a non-empty string")
        if self.status not in VALID_COMMAND_STATUSES:
            raise AgentMessageError(f"status must be ACCEPTED or REJECTED, got '{self.status}'")
        if self.error_code is not None and not isinstance(self.error_code, str):
            raise AgentMessageError("error_code must be string or None")
        if self.error_message is not None and not isinstance(self.error_message, str):
            raise AgentMessageError("error_message must be string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "allocation_id": self.allocation_id,
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandAckPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("CommandAckPayload must be a dictionary")
        return cls(
            command_id=data.get("command_id", ""),
            allocation_id=data.get("allocation_id", ""),
            status=data.get("status", ""),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )


@dataclass(frozen=True, slots=True)
class WorkerStatusPayload:
    """Payload for WORKER_STATUS message notifying Backend of worker process lifecycle changes."""

    allocation_id: str
    attempt_id: str
    actual_state: str
    exit_code: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise AgentMessageError("allocation_id must be a non-empty string")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise AgentMessageError("attempt_id must be a non-empty string")
        if self.actual_state not in VALID_WORKER_ACTUAL_STATES:
            raise AgentMessageError(
                f"actual_state must be STARTED, ENDED, or FAILED, got '{self.actual_state}'"
            )
        if self.exit_code is not None and (
            not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool)
        ):
            raise AgentMessageError("exit_code must be an integer or None")
        if self.failure_code is not None and not isinstance(self.failure_code, str):
            raise AgentMessageError("failure_code must be string or None")
        if self.failure_message is not None and not isinstance(self.failure_message, str):
            raise AgentMessageError("failure_message must be string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "attempt_id": self.attempt_id,
            "actual_state": self.actual_state,
            "exit_code": self.exit_code,
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerStatusPayload:
        if not isinstance(data, dict):
            raise AgentMessageError("WorkerStatusPayload must be a dictionary")
        return cls(
            allocation_id=data.get("allocation_id", ""),
            attempt_id=data.get("attempt_id", ""),
            actual_state=data.get("actual_state", ""),
            exit_code=data.get("exit_code"),
            failure_code=data.get("failure_code"),
            failure_message=data.get("failure_message"),
        )


AgentPayload = (
    AgentHelloPayload
    | HelloAckPayload
    | HeartbeatPayload
    | ResourceSnapshotPayload
    | StartWorkerPayload
    | StopWorkerPayload
    | CommandAckPayload
    | WorkerStatusPayload
)


# ─── Envelope ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentEnvelope:
    """Canonical outer envelope framing all control messages between Agent and Backend."""

    message_type: str
    node_id: str
    payload: AgentPayload
    protocol_version: int = AGENT_PROTOCOL_VERSION
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    sent_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.protocol_version != AGENT_PROTOCOL_VERSION:
            raise AgentMessageError(f"Unsupported protocol_version: {self.protocol_version}")
        if self.message_type not in VALID_MESSAGE_TYPES:
            raise AgentMessageError(f"Unknown message_type: '{self.message_type}'")
        if not isinstance(self.node_id, str) or not self.node_id:
            raise AgentMessageError("node_id must be a non-empty string")
        if not isinstance(self.message_id, str) or not self.message_id:
            raise AgentMessageError("message_id must be a non-empty string")
        if self.correlation_id is not None and (
            not isinstance(self.correlation_id, str) or not self.correlation_id
        ):
            raise AgentMessageError("correlation_id must be a non-empty string or None")
        if not isinstance(self.sent_at, str) or not self.sent_at:
            raise AgentMessageError("sent_at must be a non-empty ISO 8601 string")

    def __repr__(self) -> str:
        return (
            f"AgentEnvelope(message_type={self.message_type!r}, "
            f"node_id={self.node_id!r}, "
            f"message_id={self.message_id!r}, "
            f"correlation_id={self.correlation_id!r}, "
            f"sent_at={self.sent_at!r}, "
            f"payload={self.payload!r})"
        )

    def to_dict(self, *, redact: bool = False) -> dict[str, Any]:
        """Convert envelope to dictionary. Redacts secrets if redact=True."""
        if isinstance(self.payload, (StartWorkerPayload, StopWorkerPayload)):
            payload_dict = self.payload.to_dict(redact=redact)
        elif hasattr(self.payload, "to_dict"):
            payload_dict = self.payload.to_dict()
        elif isinstance(self.payload, dict):
            payload_dict = self.payload
        else:
            payload_dict = asdict(self.payload)

        return {
            "protocol_version": self.protocol_version,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "node_id": self.node_id,
            "sent_at": self.sent_at,
            "payload": payload_dict,
        }

    def to_json(self, *, redact: bool = False) -> str:
        """Serialize envelope to JSON string. Redacts secrets if redact=True."""
        return json.dumps(
            self.to_dict(redact=redact),
            sort_keys=True,
            separators=(",", ":"),
        )


def _check_forbidden_data_plane_fields(obj: Any) -> None:
    """Reject gradient, parameter, and tensor fields on the control wire."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(pattern in k_lower for pattern in FORBIDDEN_DATA_PLANE_FIELD_PATTERNS):
                raise AgentMessageError(
                    f"Forbidden data plane field '{k}' on Agent control wire. "
                    "Gradients and tensors must travel strictly over DTP/1."
                )
            _check_forbidden_data_plane_fields(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _check_forbidden_data_plane_fields(item)


def parse_agent_envelope(data: str | bytes | dict[str, Any]) -> AgentEnvelope:
    """Parse and validate an incoming agent protocol message envelope from JSON or dict.

    Enforces:
    - Root field rejection on unknown keys.
    - Message type validation.
    - Type-specific payload validation.
    - Strict prohibition of raw tensor/gradient data on the control wire.
    """
    if isinstance(data, (str, bytes)):
        try:
            raw_dict = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentMessageError(f"Malformed JSON in agent message: {exc}") from exc
    elif isinstance(data, dict):
        raw_dict = data
    else:
        raise AgentMessageError(
            f"Expected str, bytes, or dict for agent envelope, got {type(data).__name__}"
        )

    if not isinstance(raw_dict, dict):
        raise AgentMessageError("Agent envelope must be a JSON object")

    # Reject unknown root keys
    unknown_keys = set(raw_dict.keys()) - ALLOWED_ENVELOPE_ROOT_KEYS
    if unknown_keys:
        raise AgentMessageError(
            f"Unknown root field(s) in agent envelope: {', '.join(sorted(unknown_keys))}"
        )

    # Check for forbidden tensor / gradient fields anywhere in the message
    _check_forbidden_data_plane_fields(raw_dict)

    protocol_version = raw_dict.get("protocol_version", AGENT_PROTOCOL_VERSION)
    if protocol_version != AGENT_PROTOCOL_VERSION:
        raise AgentMessageError(f"Unsupported protocol_version: {protocol_version}")

    message_type = raw_dict.get("message_type")
    if not isinstance(message_type, str) or message_type not in VALID_MESSAGE_TYPES:
        raise AgentMessageError(f"Unknown or invalid message_type: '{message_type}'")

    message_id = raw_dict.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise AgentMessageError("message_id is required in envelope")

    node_id = raw_dict.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise AgentMessageError("node_id is required in envelope")

    correlation_id = raw_dict.get("correlation_id")
    sent_at = raw_dict.get("sent_at")
    if not isinstance(sent_at, str) or not sent_at:
        raise AgentMessageError("sent_at is required in envelope")

    payload_raw = raw_dict.get("payload")
    if not isinstance(payload_raw, dict):
        raise AgentMessageError("payload must be a JSON object")

    payload: AgentPayload
    if message_type == MESSAGE_TYPE_AGENT_HELLO:
        payload = AgentHelloPayload.from_dict(payload_raw)
    elif message_type == MESSAGE_TYPE_HELLO_ACK:
        payload = HelloAckPayload.from_dict(payload_raw)
    elif message_type == MESSAGE_TYPE_HEARTBEAT:
        payload = HeartbeatPayload.from_dict(payload_raw)
    elif message_type == MESSAGE_TYPE_RESOURCE_SNAPSHOT:
        payload = ResourceSnapshotPayload.from_dict(payload_raw)
    elif message_type == MESSAGE_TYPE_COMMAND:
        cmd_type = payload_raw.get("command_type")
        if cmd_type == COMMAND_TYPE_START_WORKER:
            payload = StartWorkerPayload.from_dict(payload_raw)
        elif cmd_type == COMMAND_TYPE_STOP_WORKER:
            payload = StopWorkerPayload.from_dict(payload_raw)
        else:
            raise AgentMessageError(f"Unknown command_type in COMMAND payload: '{cmd_type}'")
    elif message_type == MESSAGE_TYPE_COMMAND_ACK:
        payload = CommandAckPayload.from_dict(payload_raw)
    elif message_type == MESSAGE_TYPE_WORKER_STATUS:
        payload = WorkerStatusPayload.from_dict(payload_raw)
    else:
        raise AgentMessageError(f"Unhandled message_type: {message_type}")

    return AgentEnvelope(
        protocol_version=protocol_version,
        message_type=message_type,
        message_id=message_id,
        correlation_id=correlation_id,
        node_id=node_id,
        sent_at=sent_at,
        payload=payload,
    )
