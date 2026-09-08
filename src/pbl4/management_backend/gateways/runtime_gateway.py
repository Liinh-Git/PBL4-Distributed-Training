"""Runtime Gateway — MCP/1 connection and command dispatch seam.

CANONICAL REFERENCES:
- 02. MCP-1
- 04. Cấu trúc mã nguồn & docs/IMPLEMENTATION_CONTRACT.md

INVARIANTS:
- All training commands must be durably persisted in PostgreSQL before MCP/1 dispatch.
- When runtime is disconnected, backend reports degraded state without crashing or dropping
  persisted state.
- Communicates via McpClientPort boundary.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort, McpClientPort

logger = logging.getLogger(__name__)


class RuntimeGateway:
    """MCP/1 client boundary between Management Backend and Runtime."""

    def __init__(self, port: McpClientPort | None = None) -> None:
        self._port: McpClientPort = port or FakeMcpClientPort(initially_connected=False)
        self._runtime_instance_id: str | None = None
        self._connected_at: datetime | None = None
        self._cached_snapshot: dict[str, Any] = self._empty_snapshot()

    @property
    def port(self) -> McpClientPort:
        return self._port

    def set_port(self, port: McpClientPort) -> None:
        """Inject a custom or test port."""
        self._port = port

    @property
    def connected(self) -> bool:
        return self._port.is_connected

    @property
    def runtime_instance_id(self) -> str | None:
        return self._runtime_instance_id

    def set_runtime_instance_id(self, instance_id: str | None) -> None:
        self._runtime_instance_id = instance_id

    def _empty_snapshot(self) -> dict[str, Any]:
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

    def update_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Update the in-memory cached snapshot from a received event or reconciliation."""
        self._cached_snapshot.update(snapshot)
        self._cached_snapshot["stale"] = not self.connected
        self._cached_snapshot["observed_at"] = datetime.now(UTC)

    def get_snapshot(self) -> dict[str, Any]:
        """Return the current management-visible runtime snapshot."""
        snap = dict(self._cached_snapshot)
        snap["stale"] = not self.connected
        return snap

    def send_start_attempt(
        self, command_id: str, attempt_id: str, payload: dict[str, Any] | None = None
    ) -> bool:
        """Dispatch START_ATTEMPT to runtime via MCP/1."""
        if not self.connected:
            logger.warning(
                "Runtime not connected; START_ATTEMPT command %s queued in DB.", command_id
            )
            return False

        dispatched = self._port.send_command(
            command_type="START_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload=payload,
        )
        if dispatched:
            logger.info(
                "START_ATTEMPT dispatched via MCP/1: cmd=%s attempt=%s", command_id, attempt_id
            )
        return dispatched

    def send_abort_attempt(
        self, command_id: str, attempt_id: str, reason: str | None = None
    ) -> bool:
        """Dispatch ABORT_ATTEMPT to runtime via MCP/1."""
        if not self.connected:
            logger.warning(
                "Runtime not connected; ABORT_ATTEMPT command %s queued in DB.", command_id
            )
            return False

        dispatched = self._port.send_command(
            command_type="ABORT_ATTEMPT",
            command_id=command_id,
            target_id=attempt_id,
            payload={"reason": reason},
        )
        if dispatched:
            logger.info(
                "ABORT_ATTEMPT dispatched via MCP/1: cmd=%s attempt=%s", command_id, attempt_id
            )
        return dispatched

    def send_checkpoint_request(
        self, command_id: str, attempt_id: str, reason: str | None = None
    ) -> bool:
        """Dispatch REQUEST_CHECKPOINT to runtime via MCP/1."""
        if not self.connected:
            logger.warning(
                "Runtime not connected; REQUEST_CHECKPOINT command %s queued in DB.", command_id
            )
            return False

        dispatched = self._port.send_command(
            command_type="REQUEST_CHECKPOINT",
            command_id=command_id,
            target_id=attempt_id,
            payload={"reason": reason},
        )
        if dispatched:
            logger.info(
                "REQUEST_CHECKPOINT dispatched via MCP/1: cmd=%s attempt=%s",
                command_id,
                attempt_id,
            )
        return dispatched


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
        logger.info("Runtime gateway configured: %s:%d", host, port)
    else:
        logger.warning("Runtime host/port not configured; gateway running in disconnected mode.")
    return _gateway
