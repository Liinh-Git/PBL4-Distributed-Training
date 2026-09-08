"""DTP connection binding and protocol-order validation.

Runtime owns Attempt and membership transitions.  This object only validates
which wire messages are syntactically legal in an owner-supplied connection
phase and protects the bound connection identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pbl4.common.errors import ProtocolError
from pbl4.protocol.constants import (
    MESSAGE_TYPE_DATASET_ASSIGNMENT,
    MESSAGE_TYPE_EPOCH_END,
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_GRADIENT_CHUNK,
    MESSAGE_TYPE_GRADIENT_END,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_MODEL_INIT,
    MESSAGE_TYPE_MODEL_MANIFEST,
    MESSAGE_TYPE_PARAMETER_APPLIED,
    MESSAGE_TYPE_PARAMETER_CHUNK,
    MESSAGE_TYPE_PARAMETER_META,
    MESSAGE_TYPE_READY,
    MESSAGE_TYPE_SHARD_ERROR,
    MESSAGE_TYPE_SHARD_READY,
    MESSAGE_TYPE_STEP_START,
    MESSAGE_TYPE_STOP,
)
from pbl4.protocol.header import DTPHeader


class ConnectionPhase(StrEnum):
    CONNECTED = "CONNECTED"
    REGISTERED = "REGISTERED"
    SHARD_READY = "SHARD_READY"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING_IDLE = "RUNNING_IDLE"
    UPLOADING = "UPLOADING"
    WAITING_PARAMETER = "WAITING_PARAMETER"
    APPLYING = "APPLYING"
    WAITING_NEXT = "WAITING_NEXT"
    CLOSED = "CLOSED"


class PeerRole(StrEnum):
    WORKER = "WORKER"
    RUNTIME = "RUNTIME"


_INBOUND_BY_PEER: dict[PeerRole, frozenset[int]] = {
    PeerRole.WORKER: frozenset(
        {
            MESSAGE_TYPE_HELLO,
            MESSAGE_TYPE_SHARD_READY,
            MESSAGE_TYPE_SHARD_ERROR,
            MESSAGE_TYPE_MODEL_MANIFEST,
            MESSAGE_TYPE_MODEL_INIT,
            MESSAGE_TYPE_PARAMETER_META,
            MESSAGE_TYPE_PARAMETER_CHUNK,
            MESSAGE_TYPE_READY,
            MESSAGE_TYPE_GRADIENT_META,
            MESSAGE_TYPE_GRADIENT_CHUNK,
            MESSAGE_TYPE_GRADIENT_END,
            MESSAGE_TYPE_PARAMETER_APPLIED,
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_EPOCH_END,
            MESSAGE_TYPE_ERROR,
        }
    ),
    PeerRole.RUNTIME: frozenset(
        {
            MESSAGE_TYPE_HELLO_ACK,
            MESSAGE_TYPE_DATASET_ASSIGNMENT,
            MESSAGE_TYPE_PARAMETER_META,
            MESSAGE_TYPE_PARAMETER_CHUNK,
            MESSAGE_TYPE_STEP_START,
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
}


_ALLOWED: dict[ConnectionPhase, frozenset[int]] = {
    ConnectionPhase.CONNECTED: frozenset({MESSAGE_TYPE_HELLO, MESSAGE_TYPE_HELLO_ACK}),
    ConnectionPhase.REGISTERED: frozenset(
        {
            MESSAGE_TYPE_DATASET_ASSIGNMENT,
            MESSAGE_TYPE_SHARD_READY,
            MESSAGE_TYPE_SHARD_ERROR,
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.SHARD_READY: frozenset(
        {MESSAGE_TYPE_MODEL_MANIFEST, MESSAGE_TYPE_HEARTBEAT, MESSAGE_TYPE_STOP, MESSAGE_TYPE_ERROR}
    ),
    ConnectionPhase.INITIALIZING: frozenset(
        {
            MESSAGE_TYPE_MODEL_INIT,
            MESSAGE_TYPE_PARAMETER_META,
            MESSAGE_TYPE_PARAMETER_CHUNK,
            MESSAGE_TYPE_READY,
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.READY: frozenset(
        {
            MESSAGE_TYPE_READY,
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_STEP_START,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.RUNNING_IDLE: frozenset(
        {MESSAGE_TYPE_STEP_START, MESSAGE_TYPE_HEARTBEAT, MESSAGE_TYPE_STOP, MESSAGE_TYPE_ERROR}
    ),
    ConnectionPhase.UPLOADING: frozenset(
        {
            MESSAGE_TYPE_GRADIENT_META,
            MESSAGE_TYPE_GRADIENT_CHUNK,
            MESSAGE_TYPE_GRADIENT_END,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.WAITING_PARAMETER: frozenset(
        {
            MESSAGE_TYPE_PARAMETER_META,
            MESSAGE_TYPE_PARAMETER_CHUNK,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.APPLYING: frozenset(
        {MESSAGE_TYPE_PARAMETER_APPLIED, MESSAGE_TYPE_STOP, MESSAGE_TYPE_ERROR}
    ),
    ConnectionPhase.WAITING_NEXT: frozenset(
        {
            MESSAGE_TYPE_HEARTBEAT,
            MESSAGE_TYPE_EPOCH_END,
            MESSAGE_TYPE_STEP_START,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
    ConnectionPhase.CLOSED: frozenset(),
}


@dataclass(slots=True)
class ConnectionProtocolValidator:
    phase: ConnectionPhase = ConnectionPhase.CONNECTED
    bound_identity: tuple[int, int] | None = None
    inbound_peer: PeerRole | None = None

    def bind(self, session_id: int, worker_id: int) -> None:
        if self.phase != ConnectionPhase.CONNECTED or self.bound_identity is not None:
            raise ProtocolError("DTP connection is already bound or not registerable")
        if session_id <= 0 or worker_id < 0:
            raise ProtocolError("Invalid assigned DTP connection identity")
        self.bound_identity = (session_id, worker_id)
        self.phase = ConnectionPhase.REGISTERED

    def set_phase(self, phase: ConnectionPhase) -> None:
        """Accept an owner-decided phase; this method does not decide Runtime state."""
        if self.phase == ConnectionPhase.CLOSED:
            raise ProtocolError("Closed DTP connection cannot change phase")
        self.phase = ConnectionPhase(phase)

    def validate(self, header: DTPHeader) -> None:
        header.validate_protocol(self.bound_identity)
        if (
            self.inbound_peer is not None
            and header.message_type not in _INBOUND_BY_PEER[self.inbound_peer]
        ):
            raise ProtocolError(f"DTP message has invalid direction from {self.inbound_peer.value}")
        if header.message_type not in _ALLOWED[self.phase]:
            raise ProtocolError(f"DTP message is invalid in connection phase {self.phase.value}")

    def close(self) -> tuple[int, int] | None:
        identity = self.bound_identity
        self.phase = ConnectionPhase.CLOSED
        self.bound_identity = None
        return identity
