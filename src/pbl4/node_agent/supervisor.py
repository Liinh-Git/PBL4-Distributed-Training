"""Local Worker process supervisor for Node Agent.

Manages Worker process spawning, lifecycle monitoring, graceful stopping,
and crash recovery / reconciliation across Agent restarts.

Enforces rules from NODE_AGENT_IMPLEMENTATION_PLAN.md:
- Strictly 4 local process states: STARTING, RUNNING, STOPPED, FAILED.
- START_WORKER is idempotent by allocation_id.
- STOP_WORKER on terminal allocations is an accepted no-op.
- Reconciles surviving workers on Agent restart via PID + create_time.
- Process exit outside stop_worker is marked FAILED.
- Tokens are passed strictly via environment variables, never CLI flags or logs.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    ERROR_CODE_ALLOCATION_ALREADY_ACTIVE,
    ERROR_CODE_ALLOCATION_NOT_FOUND,
    ERROR_CODE_WORKER_SPAWN_FAILED,
    ERROR_CODE_WORKER_STOP_FAILED,
    StartWorkerPayload,
)

logger = logging.getLogger(__name__)

LOCAL_STATE_STARTING = "STARTING"
LOCAL_STATE_RUNNING = "RUNNING"
LOCAL_STATE_STOPPED = "STOPPED"
LOCAL_STATE_FAILED = "FAILED"

VALID_LOCAL_STATES = {
    LOCAL_STATE_STARTING,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STOPPED,
    LOCAL_STATE_FAILED,
}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    LOCAL_STATE_STARTING: {LOCAL_STATE_RUNNING, LOCAL_STATE_FAILED},
    LOCAL_STATE_RUNNING: {LOCAL_STATE_STOPPED, LOCAL_STATE_FAILED},
    LOCAL_STATE_STOPPED: set(),
    LOCAL_STATE_FAILED: set(),
}


@dataclass
class LocalAllocationRecord:
    """Local state record tracking a Worker process allocation."""

    allocation_id: str
    attempt_id: str
    local_state: str
    created_at: float
    pid: int | None = None
    create_time: float | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.allocation_id, str) or not self.allocation_id:
            raise ValueError("allocation_id must be a non-empty string")
        if not isinstance(self.attempt_id, str) or not self.attempt_id:
            raise ValueError("attempt_id must be a non-empty string")
        if self.local_state not in VALID_LOCAL_STATES:
            raise ValueError(
                f"Invalid local_state '{self.local_state}', must be one of {VALID_LOCAL_STATES}"
            )

    def transition_to(self, new_state: str, *, exit_code: int | None = None) -> None:
        """Perform a validated local state transition."""
        if new_state not in VALID_LOCAL_STATES:
            raise ValueError(f"Invalid target state '{new_state}'")
        allowed = _ALLOWED_TRANSITIONS.get(self.local_state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Illegal state transition from {self.local_state} to {new_state}. "
                f"Allowed transitions: {allowed}"
            )
        self.local_state = new_state
        if exit_code is not None:
            try:
                self.exit_code = int(exit_code)
            except Exception:
                self.exit_code = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "attempt_id": self.attempt_id,
            "local_state": self.local_state,
            "created_at": self.created_at,
            "pid": self.pid,
            "create_time": self.create_time,
            "exit_code": self.exit_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LocalAllocationRecord:
        if not isinstance(data, dict):
            raise ValueError("Record data must be a dictionary")
        return cls(
            allocation_id=data["allocation_id"],
            attempt_id=data["attempt_id"],
            local_state=data["local_state"],
            created_at=float(data["created_at"]),
            pid=data.get("pid"),
            create_time=float(data["create_time"]) if data.get("create_time") is not None else None,
            exit_code=data.get("exit_code"),
        )


class WorkerProcessSupervisor:
    """Supervises Worker OS processes launched locally on this Node."""

    def __init__(self, var_dir: str | Path, *, node_id: str = "node-default") -> None:
        self.var_dir = Path(var_dir)
        self.var_dir.mkdir(parents=True, exist_ok=True)
        self.node_id = node_id
        self._records_file = self.var_dir / "allocations.json"
        self._lock = threading.Lock()
        self._records: dict[str, LocalAllocationRecord] = {}
        self._subprocesses: dict[str, subprocess.Popen[Any]] = {}

        self._load_records()

    def _save_records(self) -> None:
        """Persist in-memory records to disk with Windows file lock retry handling."""
        data = {alloc_id: r.to_dict() for alloc_id, r in self._records.items()}
        tmp_file = self._records_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        for attempt in range(5):
            try:
                tmp_file.replace(self._records_file)
                return
            except PermissionError:
                if attempt == 4:
                    logger.warning(
                        "Permission denied replacing %s; skipping this write cycle",
                        self._records_file,
                    )
                    return
                time.sleep(0.05 * (attempt + 1))

    def _load_records(self) -> None:
        """Load records from disk if available."""
        if not self._records_file.is_file():
            return
        try:
            content = self._records_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                for alloc_id, item in data.items():
                    try:
                        self._records[alloc_id] = LocalAllocationRecord.from_dict(item)
                    except Exception as exc:
                        logger.warning("Skipping corrupt allocation record %s: %s", alloc_id, exc)
        except Exception as exc:
            logger.warning("Failed to load records from %s: %s", self._records_file, exc)

    def reconcile_on_startup(self) -> list[LocalAllocationRecord]:
        """Reconcile surviving Worker processes on Agent startup / recovery.

        Checks whether previously recorded processes are still alive and match
        PID and process creation time. If verification fails, transitions to FAILED
        with exit_code = None (never fabricates exit codes).
        """
        with self._lock:
            for record in list(self._records.values()):
                if record.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING):
                    if record.pid is None or record.pid <= 0 or record.create_time is None:
                        logger.warning(
                            "Cannot verify allocation %s: missing PID or create_time. "
                            "Marking FAILED.",
                            record.allocation_id,
                        )
                        record.transition_to(LOCAL_STATE_FAILED, exit_code=None)
                        continue

                    try:
                        proc = psutil.Process(record.pid)
                        # Check running status and create_time within acceptable margin (2s)
                        if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                            p_create_time = proc.create_time()
                            if abs(p_create_time - record.create_time) < 2.0:
                                logger.info(
                                    "Reattached surviving Worker process PID=%d for allocation %s",
                                    record.pid,
                                    record.allocation_id,
                                )
                                record.local_state = LOCAL_STATE_RUNNING
                                continue

                        logger.warning(
                            "Worker process PID=%d for allocation %s is dead or "
                            "create_time mismatched. Marking FAILED.",
                            record.pid,
                            record.allocation_id,
                        )
                        record.transition_to(LOCAL_STATE_FAILED, exit_code=None)
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                        logger.warning(
                            "Process PID=%d for allocation %s not found: %s. Marking FAILED.",
                            record.pid,
                            record.allocation_id,
                            exc,
                        )
                        record.transition_to(LOCAL_STATE_FAILED, exit_code=None)

            self._save_records()
            return list(self._records.values())

    def spawn_worker(self, command: StartWorkerPayload) -> tuple[str, str | None]:
        """Spawn a new Worker process for the specified allocation.

        Idempotency rules:
        - If already STARTING or RUNNING: returns (ACCEPTED, None) no-op.
        - If already STOPPED or FAILED: returns (REJECTED, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE).
        - If new: creates STARTING record, spawns process, verifies PID, transitions to RUNNING.

        Returns:
            (status, error_code_or_none)
        """
        with self._lock:
            existing = self._records.get(command.allocation_id)
            if existing is not None:
                if existing.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING):
                    logger.info(
                        "Duplicate START_WORKER for active allocation %s in state %s: "
                        "ACCEPTED (no-op)",
                        command.allocation_id,
                        existing.local_state,
                    )
                    return (COMMAND_STATUS_ACCEPTED, None)
                else:
                    logger.warning(
                        "START_WORKER rejected for terminal allocation %s in state %s",
                        command.allocation_id,
                        existing.local_state,
                    )
                    return (COMMAND_STATUS_REJECTED, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE)

            # Intent recorded as STARTING
            record = LocalAllocationRecord(
                allocation_id=command.allocation_id,
                attempt_id=command.attempt_id,
                local_state=LOCAL_STATE_STARTING,
                created_at=time.time(),
            )
            self._records[command.allocation_id] = record
            self._save_records()

            cmd_args = [
                sys.executable,
                "-m",
                "pbl4.worker.entrypoint",
                "--runtime-host",
                command.runtime_host,
                "--runtime-port",
                str(command.runtime_port),
                "--attempt-id",
                command.attempt_id,
                "--allocation-id",
                command.allocation_id,
                "--node-id",
                self.node_id,
                "--device",
                command.device,
                "--initialization-seed",
                str(command.initialization_seed),
            ]

            env = os.environ.copy()
            # Token passed strictly via environment variable, never command line
            env["PBL4_WORKER_JOIN_TOKEN"] = command.worker_join_token

            spawn_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                spawn_kwargs["start_new_session"] = True

            try:
                proc = subprocess.Popen(cmd_args, env=env, **spawn_kwargs)
                self._subprocesses[command.allocation_id] = proc
                record.pid = proc.pid

                try:
                    p_info = psutil.Process(proc.pid)
                    record.create_time = float(p_info.create_time())
                except Exception:
                    record.create_time = float(time.time())

                record.transition_to(LOCAL_STATE_RUNNING)
                self._save_records()
                logger.info(
                    "Worker spawned successfully: allocation_id=%s, pid=%d",
                    command.allocation_id,
                    proc.pid,
                )
                return (COMMAND_STATUS_ACCEPTED, None)
            except Exception as exc:
                logger.error(
                    "Failed spawning worker for allocation %s: %s", command.allocation_id, exc
                )
                record.transition_to(LOCAL_STATE_FAILED, exit_code=None)
                self._save_records()
                return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_SPAWN_FAILED)

    def stop_worker(
        self,
        allocation_id: str,
        grace_period_seconds: float = 10.0,
        force: bool = False,
    ) -> tuple[str, str | None]:
        """Stop an active Worker process.

        Idempotency rules:
        - If allocation not found: returns (REJECTED, ERROR_CODE_ALLOCATION_NOT_FOUND).
        - If already STOPPED or FAILED: returns (ACCEPTED, None) no-op.
        - If STARTING or RUNNING: stop according to force policy, then mark STOPPED.

        Returns:
            (status, error_code_or_none)
        """
        with self._lock:
            record = self._records.get(allocation_id)
            if record is None:
                return (COMMAND_STATUS_REJECTED, ERROR_CODE_ALLOCATION_NOT_FOUND)

            if record.local_state in (LOCAL_STATE_STOPPED, LOCAL_STATE_FAILED):
                logger.info(
                    "STOP_WORKER for terminal allocation %s in state %s: ACCEPTED (no-op)",
                    allocation_id,
                    record.local_state,
                )
                return (COMMAND_STATUS_ACCEPTED, None)

            # Process active or starting
            proc = self._subprocesses.get(allocation_id)
            exit_code: int | None = None
            stopped = False

            if proc is not None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=grace_period_seconds)
                    except subprocess.TimeoutExpired:
                        if force:
                            proc.kill()
                            proc.wait(timeout=2.0)
                        else:
                            logger.warning(
                                "Worker allocation %s did not stop within grace period; "
                                "force=false so it remains RUNNING",
                                allocation_id,
                            )
                            return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_STOP_FAILED)
                    exit_code = proc.returncode
                    stopped = True
                except Exception as exc:
                    logger.warning("Error stopping subprocess for %s: %s", allocation_id, exc)
                    return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_STOP_FAILED)
            elif record.pid is not None:
                # Process was reattached or spawned in previous agent instance
                try:
                    p = psutil.Process(record.pid)
                    if p.is_running() and (
                        record.create_time is None
                        or abs(p.create_time() - record.create_time) < 2.0
                    ):
                        p.terminate()
                        try:
                            p.wait(timeout=grace_period_seconds)
                        except psutil.TimeoutExpired:
                            if force:
                                p.kill()
                                p.wait(timeout=2.0)
                            else:
                                return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_STOP_FAILED)
                        stopped = True
                    else:
                        stopped = True
                except psutil.NoSuchProcess:
                    stopped = True
                except (psutil.AccessDenied, psutil.Error) as exc:
                    logger.warning("Error stopping reattached worker %s: %s", allocation_id, exc)
                    return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_STOP_FAILED)
            else:
                stopped = True

            if not stopped:
                return (COMMAND_STATUS_REJECTED, ERROR_CODE_WORKER_STOP_FAILED)
            self._subprocesses.pop(allocation_id, None)
            record.transition_to(LOCAL_STATE_STOPPED, exit_code=exit_code)
            self._save_records()
            logger.info("Worker allocation %s successfully stopped", allocation_id)
            return (COMMAND_STATUS_ACCEPTED, None)

    def poll(self) -> list[LocalAllocationRecord]:
        """Poll active workers and detect unexpected termination.

        Any worker exiting outside the stop_worker flow is transitioned to FAILED.
        """
        with self._lock:
            state_changed = False
            for allocation_id, record in list(self._records.items()):
                if record.local_state == LOCAL_STATE_RUNNING:
                    proc = self._subprocesses.get(allocation_id)
                    if proc is not None:
                        ret = proc.poll()
                        if ret is not None:
                            logger.warning(
                                "Worker allocation %s terminated unexpectedly with "
                                "returncode %d. Transitioning to FAILED.",
                                allocation_id,
                                ret,
                            )
                            self._subprocesses.pop(allocation_id, None)
                            record.transition_to(LOCAL_STATE_FAILED, exit_code=ret)
                            state_changed = True
                    elif record.pid is not None:
                        try:
                            p = psutil.Process(record.pid)
                            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                                logger.warning(
                                    "Worker allocation %s (PID=%d) terminated unexpectedly. "
                                    "Transitioning to FAILED.",
                                    allocation_id,
                                    record.pid,
                                )
                                record.transition_to(LOCAL_STATE_FAILED, exit_code=None)
                                state_changed = True
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            logger.warning(
                                "Worker allocation %s (PID=%d) no longer exists. "
                                "Transitioning to FAILED.",
                                allocation_id,
                                record.pid,
                            )
                            record.transition_to(LOCAL_STATE_FAILED, exit_code=None)
                            state_changed = True

            if state_changed or not self._records_file.exists():
                self._save_records()
            return list(self._records.values())

    def list_records(self) -> list[LocalAllocationRecord]:
        """Return a copy of all allocation records."""
        with self._lock:
            return list(self._records.values())

    def get_record(self, allocation_id: str) -> LocalAllocationRecord | None:
        """Retrieve a specific allocation record by allocation_id."""
        with self._lock:
            return self._records.get(allocation_id)
