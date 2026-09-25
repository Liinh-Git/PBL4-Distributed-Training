"""Allocation Service — business logic for worker allocations, command dispatch, and admission tokens.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

Responsibilities:
- Create worker allocations from scheduler placements in 'REQUESTED' state.
- Validate target node is 'ONLINE' and not 'REVOKED' or 'OFFLINE'.
- Build START_WORKER command with exact parameters:
  * runtime_host = settings.dtp_advertised_host
  * runtime_port = settings.runtime_dtp_port
  * initialization_seed extracted from job.resolved_contract["training"]["training_seed"] (strictly int)
  * short-lived signed worker_join_token with claims (attempt_id, allocation_id, node_id)
- Zero token logging or token in database.
- Dispatch commands through NodeControlGatewayProtocol boundary.
- Handle allocation state transitions:
  * create -> REQUESTED
  * successful dispatch -> DISPATCHED
  * ACK ACCEPTED -> remain DISPATCHED
  * dispatch/send failure -> FAILED
  * start timeout -> FAILED
  * WORKER_STATUS STARTED -> STARTED
  * intentional stop + ended -> ENDED
  * unexpected process exit -> FAILED
- Enforce stop semantics: set desired_state = 'STOPPED', dispatch STOP_WORKER, without modifying Attempt lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from typing import Any, Protocol, runtime_checkable
import uuid

import psycopg

from pbl4.agent_protocol.messages import (
    StartWorkerPayload,
    StopWorkerPayload,
)
from pbl4.common.worker_admission import (
    issue_worker_join_token,
    verify_worker_join_token,
)
from pbl4.management_backend.config import BackendSettings, get_settings
from pbl4.management_backend.repositories import (
    allocation_repository,
    node_repository,
)
from pbl4.management_backend.services.cluster_scheduler import WorkerPlacementSpec
from pbl4.management_backend.services.node_service import (
    NodeNotFoundError,
    NodeOfflineError,
    NodeRevokedError,
)

logger = logging.getLogger(__name__)


# ─── Service Exceptions ───────────────────────────────────────────────────────

class AllocationError(Exception):
    """Base exception for worker allocation service errors."""

    code: str = "ALLOCATION_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AllocationNotFoundError(AllocationError):
    """Raised when an allocation record is not found."""

    code: str = "ALLOCATION_NOT_FOUND"


class AllocationStateError(AllocationError):
    """Raised when an invalid state transition is attempted on an allocation."""

    code: str = "INVALID_STATE"


class WorkerAdmissionConfigError(AllocationError):
    """Raised when worker admission secret is missing in configuration."""

    code: str = "WORKER_ADMISSION_CONFIG_ERROR"


# ─── Gateway Boundary Protocol ────────────────────────────────────────────────

@runtime_checkable
class NodeControlGatewayProtocol(Protocol):
    """Outbound boundary interface for communicating with Node Agents over WSS.

    Decouples AllocationService from the concrete WebSocket connection management.
    """

    def send_start_worker(
        self,
        node_id: str,
        *,
        command: StartWorkerPayload,
    ) -> bool:
        """Send START_WORKER command to node agent. Returns True if successfully transmitted."""
        ...

    def send_stop_worker(
        self,
        node_id: str,
        *,
        command: StopWorkerPayload,
    ) -> bool:
        """Send STOP_WORKER command to node agent. Returns True if successfully transmitted."""
        ...


# ─── Allocation Service Implementation ─────────────────────────────────────────

class AllocationService:
    """Domain service managing WorkerAllocation records, commands, and tokens."""

    @staticmethod
    def get_allocation(conn: psycopg.Connection, allocation_id: str) -> dict[str, Any]:
        """Fetch allocation by ID or raise AllocationNotFoundError."""
        alloc = allocation_repository.get_allocation(conn, allocation_id)
        if alloc is None:
            raise AllocationNotFoundError(f"Allocation '{allocation_id}' not found.")
        return alloc

    @staticmethod
    def list_for_attempt(
        conn: psycopg.Connection,
        attempt_id: str,
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List allocations for an attempt."""
        return allocation_repository.list_for_attempt(conn, attempt_id, active_only=active_only)

    @staticmethod
    def create_allocation(
        conn: psycopg.Connection,
        *,
        attempt_id: str,
        node_id: str,
        device: str,
        allocation_id: str | None = None,
        desired_state: str = allocation_repository.DESIRED_STATE_RUNNING,
        actual_state: str = allocation_repository.ACTUAL_STATE_REQUESTED,
        resource_allocation_jsonb: dict[str, Any] | None = None,
        runtime_endpoint: str | None = None,
        now: datetime | None = None,
        settings: BackendSettings | None = None,
    ) -> dict[str, Any]:
        """Create a worker allocation record in the database.

        Validates:
        - Target node exists and is ONLINE.
        - Rejects OFFLINE or REVOKED target nodes.
        """
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("attempt_id must be a non-empty string.")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node_id must be a non-empty string.")

        # Validate target node state
        node = node_repository.get_node(conn, node_id)
        if node is None:
            raise NodeNotFoundError(f"Target node '{node_id}' does not exist.")
        if node.get("state") == node_repository.NODE_STATE_REVOKED:
            raise NodeRevokedError(f"Cannot allocate worker to REVOKED node '{node_id}'.")
        if node.get("state") != node_repository.NODE_STATE_ONLINE:
            raise NodeOfflineError(
                f"Cannot allocate worker to node '{node_id}' in state '{node.get('state')}'; must be ONLINE."
            )

        app_settings = settings or get_settings()
        endpoint = runtime_endpoint or f"{app_settings.dtp_advertised_host}:{app_settings.runtime_dtp_port}"
        current_time = now or datetime.now(UTC)
        chosen_alloc_id = allocation_id or f"alloc-{uuid.uuid4().hex[:12]}"

        alloc = allocation_repository.create_allocation(
            conn,
            allocation_id=chosen_alloc_id,
            attempt_id=attempt_id,
            node_id=node_id,
            desired_state=desired_state,
            actual_state=actual_state,
            device=device,
            runtime_endpoint=endpoint,
            created_at=current_time,
            resource_allocation_jsonb=resource_allocation_jsonb or {},
        )

        logger.info(
            "Created allocation '%s' on node '%s' for attempt '%s' (actual=REQUESTED, desired=RUNNING)",
            chosen_alloc_id,
            node_id,
            attempt_id,
        )
        return alloc

    @staticmethod
    def create_allocations_for_attempt(
        conn: psycopg.Connection,
        *,
        attempt_id: str,
        placements: list[WorkerPlacementSpec],
        resource_allocation_jsonb: dict[str, Any] | None = None,
        runtime_endpoint: str | None = None,
        now: datetime | None = None,
        settings: BackendSettings | None = None,
    ) -> list[dict[str, Any]]:
        """Create multiple allocation records for an attempt based on scheduler placements."""
        created: list[dict[str, Any]] = []
        for p in placements:
            alloc = AllocationService.create_allocation(
                conn,
                attempt_id=attempt_id,
                node_id=p.node_id,
                device=p.device,
                resource_allocation_jsonb=resource_allocation_jsonb,
                runtime_endpoint=runtime_endpoint,
                now=now,
                settings=settings,
            )
            created.append(alloc)
        return created

    @staticmethod
    def build_start_worker_command(
        *,
        allocation: dict[str, Any],
        job: dict[str, Any] | None = None,
        attempt: dict[str, Any] | None = None,
        settings: BackendSettings | None = None,
        now: float | None = None,
    ) -> StartWorkerPayload:
        """Construct the canonical START_WORKER command with short-lived admission token.

        Invariants enforced:
        - initialization_seed strictly extracted from job.resolved_contract["training"]["training_seed"] as int.
        - worker_admission_secret loaded from settings, never hardcoded.
        - Token issued with exact scope claims: (attempt_id, allocation_id, node_id).
        - Advertised host and port strictly from settings.dtp_advertised_host and runtime_dtp_port.
        """
        app_settings = settings or get_settings()

        allocation_id = str(allocation["allocation_id"])
        attempt_id = str(allocation["attempt_id"])
        node_id = str(allocation["node_id"])
        device = str(allocation["device"])

        # Validate attempt correlation if provided
        if attempt is not None:
            expected_attempt_id = str(attempt.get("attempt_id", ""))
            if expected_attempt_id and expected_attempt_id != attempt_id:
                raise ValueError(
                    f"Attempt ID mismatch: allocation has '{attempt_id}', attempt has '{expected_attempt_id}'"
                )

        # Extract resolved contract from job or attempt
        resolved_contract: dict[str, Any] | None = None
        if job is not None and job.get("resolved_contract"):
            rc = job["resolved_contract"]
            resolved_contract = json.loads(rc) if isinstance(rc, str) else rc
        elif attempt is not None and attempt.get("resolved_contract"):
            rc = attempt["resolved_contract"]
            resolved_contract = json.loads(rc) if isinstance(rc, str) else rc

        if not resolved_contract or not isinstance(resolved_contract, dict):
            raise ValueError("A frozen resolved_contract is required to extract initialization_seed for START_WORKER.")

        # Extract and validate initialization_seed
        training = resolved_contract.get("training")
        if not isinstance(training, dict):
            raise ValueError("resolved_contract is missing 'training' section.")

        seed = training.get("training_seed")
        if seed is None or not isinstance(seed, int) or isinstance(seed, bool):
            raise ValueError(f"initialization_seed must be an integer in resolved_contract['training'], got: {seed!r}")

        # Check admission secret
        secret = app_settings.worker_admission_secret
        if not secret:
            raise WorkerAdmissionConfigError(
                "PBL4_WORKER_ADMISSION_SECRET is not configured; cannot issue worker join token."
            )

        # Issue short-lived worker join token
        token = issue_worker_join_token(
            secret=secret,
            attempt_id=attempt_id,
            allocation_id=allocation_id,
            node_id=node_id,
            ttl_seconds=app_settings.worker_join_token_ttl_seconds,
            now=now,
        )

        # Self-verify token to guarantee claims match perfectly
        claims = verify_worker_join_token(
            secret=secret,
            token=token,
            expected_attempt_id=attempt_id,
            expected_allocation_id=allocation_id,
            expected_node_id=node_id,
            now=now,
        )
        assert claims.attempt_id == attempt_id
        assert claims.allocation_id == allocation_id
        assert claims.node_id == node_id

        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        return StartWorkerPayload(
            command_id=command_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            runtime_host=app_settings.dtp_advertised_host,
            runtime_port=app_settings.runtime_dtp_port,
            device=device,
            initialization_seed=seed,
            worker_join_token=token,
        )

    @staticmethod
    def build_stop_worker_command(
        *,
        allocation: dict[str, Any],
        grace_period_seconds: float = 10.0,
        force: bool = False,
    ) -> StopWorkerPayload:
        """Construct a STOP_WORKER command for a targeted allocation."""
        allocation_id = str(allocation["allocation_id"])
        command_id = f"cmd-{uuid.uuid4().hex[:12]}"
        return StopWorkerPayload(
            command_id=command_id,
            allocation_id=allocation_id,
            grace_period_seconds=grace_period_seconds,
            force=force,
        )

    @staticmethod
    def dispatch_allocation(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        command: StartWorkerPayload,
        gateway: NodeControlGatewayProtocol | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Dispatch START_WORKER command to the target node agent.

        Transitions:
        - Successful dispatch -> DISPATCHED (dispatched_at updated).
        - Gateway transmission failure -> FAILED.
        """
        alloc = AllocationService.get_allocation(conn, allocation_id)
        current_time = now or datetime.now(UTC)
        node_id = str(alloc["node_id"])

        if gateway is not None:
            try:
                success = gateway.send_start_worker(node_id, command=command)
            except Exception as exc:
                logger.error("Exception dispatching START_WORKER to node '%s': %s", node_id, exc)
                success = False

            if not success:
                logger.warning("Failed to dispatch START_WORKER to node '%s'; marking allocation FAILED", node_id)
                updated = allocation_repository.update_actual_state(
                    conn,
                    allocation_id,
                    allocation_repository.ACTUAL_STATE_FAILED,
                    ended_at=current_time,
                    failure_code="NODE_DISPATCH_FAILED",
                    failure_message=f"Failed to transmit START_WORKER to node agent '{node_id}'.",
                )
                return updated or alloc

        # Successful dispatch -> actual_state = DISPATCHED
        updated = allocation_repository.update_actual_state(
            conn,
            allocation_id,
            allocation_repository.ACTUAL_STATE_DISPATCHED,
            dispatched_at=current_time,
        )
        logger.info("Allocation '%s' transitioned to DISPATCHED", allocation_id)
        return updated or alloc

    @staticmethod
    def record_dispatched(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        dispatched_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Explicitly record allocation as DISPATCHED."""
        current_time = dispatched_at or datetime.now(UTC)
        updated = allocation_repository.update_actual_state(
            conn,
            allocation_id,
            allocation_repository.ACTUAL_STATE_DISPATCHED,
            dispatched_at=current_time,
        )
        return updated or AllocationService.get_allocation(conn, allocation_id)

    @staticmethod
    def record_started(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        started_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Record WORKER_STATUS STARTED from agent: actual_state -> STARTED."""
        current_time = started_at or datetime.now(UTC)
        updated = allocation_repository.update_actual_state(
            conn,
            allocation_id,
            allocation_repository.ACTUAL_STATE_STARTED,
            started_at=current_time,
        )
        logger.info("Allocation '%s' transitioned to STARTED", allocation_id)
        return updated or AllocationService.get_allocation(conn, allocation_id)

    @staticmethod
    def record_ended(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        ended_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Record clean process stop in stop flow: actual_state -> ENDED."""
        current_time = ended_at or datetime.now(UTC)
        updated = allocation_repository.terminal_update(
            conn,
            allocation_id,
            allocation_repository.ACTUAL_STATE_ENDED,
            ended_at=current_time,
        )
        logger.info("Allocation '%s' transitioned to ENDED", allocation_id)
        return updated or AllocationService.get_allocation(conn, allocation_id)

    @staticmethod
    def record_failed(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
        ended_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Record worker spawn failure, crash, or launch timeout: actual_state -> FAILED."""
        current_time = ended_at or datetime.now(UTC)
        updated = allocation_repository.terminal_update(
            conn,
            allocation_id,
            allocation_repository.ACTUAL_STATE_FAILED,
            ended_at=current_time,
            failure_code=failure_code,
            failure_message=failure_message,
        )
        logger.warning(
            "Allocation '%s' transitioned to FAILED: code=%s message=%s",
            allocation_id,
            failure_code,
            failure_message,
        )
        return updated or AllocationService.get_allocation(conn, allocation_id)

    @staticmethod
    def stop_allocation(
        conn: psycopg.Connection,
        allocation_id: str,
        *,
        gateway: NodeControlGatewayProtocol | None = None,
        grace_period_seconds: float = 10.0,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Request stopping a worker allocation.

        Invariants:
        - Sets desired_state = 'STOPPED'.
        - Dispatches STOP_WORKER command via gateway if provided.
        - Does NOT directly alter Attempt state or send ABORT_ATTEMPT.
        """
        alloc = AllocationService.get_allocation(conn, allocation_id)
        updated = allocation_repository.update_desired_state(
            conn,
            allocation_id,
            allocation_repository.DESIRED_STATE_STOPPED,
        )

        if gateway is not None:
            stop_cmd = AllocationService.build_stop_worker_command(
                allocation=alloc,
                grace_period_seconds=grace_period_seconds,
                force=force,
            )
            node_id = str(alloc["node_id"])
            try:
                gateway.send_stop_worker(node_id, command=stop_cmd)
            except Exception as exc:
                logger.error("Exception dispatching STOP_WORKER to node '%s': %s", node_id, exc)

        logger.info("Allocation '%s' desired_state set to STOPPED", allocation_id)
        return updated or alloc

    @staticmethod
    def fail_timed_out_dispatched_allocations(
        conn: psycopg.Connection,
        *,
        timeout_seconds: float,
        now: datetime | None = None,
    ) -> list[str]:
        """Mark DISPATCHED allocations that exceed worker_start_timeout_seconds as FAILED.

        Triggered by background maintenance loop.
        """
        current_time = now or datetime.now(UTC)
        active_allocations = allocation_repository.list_active(conn)

        timed_out_ids: list[str] = []
        for alloc in active_allocations:
            if alloc.get("actual_state") != allocation_repository.ACTUAL_STATE_DISPATCHED:
                continue

            dispatched_at = alloc.get("dispatched_at")
            if dispatched_at is None:
                is_timed_out = True
            else:
                is_timed_out = (current_time - dispatched_at).total_seconds() > timeout_seconds

            if is_timed_out:
                alloc_id = str(alloc["allocation_id"])
                allocation_repository.terminal_update(
                    conn,
                    alloc_id,
                    allocation_repository.ACTUAL_STATE_FAILED,
                    ended_at=current_time,
                    failure_code="WORKER_START_TIMEOUT",
                    failure_message="Timed out waiting for WORKER_STATUS STARTED from node agent.",
                )
                timed_out_ids.append(alloc_id)
                logger.warning(
                    "Allocation '%s' timed out in DISPATCHED state after %ss; marked FAILED",
                    alloc_id,
                    timeout_seconds,
                )

        return timed_out_ids


# Module-level convenience functions
get_allocation = AllocationService.get_allocation
list_for_attempt = AllocationService.list_for_attempt
create_allocation = AllocationService.create_allocation
create_allocations_for_attempt = AllocationService.create_allocations_for_attempt
build_start_worker_command = AllocationService.build_start_worker_command
build_stop_worker_command = AllocationService.build_stop_worker_command
dispatch_allocation = AllocationService.dispatch_allocation
record_dispatched = AllocationService.record_dispatched
record_started = AllocationService.record_started
record_ended = AllocationService.record_ended
record_failed = AllocationService.record_failed
stop_allocation = AllocationService.stop_allocation
fail_timed_out_dispatched_allocations = AllocationService.fail_timed_out_dispatched_allocations
