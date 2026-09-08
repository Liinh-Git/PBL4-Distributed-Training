"""DTP connection binding and protocol-order validation.

Runtime owns Attempt and membership transitions.  This object only validates
which wire messages are syntactically legal in an owner-supplied connection
phase and protects the bound connection identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    NO_OPERATION,
)
from pbl4.protocol.header import DTPHeader
from pbl4.protocol.messages import DtpControlMessage, ParameterMeta


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
            MESSAGE_TYPE_EPOCH_END,
            MESSAGE_TYPE_STOP,
            MESSAGE_TYPE_ERROR,
        }
    ),
}


_ALLOWED: dict[ConnectionPhase, frozenset[int]] = {
    ConnectionPhase.CONNECTED: frozenset(
        {MESSAGE_TYPE_HELLO, MESSAGE_TYPE_HELLO_ACK, MESSAGE_TYPE_ERROR}
    ),
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
    _parameter_transfer: tuple[tuple[int, int, int, int], str, int, int] | None = field(
        default=None, init=False, repr=False
    )

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

    def validate(self, header: DTPHeader, message: DtpControlMessage | None = None) -> None:
        header.validate_protocol(self.bound_identity)
        if (
            header.message_type == MESSAGE_TYPE_ERROR
            and header.session_id == 0
            and self.inbound_peer not in {None, PeerRole.RUNTIME}
        ):
            raise ProtocolError("Only Runtime may send pre-registration ERROR")
        if (
            self.inbound_peer is not None
            and header.message_type not in _INBOUND_BY_PEER[self.inbound_peer]
        ):
            raise ProtocolError(f"DTP message has invalid direction from {self.inbound_peer.value}")
        if header.message_type not in _ALLOWED[self.phase]:
            raise ProtocolError(f"DTP message is invalid in connection phase {self.phase.value}")
        if header.message_type == MESSAGE_TYPE_MODEL_INIT and header.worker_id != 0:
            raise ProtocolError("MODEL_INIT is only valid from worker_id=0")
        if header.message_type == MESSAGE_TYPE_PARAMETER_META:
            self._begin_parameter_transfer(header, message)
        elif header.message_type == MESSAGE_TYPE_PARAMETER_CHUNK:
            self._validate_parameter_chunk(header)

    def _begin_parameter_transfer(
        self, header: DTPHeader, message: DtpControlMessage | None
    ) -> None:
        if not isinstance(message, ParameterMeta):
            raise ProtocolError("PARAMETER_META requires its decoded canonical payload")
        purpose = message.transfer_purpose
        if purpose == "model_init":
            if (
                self.inbound_peer != PeerRole.WORKER
                or header.worker_id != 0
                or header.operation_id != NO_OPERATION
                or self.phase != ConnectionPhase.INITIALIZING
            ):
                raise ProtocolError(
                    "model_init parameter transfer is only W0 to Server initialization"
                )
        elif purpose == "model_update":
            if (
                self.inbound_peer != PeerRole.RUNTIME
                or header.operation_id == NO_OPERATION
                or self.phase
                not in {ConnectionPhase.INITIALIZING, ConnectionPhase.WAITING_PARAMETER}
            ):
                raise ProtocolError("model_update parameter transfer is only Server to Worker")
        else:  # ParameterMeta schema currently makes this unreachable.
            raise ProtocolError("Unknown parameter transfer_purpose")
        if self._parameter_transfer is not None:
            raise ProtocolError("A parameter transfer context is already active")
        identity = (
            header.session_id,
            header.worker_id,
            header.operation_id,
            header.tensor_id,
        )
        self._parameter_transfer = (identity, purpose, message.chunk_count, 0)

    def _validate_parameter_chunk(self, header: DTPHeader) -> None:
        if self._parameter_transfer is None:
            raise ProtocolError("PARAMETER_CHUNK arrived without PARAMETER_META context")
        expected_identity, purpose, chunk_count, next_index = self._parameter_transfer
        actual_identity = (
            header.session_id,
            header.worker_id,
            header.operation_id,
            header.tensor_id,
        )
        if actual_identity != expected_identity or header.chunk_index != next_index:
            self._parameter_transfer = None
            raise ProtocolError("PARAMETER_CHUNK does not match its transfer context")
        next_index += 1
        self._parameter_transfer = (
            None
            if next_index == chunk_count
            else (expected_identity, purpose, chunk_count, next_index)
        )

    def close(self) -> tuple[int, int] | None:
        identity = self.bound_identity
        self.phase = ConnectionPhase.CLOSED
        self.bound_identity = None
        self._parameter_transfer = None
        return identity
