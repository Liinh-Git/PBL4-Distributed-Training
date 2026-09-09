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

import concurrent.futures
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pbl4.management_backend.gateways.mcp_port import (
    McpClientPort,
    TruthfulDisconnectedMcpPort,
)

logger = logging.getLogger(__name__)

VALID_COMMAND_STATES = {"ACCEPTED", "DEFERRED", "SUCCEEDED", "REJECTED", "FAILED"}


@dataclass
class AttemptRuntimeCursor:
    max_seen_seq: int = 0
    highest_contiguous_seq: int | None = None
    authoritative_snapshot_seq: int | None = None
    gap_fenced: bool = False
    stale: bool = True
    observed_at: datetime | None = None


class RuntimeUnavailableError(Exception):
    """Raised when Runtime is disconnected or command dispatch fails/times out."""

    def __init__(self, message: str, command_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.command_id = command_id


class DatabaseUnavailableError(Exception):
    """Raised when a Runtime result cannot be durably recorded in PostgreSQL."""

    def __init__(self, message: str, command_id: str | None = None) -> None:
        super().__init__(message)
        self.command_id = command_id


class RuntimeGateway:
    """MCP/1 client boundary between Management Backend and Runtime."""

    def __init__(self, port: McpClientPort | None = None) -> None:
        self._port: McpClientPort = port or TruthfulDisconnectedMcpPort()
        self._runtime_instance_id: str | None = None
        self._connected_at: datetime | None = None
        self._cached_snapshot: dict[str, Any] = self._empty_snapshot()
        self._attempt_snapshots: dict[str, dict[str, Any]] = {}
        self._attempt_cursors: dict[str, AttemptRuntimeCursor] = {}
        self._pending_results: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}

        self._port.set_message_handler(self._handle_inbound_message)

    @property
    def port(self) -> McpClientPort:
        return self._port

    def set_port(self, port: McpClientPort) -> None:
        """Inject a custom or test port."""
        self._port = port
        self._port.set_message_handler(self._handle_inbound_message)

    @property
    def connected(self) -> bool:
        return self._port.is_connected

    @property
    def runtime_instance_id(self) -> str | None:
        return self._runtime_instance_id

    def set_runtime_instance_id(self, instance_id: str | None) -> None:
        self._runtime_instance_id = instance_id

    def get_cursor(self, attempt_id: str) -> AttemptRuntimeCursor:
        """Return the sequence cursor owned exclusively by one Attempt."""
        return self._attempt_cursors.setdefault(attempt_id, AttemptRuntimeCursor())

    def record_event_seq(self, attempt_id: str, seq: int, conn: Any) -> None:
        """Track one Attempt's event continuity and fence gaps."""
        from pbl4.management_backend.repositories import event_repository
        from pbl4.management_backend.websocket import hub

        cursor = self.get_cursor(attempt_id)
        cursor.max_seen_seq = max(cursor.max_seen_seq, seq)
        cursor.observed_at = datetime.now(UTC)
        cursor.stale = not self.connected

        expected = (
            (cursor.highest_contiguous_seq + 1)
            if cursor.highest_contiguous_seq is not None
            else (
                cursor.authoritative_snapshot_seq + 1
                if cursor.authoritative_snapshot_seq is not None
                else 1
            )
        )

        if seq > expected:
            logger.warning(
                "Event gap detected for attempt %s: expected %s, received %s (fencing projection)",
                attempt_id,
                expected,
                seq,
            )
            cursor.gap_fenced = True
            snap = self._attempt_snapshots.get(attempt_id)
            if snap is not None:
                snap["management_event_gap_count"] = snap.get("management_event_gap_count", 0) + 1
            hub.broadcast_sync(
                attempt_id,
                {
                    "kind": "GAP",
                    "attempt_id": attempt_id,
                    "runtime_event_seq": None,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "payload": {
                        "expected_seq": expected,
                        "received_seq": seq,
                        "reason": f"Event gap: expected {expected}, received {seq}",
                    },
                },
            )
        elif seq == expected:
            cursor.highest_contiguous_seq = seq
            # Drain contiguous cursor through any pre-persisted events in DB
            while True:
                next_ev = event_repository.get_event_by_seq(
                    conn, attempt_id, cursor.highest_contiguous_seq + 1
                )
                if next_ev is not None:
                    cursor.highest_contiguous_seq += 1
                else:
                    break

            if cursor.highest_contiguous_seq >= cursor.max_seen_seq:
                if cursor.gap_fenced:
                    logger.info(
                        "Event gap closed for attempt %s; contiguous cursor at %s",
                        attempt_id,
                        cursor.highest_contiguous_seq,
                    )
                cursor.gap_fenced = False

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

    def get_snapshot(self, attempt_id: str | None = None) -> dict[str, Any]:
        """Return the current management-visible runtime snapshot."""
        if attempt_id is None:
            snap = dict(self._cached_snapshot)
            snap["stale"] = not self.connected
            return snap

        snap = dict(self._attempt_snapshots.get(attempt_id, self._empty_snapshot()))
        cursor = self.get_cursor(attempt_id)
        snap["attempt_id"] = attempt_id
        snap["active_attempt_id"] = attempt_id
        snap["stale"] = cursor.stale or not self.connected
        snap["observed_at"] = cursor.observed_at
        snap["runtime_event_seq"] = cursor.authoritative_snapshot_seq
        return snap

    def get_authoritative_snapshot(self, attempt_id: str) -> dict[str, Any] | None:
        """Return authoritative snapshot dictionary with sequence tracking metadata."""
        cursor = self.get_cursor(attempt_id)
        if cursor.authoritative_snapshot_seq is None:
            return None
        snap = self.get_snapshot(attempt_id)
        snap["authoritative_snapshot_seq"] = cursor.authoritative_snapshot_seq
        snap["highest_contiguous_seq"] = cursor.highest_contiguous_seq
        snap["max_seen_seq"] = cursor.max_seen_seq
        return snap

    def on_disconnect(self) -> None:
        """Preserve the last Attempt projection and mark it stale on disconnect."""
        self._cached_snapshot["stale"] = True
        for attempt_id, cursor in self._attempt_cursors.items():
            cursor.stale = True
            if attempt_id in self._attempt_snapshots:
                self._attempt_snapshots[attempt_id]["stale"] = True
        logger.info("Runtime disconnected; snapshot marked stale, attempt preserved.")

    # ─── Inbound Management Message Dispatcher ────────────────────────────────

    def _handle_inbound_message(self, msg_type: str, payload: dict[str, Any]) -> None:
        if msg_type == "MGMT_HELLO_ACK":
            self.handle_hello_ack(payload)
        elif msg_type == "STATE_SNAPSHOT":
            self.handle_state_snapshot(payload)
        elif msg_type == "COMMAND_RESULT":
            self.handle_command_result(payload)
        elif msg_type == "RUNTIME_EVENT":
            self.handle_runtime_event(payload)
        else:
            logger.warning("Unknown inbound MCP message type: %s", msg_type)

    def handle_hello_ack(self, payload: dict[str, Any]) -> None:
        """MGMT_HELLO_ACK -> ALWAYS request GET_STATE."""
        logger.info("Received MGMT_HELLO_ACK: %s", payload)
        if "runtime_instance_id" in payload:
            self._runtime_instance_id = payload["runtime_instance_id"]
        # Always request authoritative runtime state immediately
        state = self._port.request_state()
        if state:
            self.handle_state_snapshot(state)

    def handle_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        """STATE_SNAPSHOT -> authoritative Runtime projection reconciliation."""
        attempt_id = snapshot.get("active_attempt_id") or snapshot.get("attempt_id")
        snap_seq = snapshot.get("runtime_event_seq")
        if snap_seq is None and "snapshot_seq" in snapshot:
            snap_seq = snapshot["snapshot_seq"]
        if not attempt_id or not isinstance(snap_seq, int) or snap_seq < 0:
            logger.warning("Ignoring malformed STATE_SNAPSHOT without Attempt cursor: %s", snapshot)
            return

        workers = snapshot.get("workers")
        if workers is not None and not isinstance(workers, list):
            logger.warning("Ignoring STATE_SNAPSHOT whose workers field is not a list")
            return

        observed_at = datetime.now(UTC)
        try:
            from pbl4.management_backend import db
            from pbl4.management_backend.repositories import (
                attempt_repository,
                worker_session_repository,
            )

            with db.transaction() as conn:
                attempt = attempt_repository.get_attempt(conn, attempt_id)
                if attempt is None:
                    raise ValueError(f"Unknown attempt '{attempt_id}' in STATE_SNAPSHOT")
                metadata = attempt.get("runtime_metadata") or {}
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                for key in (
                    "training_strategy",
                    "epoch",
                    "current_operation_id",
                    "current_batch_ordinal",
                    "model_version",
                    "strategy_state",
                    "checkpoint_state",
                    "latest_checkpoint_id",
                    "recovery_cursor",
                ):
                    if key in snapshot:
                        metadata[key] = snapshot[key]
                metadata.update(
                    {
                        "authoritative_snapshot_seq": snap_seq,
                        "highest_contiguous_seq": snap_seq,
                        "stale": False,
                        "observed_at": observed_at.isoformat(),
                    }
                )
                new_state = (
                    snapshot.get("attempt_state") or snapshot.get("state") or attempt["state"]
                )
                attempt_repository.update_attempt_state(
                    conn,
                    attempt_id,
                    new_state,
                    runtime_metadata=metadata,
                )

                for worker in workers or []:
                    if not isinstance(worker, dict) or worker.get("worker_id") is None:
                        logger.warning("Ignoring malformed worker snapshot entry: %s", worker)
                        continue
                    if not worker.get("state"):
                        logger.warning(
                            "Worker snapshot missing state; preserving prior projection: %s", worker
                        )
                        continue
                    required = ("session_id", "node_label", "protocol_version", "connected_at")
                    if any(worker.get(field) is None for field in required):
                        logger.warning(
                            "Worker snapshot missing required identity fields: %s", worker
                        )
                        continue
                    connected_at = worker["connected_at"]
                    if isinstance(connected_at, str):
                        connected_at = datetime.fromisoformat(connected_at)
                    worker_session_repository.upsert_session(
                        conn,
                        session_id=worker["session_id"],
                        attempt_id=attempt_id,
                        worker_id=worker["worker_id"],
                        node_label=worker["node_label"],
                        protocol_version=worker["protocol_version"],
                        state=worker["state"],
                        connected_at=connected_at,
                        last_heartbeat_at=worker.get("last_heartbeat_at"),
                        disconnected_at=worker.get("disconnected_at"),
                        failure_code=worker.get("failure_code"),
                    )
        except Exception as exc:
            logger.warning("Could not reconcile STATE_SNAPSHOT into PostgreSQL: %s", exc)
            return

        reconciled = {**self._empty_snapshot(), **snapshot}
        reconciled.update(
            {
                "attempt_id": attempt_id,
                "active_attempt_id": attempt_id,
                "runtime_event_seq": snap_seq,
                "stale": False,
                "observed_at": observed_at,
            }
        )
        self._attempt_snapshots[attempt_id] = reconciled
        self._cached_snapshot.update(reconciled)
        cursor = self.get_cursor(attempt_id)
        cursor.authoritative_snapshot_seq = snap_seq
        cursor.highest_contiguous_seq = snap_seq
        cursor.max_seen_seq = max(cursor.max_seen_seq, snap_seq)
        cursor.gap_fenced = False
        cursor.stale = False
        cursor.observed_at = observed_at

        try:
            from pbl4.management_backend.websocket import hub

            hub.broadcast_sync(
                attempt_id,
                {
                    "kind": "SNAPSHOT",
                    "attempt_id": attempt_id,
                    "runtime_event_seq": snap_seq,
                    "occurred_at": observed_at.isoformat(),
                    "payload": reconciled,
                },
            )
        except Exception as exc:
            logger.debug("Failed to broadcast snapshot: %s", exc)

    def handle_command_result(self, payload: dict[str, Any]) -> None:
        """COMMAND_RESULT -> update existing durable ControlCommand."""
        command_id = payload.get("command_id")
        if not command_id:
            logger.warning("Received COMMAND_RESULT without command_id: %s", payload)
            return

        state = payload.get("state") or payload.get("command_state")
        if state not in VALID_COMMAND_STATES:
            logger.warning(
                "Received malformed COMMAND_RESULT state for command %s: %r", command_id, state
            )
            return
        result = payload.get("result") or {}

        try:
            from pbl4.management_backend import db
            from pbl4.management_backend.repositories import command_repository

            with db.transaction() as conn:
                updated = command_repository.update_command_state(
                    conn,
                    command_id=command_id,
                    new_state=state,
                    result=result,
                )
                if updated is None:
                    raise RuntimeError(f"Unknown durable command '{command_id}'.")
        except Exception as exc:
            logger.error("Could not durably persist COMMAND_RESULT for %s: %s", command_id, exc)
            fut = self._pending_results.pop(command_id, None)
            if fut and not fut.done():
                fut.set_exception(
                    DatabaseUnavailableError(
                        f"Could not durably persist result for command '{command_id}'.",
                        command_id=command_id,
                    )
                )
            return

        fut = self._pending_results.pop(command_id, None)
        if fut and not fut.done():
            fut.set_result(
                {"command_id": command_id, "state": state, "result": result, "payload": payload}
            )

    def handle_runtime_event(self, payload: dict[str, Any]) -> None:
        """RUNTIME_EVENT -> event ingestion / dedup / gap handling / projection / WS publish."""
        attempt_id = payload.get("attempt_id")
        seq = payload.get("runtime_event_seq")
        if not attempt_id or not isinstance(seq, int) or seq < 1:
            logger.warning("Ignoring malformed RUNTIME_EVENT without Attempt cursor: %s", payload)
            return
        event_type = payload.get("event_type", "UNKNOWN")
        severity = payload.get("severity", "INFO")
        occurred_at_raw = payload.get("occurred_at")
        occurred_at = datetime.now(UTC)
        if occurred_at_raw:
            with contextlib.suppress(Exception):
                occurred_at = (
                    datetime.fromisoformat(occurred_at_raw)
                    if isinstance(occurred_at_raw, str)
                    else occurred_at_raw
                )

        try:
            from pbl4.management_backend import db
            from pbl4.management_backend.services import event_ingest

            source_component = payload.get("source_component", "Runtime")
            event_payload = payload.get("payload") or payload
            with db.transaction() as conn:
                ingest_result = event_ingest.ingest_runtime_event(
                    conn,
                    attempt_id=attempt_id,
                    runtime_event_seq=seq,
                    event_type=event_type,
                    severity=severity,
                    occurred_at=occurred_at,
                    source_component=source_component,
                    payload=event_payload,
                )
            if ingest_result.inserted and attempt_id is not None:
                with db.get_connection() as conn:
                    self.record_event_seq(attempt_id, seq, conn)
                event_ingest.broadcast_runtime_event(
                    attempt_id=attempt_id,
                    runtime_event_seq=seq,
                    event_type=event_type,
                    severity=severity,
                    occurred_at=occurred_at,
                    source_component=source_component,
                    payload=event_payload,
                )
        except Exception as exc:
            logger.debug("Failed to ingest runtime event: %s", exc)

    # ─── Outbound Bounded Command Dispatch ────────────────────────────────────

    def send_command_and_wait_result(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Dispatch command and await bounded COMMAND_RESULT acceptance.

        If transport fails or downstream acceptance is not observed within timeout,
        raises RuntimeUnavailableError(message, command_id=command_id).
        Does NOT mark the command FAILED.
        """
        if not self.connected:
            logger.warning(
                "Runtime not connected; command %s (%s) remains PENDING.", command_id, command_type
            )
            raise RuntimeUnavailableError(
                f"Runtime is not connected; command '{command_id}' remains PENDING.",
                command_id=command_id,
            )

        fut: concurrent.futures.Future[dict[str, Any]] = concurrent.futures.Future()
        self._pending_results[command_id] = fut

        try:
            dispatched = self._port.send_command(
                command_type=command_type,
                command_id=command_id,
                target_id=target_id,
                payload=payload,
            )
            if not dispatched:
                self._pending_results.pop(command_id, None)
                raise RuntimeUnavailableError(
                    f"Transport failed to dispatch command '{command_id}' via MCP/1.",
                    command_id=command_id,
                )

            # Wait for correlated COMMAND_RESULT from downstream
            result = fut.result(timeout=timeout)
            logger.info("Command %s accepted by runtime: %s", command_id, result.get("state"))
            return result
        except concurrent.futures.TimeoutError as exc:
            self._pending_results.pop(command_id, None)
            logger.warning(
                "Command %s timed out awaiting downstream acceptance (%ss)", command_id, timeout
            )
            raise RuntimeUnavailableError(
                f"Command '{command_id}' timed out awaiting downstream acceptance.",
                command_id=command_id,
            ) from exc
        except Exception:
            self._pending_results.pop(command_id, None)
            raise

    def send_start_attempt(
        self, command_id: str, attempt_id: str, payload: dict[str, Any] | None = None
    ) -> bool:
        """Legacy bool wrapper for start attempt."""
        try:
            res = self.send_command_and_wait_result(
                "START_ATTEMPT", command_id, attempt_id, payload
            )
            return res.get("state") in {"ACCEPTED", "SUCCEEDED", "DEFERRED"}
        except RuntimeUnavailableError:
            return False

    def send_abort_attempt(
        self, command_id: str, attempt_id: str, reason: str | None = None
    ) -> bool:
        """Legacy bool wrapper for abort attempt."""
        try:
            res = self.send_command_and_wait_result(
                "ABORT_ATTEMPT", command_id, attempt_id, {"reason": reason}
            )
            return res.get("state") in {"ACCEPTED", "SUCCEEDED", "DEFERRED"}
        except RuntimeUnavailableError:
            return False

    def send_checkpoint_request(
        self, command_id: str, attempt_id: str, reason: str | None = None
    ) -> bool:
        """Legacy bool wrapper for checkpoint request."""
        try:
            res = self.send_command_and_wait_result(
                "REQUEST_CHECKPOINT", command_id, attempt_id, {"reason": reason}
            )
            return res.get("state") in {"ACCEPTED", "SUCCEEDED", "DEFERRED"}
        except RuntimeUnavailableError:
            return False


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
