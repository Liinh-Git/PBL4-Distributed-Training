"""Runtime Gateway — MCP/1 connection stub.

In V1 the runtime component is external. This stub maintains a "not connected"
state and provides the interface that services use to communicate with runtime.

When the runtime connects via MCP/1, this gateway will:
1. Establish TCP connection to the runtime management endpoint.
2. Receive RuntimeEvent stream → forward to WebSocket broadcast + event persistence.
3. Send COMMAND packets → ABORT_ATTEMPT, REQUEST_CHECKPOINT, START_ATTEMPT.
4. Handle STATE_SNAPSHOT for reconciliation after reconnect.

CRITICAL INVARIANTS (from data-flow spec):
- DB downtime does NOT stop training (runtime is independent).
- Command must be persisted in DB BEFORE being dispatched via MCP/1.
- Runtime communicates with Backend ONLY via MCP/1 — not DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class RuntimeGateway:
    """MCP/1 client boundary between Management Backend and Runtime.

    V1 status: stub — runtime not connected.
    The interface is fully defined so services can program against it.
    """

    def __init__(self) -> None:
        self._connected = False
        self._runtime_instance_id: str | None = None
        self._connected_at: datetime | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def runtime_instance_id(self) -> str | None:
        return self._runtime_instance_id

    def get_snapshot(self) -> dict:
        """Return the current management-visible runtime snapshot.

        Returns stale=True when not connected to runtime.
        """
        return {
            "runtime_instance_id": self._runtime_instance_id,
            "active_job_id": None,
            "active_attempt_id": None,
            "attempt_state": None,
            "training_strategy": None,
            "checkpoint_policy": None,
            "epoch": None,
            "current_operation_id": None,
            "current_batch_ordinal": None,
            "model_version": None,
            "workers": [],
            "strategy_state": None,
            "checkpoint_state": None,
            "latest_checkpoint_id": None,
            "recovery_cursor": None,
            "dataset_build_id": None,
            "dataset_manifest_hash": None,
            "management_event_gap_count": 0,
            "stale": True,
            "observed_at": None,
            "runtime_event_seq": None,
        }

    def send_start_attempt(self, command_id: str, attempt_id: str, payload: dict) -> bool:
        """Dispatch START_ATTEMPT to runtime via MCP/1.

        Returns True if dispatched, False if runtime unavailable.
        """
        if not self._connected:
            logger.warning(
                "Runtime not connected; START_ATTEMPT command %s queued but not dispatched.", command_id
            )
            return False
        # TODO: Implement MCP/1 COMMAND packet send when runtime is available
        logger.info("START_ATTEMPT dispatched: cmd=%s attempt=%s", command_id, attempt_id)
        return True

    def send_abort_attempt(self, command_id: str, attempt_id: str, reason: str | None = None) -> bool:
        """Dispatch ABORT_ATTEMPT to runtime via MCP/1."""
        if not self._connected:
            logger.warning(
                "Runtime not connected; ABORT_ATTEMPT command %s not dispatched.", command_id
            )
            return False
        # TODO: Implement MCP/1 COMMAND packet send when runtime is available
        logger.info("ABORT_ATTEMPT dispatched: cmd=%s attempt=%s", command_id, attempt_id)
        return True

    def send_checkpoint_request(self, command_id: str, attempt_id: str) -> bool:
        """Dispatch REQUEST_CHECKPOINT to runtime via MCP/1."""
        if not self._connected:
            logger.warning(
                "Runtime not connected; REQUEST_CHECKPOINT command %s not dispatched.", command_id
            )
            return False
        # TODO: Implement MCP/1 COMMAND packet send when runtime is available
        logger.info("REQUEST_CHECKPOINT dispatched: cmd=%s attempt=%s", command_id, attempt_id)
        return True


# Module-level singleton — initialized in app startup lifespan
_gateway: RuntimeGateway | None = None


def get_gateway() -> RuntimeGateway:
    global _gateway
    if _gateway is None:
        _gateway = RuntimeGateway()
    return _gateway


def init_gateway(host: str | None, port: int | None) -> RuntimeGateway:
    global _gateway
    _gateway = RuntimeGateway()
    if host and port:
        logger.info(
            "Runtime gateway configured (not yet connected): %s:%d", host, port
        )
    else:
        logger.warning("Runtime host/port not configured; runtime gateway in stub mode.")
    return _gateway
