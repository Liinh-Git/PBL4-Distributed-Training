"""Production Runtime composition for one active distributed Attempt."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes
from pbl4.protocol.messages import DatasetAssignment, StepStart
from pbl4.protocol.parameter_manifest import ParameterManifest
from pbl4.protocol.transfer import CompletedTensorTransfer
from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.checkpoint_v1 import CheckpointV1Serializer
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.dataset_manifest_client import DatasetManifestClient, PinnedDatasetManifest
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.heartbeat import HeartbeatMonitor
from pbl4.runtime.management_endpoint import ManagementEndpoint
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.context import BatchAssignment, Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RuntimeProcess:
    def __init__(
        self,
        *,
        host: str,
        dtp_port: int,
        management_port: int,
        dataset_manager_url: str,
        checkpoint_dir: Path,
        parameter_manifest: ParameterManifest,
        heartbeat_timeout_seconds: float = 120.0,
    ) -> None:
        self._host = host
        self._dtp_port = dtp_port
        self._dataset_manager_url = dataset_manager_url.rstrip("/")
        self._checkpoint_dir = Path(checkpoint_dir)
        self._manifest = parameter_manifest
        self._heartbeat_timeout = heartbeat_timeout_seconds
        self._lock = threading.Lock()
        self._active: _AttemptRunner | None = None
        self._stopping = threading.Event()
        self._management = ManagementEndpoint(
            host,
            management_port,
            snapshot_provider=self.snapshot,
            command_handler=self._handle_command,
        )

    def run(self) -> None:
        self._management.start()
        logger.info(
            "Runtime ready MCP=%s DTP=%s:%s manifest=%s",
            self._management.bound_address,
            self._host,
            self._dtp_port,
            self._manifest.parameter_manifest_hash,
        )
        try:
            while not self._stopping.wait(0.5):
                pass
        finally:
            with self._lock:
                active = self._active
            if active is not None:
                active.abort()
                active.join(10.0)
            self._management.stop()

    def stop(self) -> None:
        self._stopping.set()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            active = self._active
        if active is None:
            return {
                "runtime_instance_id": self._management.runtime_instance_id,
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
                "strategy_state": {},
                "checkpoint_state": None,
                "latest_checkpoint_id": None,
                "recovery_cursor": {},
                "dataset_build_id": None,
                "dataset_manifest_hash": None,
                "last_runtime_event_seq": 0,
                "management_event_gap_count": 0,
                "captured_at": _now(),
            }
        return active.snapshot(self._management.runtime_instance_id)

    def _handle_command(self, command_type: str, payload: dict[str, object]) -> dict[str, object]:
        command_id = str(payload["command_id"])
        attempt_id = str(payload["attempt_id"])
        if command_type == "START_ATTEMPT":
            with self._lock:
                if self._active is not None and not self._active.terminal:
                    return self._result(
                        command_id,
                        attempt_id,
                        "REJECTED",
                        "ACTIVE_ATTEMPT_EXISTS",
                        "Runtime already owns an active Attempt.",
                    )
                runner = _AttemptRunner(
                    process=self,
                    payload=payload,
                    management=self._management,
                )
                self._active = runner
                runner.start()
            return self._result(
                command_id,
                attempt_id,
                "ACCEPTED",
                "START_ACCEPTED",
                "Attempt accepted and DTP provisioning started.",
            )
        with self._lock:
            active = self._active
        if active is None or active.attempt_id != attempt_id:
            return self._result(
                command_id,
                attempt_id,
                "REJECTED",
                "ATTEMPT_NOT_ACTIVE",
                "Attempt is not active on this Runtime.",
            )
        if command_type == "ABORT_ATTEMPT":
            active.abort()
            return self._result(command_id, attempt_id, "SUCCEEDED", "ABORTED", "Abort requested.")
        if command_type == "REQUEST_CHECKPOINT":
            return self._result(
                command_id,
                attempt_id,
                "DEFERRED",
                "CHECKPOINT_POLICY_OWNS_CADENCE",
                "V1 creates a blocking checkpoint after every synchronized update.",
            )
        raise ValueError(f"Unsupported Runtime command {command_type}")

    @staticmethod
    def _result(
        command_id: str, attempt_id: str, status: str, code: str, message: str
    ) -> dict[str, object]:
        return {
            "command_id": command_id,
            "target_type": "ATTEMPT",
            "target_id": attempt_id,
            "status": status,
            "result_code": code,
            "message": message,
            "attempt_id": attempt_id,
            "effective_at": _now(),
        }


class _AttemptRunner:
    def __init__(
        self,
        *,
        process: RuntimeProcess,
        payload: dict[str, object],
        management: ManagementEndpoint,
    ) -> None:
        self._process = process
        self._payload = payload
        self._management = management
        self.job_id = str(payload["job_id"])
        self.attempt_id = str(payload["attempt_id"])
        self._state = "CREATED"
        self._state_lock = threading.Lock()
        self._abort = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"pbl4-attempt-{self.attempt_id}", daemon=True
        )
        self._server: ParameterServer | None = None
        self._registry: WorkerRegistry | None = None
        self._coordinator: Coordinator | None = None
        self._events: EventEmitter | None = None
        self._dataset: PinnedDatasetManifest | None = None
        self._step_done = threading.Event()
        self._model_init = threading.Event()
        self._model_init_transfer: CompletedTensorTransfer | None = None
        self._failure: str | None = None
        self._final_workers: tuple[dict[str, object], ...] = ()
        self._event_thread = threading.Thread(
            target=self._forward_events,
            name=f"pbl4-events-{self.attempt_id}",
            daemon=True,
        )

    @property
    def terminal(self) -> bool:
        with self._state_lock:
            return self._state in {"COMPLETED", "FAILED", "ABORTED"}

    def start(self) -> None:
        self._thread.start()
        self._event_thread.start()

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)

    def abort(self) -> None:
        self._abort.set()
        coordinator = self._coordinator
        if coordinator is not None:
            coordinator.abort()

    def _set_state(self, state: str) -> None:
        with self._state_lock:
            self._state = state

    def _run(self) -> None:
        try:
            contract = self._validate_contract()
            expected_workers = int(contract["synchronization"]["expected_workers"])
            registry = WorkerRegistry(self.attempt_id, expected_workers)
            self._registry = registry
            server = ParameterServer(
                self._process._host,
                self._process._dtp_port,
                attempt_id=self.attempt_id,
                job_id=self.job_id,
                expected_workers=expected_workers,
                manifest=self._process._manifest,
                registry=registry,
                gradient_handler=self._on_gradient,
                parameter_applied_handler=self._on_parameter_applied,
                model_init_handler=self._on_model_init,
                disconnect_handler=self._on_disconnect,
                heartbeat_timeout_ms=int(self._process._heartbeat_timeout * 1000),
            )
            self._server = server
            server.start()
            self._set_state("WAITING_WORKERS")

            dataset_contract = contract["dataset"]
            resolved = self._management.resolve_dataset_build(
                {
                    "job_id": self.job_id,
                    "attempt_id": self.attempt_id,
                    "dataset_build_id": dataset_contract["dataset_build_id"],
                    "expected_dataset_manifest_hash": dataset_contract["dataset_manifest_hash"],
                }
            )
            dataset = DatasetManifestClient(self._process._dataset_manager_url).pin(
                dataset_contract["dataset_build_id"],
                dataset_contract["dataset_manifest_hash"],
            )
            self._dataset = dataset
            if dataset.shard_count != expected_workers:
                raise ValueError("Pinned Dataset Manifest shard count differs from membership")
            shard_manifests = self._fetch_shard_manifests(dataset)

            if not server.wait_for_workers(expected_workers, 180.0):
                raise TimeoutError("Timed out waiting for full DTP worker membership")
            self._set_state("PROVISIONING")
            artifact_base_url = str(resolved["artifact_base_url"])
            for worker_id in server.worker_ids():
                server.send_dataset_assignment(
                    worker_id,
                    DatasetAssignment.from_dict(
                        {
                            "dataset_build_id": dataset.dataset_build_id,
                            "dataset_manifest_hash": dataset.dataset_manifest_hash,
                            "shard_id": worker_id,
                            "artifact_base_url": artifact_base_url,
                            "root_manifest_path": "manifest.json",
                            "expected_shard_count": expected_workers,
                            "profile": dataset_contract.get(
                                "profile", "CNN_IMAGE_CLASSIFICATION_V1"
                            ),
                        }
                    ),
                )
            self._wait_for(
                lambda: (
                    len(registry.snapshot()) == expected_workers
                    and all(item.state == SessionState.SHARD_READY for item in registry.snapshot())
                ),
                600.0,
                "verified worker shards",
            )
            self._set_state("INITIALIZING")
            if not server.wait_for_manifests(120.0):
                raise TimeoutError("Timed out waiting for Parameter Manifests")
            if not self._model_init.wait(120.0):
                raise TimeoutError("Timed out waiting for worker-0 canonical initialization")
            transfer = self._model_init_transfer
            if transfer is None:
                raise ValueError("Canonical initialization transfer is unavailable")
            initial = np.frombuffer(transfer.data, dtype="<f4").astype(np.float32, copy=True)
            if (
                initial.size != self._process._manifest.total_numel
                or not np.isfinite(initial).all()
            ):
                raise ValueError("Canonical initialization tensor is invalid")

            members = tuple(Member(item.worker_id, item.session_id) for item in registry.snapshot())
            context = StrategyContext(
                self.job_id,
                self.attempt_id,
                str(self._payload["contract_hash"]),
                str(contract["synchronization"]["training_strategy"]),
                expected_workers,
                str(contract["update_policy"]["type"]),
                dataset.dataset_build_id,
                dataset.dataset_manifest_hash,
                self._process._manifest.parameter_manifest_hash,
                int(contract["protocols"]["dtp_version"]),
                self._process._manifest.total_numel,
                members,
            )
            schedule = self._schedule(shard_manifests)
            model = CanonicalModel(initial, 0, self._process._manifest.parameter_manifest_hash)
            events = EventEmitter(self.attempt_id, self.job_id)
            self._events = events
            checkpoint_template = CheckpointSnapshot(
                checkpoint_id="pending",
                checkpoint_schema_version=int(contract["checkpoint_policy"]["schema_version"]),
                job_id=self.job_id,
                created_by_attempt_id=self.attempt_id,
                contract_hash=str(self._payload["contract_hash"]),
                checkpoint_policy=str(contract["checkpoint_policy"]["type"]),
                checkpoint_policy_version=1,
                training_strategy=str(contract["synchronization"]["training_strategy"]),
                dataset_build_id=dataset.dataset_build_id,
                dataset_manifest_hash=dataset.dataset_manifest_hash,
                model_id=str(contract["model"]["model_id"]),
                model_profile=str(contract["model"]["profile"]),
                source_operation_id=0,
                source_step_id=None,
                optimizer=str(contract["update_policy"]["type"]),
                created_at=_now(),
                model=ModelSnapshot(
                    0, self._process._manifest.parameter_manifest_hash, initial.tobytes()
                ),
                recovery_cursor=RecoveryCursor(0, 0),
            )
            coordinator = Coordinator(
                context,
                registry,
                create_policy(context),
                model,
                UpdateEngine(
                    model,
                    self.attempt_id,
                    str(contract["update_policy"]["type"]),
                    float(contract["training"]["learning_rate"]),
                ),
                BatchScheduler(
                    schedule,
                    int(contract["training"]["training_seed"]),
                    int(contract["training"]["epochs"]),
                ),
                CheckpointPolicy(str(contract["checkpoint_policy"]["type"])),
                CheckpointManager(
                    self._process._checkpoint_dir / self.attempt_id,
                    CheckpointV1Serializer(),
                ),
                checkpoint_template,
                events,
            )
            self._coordinator = coordinator
            coordinator.advance_initialization()
            coordinator.advance_initialization()
            coordinator.advance_initialization()
            server.mark_model_syncing()
            server.broadcast_parameters(
                initial.tobytes(),
                operation_id=0,
                source_step_id=0,
                model_version=0,
                initialization=True,
            )
            self._wait_for(
                lambda: all(item.state == SessionState.READY for item in registry.snapshot()),
                120.0,
                "model-ready workers",
            )
            coordinator.advance_initialization()
            self._set_state("RUNNING")
            self._training_loop(coordinator, server)
            self._final_workers = server.worker_snapshots()
            final_state = str(coordinator.snapshot()["state"])
            if final_state != "COMPLETED":
                server.send_stop(
                    attempt_state=final_state,
                    reason_code="ATTEMPT_ABORTED",
                    reason="Attempt stopped before schedule completion.",
                )
                return
            server.send_stop(
                attempt_state="COMPLETED",
                reason_code="ATTEMPT_COMPLETED",
                reason="All scheduled Strict BSP steps committed.",
            )
            time.sleep(1.0)
        except Exception as exc:
            logger.exception("Attempt %s failed", self.attempt_id)
            self._failure = str(exc)
            coordinator = self._coordinator
            if coordinator is not None and coordinator.snapshot()["state"] not in {
                "FAILED",
                "ABORTED",
            }:
                if self._abort.is_set():
                    coordinator.abort()
                else:
                    coordinator.fail(self._failure or "Runtime failure")
            self._set_state("ABORTED" if self._abort.is_set() else "FAILED")
            server = self._server
            if server is not None:
                self._final_workers = server.worker_snapshots()
                server.send_stop(
                    attempt_state=self._state,
                    reason_code="ATTEMPT_FAILED",
                    reason=self._failure or "Runtime failure",
                )
        finally:
            if self._server is not None:
                self._server.stop()
            coordinator = self._coordinator
            if coordinator is not None:
                self._set_state(str(coordinator.snapshot()["state"]))

    def _training_loop(self, coordinator: Coordinator, server: ParameterServer) -> None:
        monitor = HeartbeatMonitor(self._registry, self._process._heartbeat_timeout)
        while not self._abort.is_set():
            try:
                operation = coordinator.open_step()
            except StopIteration:
                coordinator.complete()
                self._set_state("COMPLETED")
                return
            self._step_done.clear()
            for assignment in operation.assignments:
                server.send_step_start(
                    assignment.worker_id,
                    operation.operation_id,
                    StepStart.from_dict(
                        {
                            "attempt_id": self.attempt_id,
                            "epoch": operation.epoch,
                            "step_id": operation.step_id,
                            "batch_ordinal": assignment.batch_ordinal,
                            "model_version": operation.input_model_version,
                            "shard_id": assignment.shard_id,
                            "batch_id": assignment.batch_id,
                            "expected_sample_count": assignment.sample_count,
                            "training_strategy": "strict_bsp",
                            "parameter_manifest_hash": (
                                self._process._manifest.parameter_manifest_hash
                            ),
                        }
                    ),
                )
            deadline = time.monotonic() + 1800.0
            while not self._step_done.wait(0.2):
                if self._abort.is_set():
                    coordinator.abort()
                    return
                for session in monitor.expired(time.monotonic()):
                    coordinator.heartbeat_timeout(
                        session.worker_id, session.session_id, session.last_heartbeat_at
                    )
                snapshot = coordinator.snapshot()
                if snapshot["state"] in {"FAILED", "ABORTED"}:
                    raise RuntimeError(f"Coordinator entered {snapshot['state']}")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for synchronized Step commit")

    def _on_model_init(self, transfer: CompletedTensorTransfer) -> None:
        if transfer.identity.worker_id != 0 or self._model_init_transfer is not None:
            raise ValueError("Invalid or duplicate worker-0 initialization")
        self._model_init_transfer = transfer
        self._model_init.set()

    def _on_gradient(self, contribution) -> None:
        coordinator = self._coordinator
        server = self._server
        if coordinator is None or server is None:
            raise ValueError("Gradient arrived before Runtime initialization")
        _, published = coordinator.admit(contribution)
        if published is not None:
            server.broadcast_parameters(
                published._parameters,
                operation_id=contribution.operation_id,
                source_step_id=contribution.step_id,
                model_version=published.model_version,
            )

    def _on_parameter_applied(self, ack) -> None:
        coordinator = self._coordinator
        if coordinator is None:
            raise ValueError("Parameter ACK arrived before Runtime initialization")
        if coordinator.parameter_applied(ack):
            if coordinator.checkpoint() is None:
                raise RuntimeError("Blocking checkpoint did not complete")
            self._step_done.set()

    def _on_disconnect(self, worker_id: int, session_id: int) -> None:
        coordinator = self._coordinator
        if coordinator is not None and not self.terminal:
            coordinator.worker_failed(worker_id, session_id)

    def _forward_events(self) -> None:
        while not self.terminal or (
            self._events is not None and self._events.snapshot()["queued_event_count"]
        ):
            events = self._events
            if events is None or not self._management.backend_connected:
                time.sleep(0.1)
                continue
            for event in events.drain():
                self._management.send_runtime_event(
                    {
                        "attempt_id": event.attempt_id,
                        "job_id": event.job_id,
                        "runtime_event_seq": event.runtime_event_seq,
                        "event_type": event.event_type,
                        "event_schema_version": event.event_schema_version,
                        "occurred_at": event.occurred_at,
                        "source_component": event.source_component,
                        "severity": event.severity,
                        "details": event.details,
                    }
                )
            time.sleep(0.05)

    def snapshot(self, runtime_instance_id: str) -> dict[str, object]:
        coordinator = self._coordinator
        if coordinator is not None:
            current = coordinator.snapshot()
            state = str(current["state"])
            raw_strategy = current.get("strategy_state")
            if isinstance(raw_strategy, dict):
                strategy_state = {
                    k: list(v) if isinstance(v, (list, tuple)) else v
                    for k, v in raw_strategy.items()
                }
            else:
                strategy_state = {}
            epoch = int(current["epoch"])
            ordinal = int(current["next_batch_ordinal"])
            operation = current["current_operation_id"]
            model_version = int(current["model_version"])
            checkpoint_state = current["checkpoint_state"]
            latest_checkpoint = current["latest_checkpoint_id"]
            last_seq = int(current["last_runtime_event_seq"])
            gap_count = int(current["dropped_event_count"])
        else:
            with self._state_lock:
                state = self._state
            strategy_state = {}
            epoch = 0
            ordinal = 0
            operation = None
            model_version = 0
            checkpoint_state = None
            latest_checkpoint = None
            last_seq = 0
            gap_count = 0
        server = self._server
        raw_workers = server.worker_snapshots() if server is not None else self._final_workers
        captured = _now()
        workers = [
            {
                "worker_id": item["worker_id"],
                "session_id": str(item["session_id"]),
                "node_label": item["node_label"],
                "state": item["state"],
                "protocol_version": item["protocol_version"],
                "connected_at": item["connected_at"],
                "last_heartbeat_at": item["last_heartbeat_at"],
                "shard_id": item["shard_id"],
                "local_model_version": item["local_model_version"],
            }
            for item in raw_workers
        ]
        contract = self._payload["resolved_contract"]
        dataset = contract["dataset"]
        return {
            "runtime_instance_id": runtime_instance_id,
            "active_job_id": self.job_id,
            "active_attempt_id": self.attempt_id,
            "attempt_state": state,
            "training_strategy": contract["synchronization"]["training_strategy"],
            "checkpoint_policy": contract["checkpoint_policy"]["type"],
            "epoch": epoch,
            "current_operation_id": operation,
            "current_batch_ordinal": ordinal,
            "model_version": model_version,
            "workers": workers,
            "strategy_state": strategy_state,
            "checkpoint_state": checkpoint_state,
            "latest_checkpoint_id": latest_checkpoint,
            "recovery_cursor": {"epoch": epoch, "next_batch_ordinal": ordinal},
            "dataset_build_id": dataset["dataset_build_id"],
            "dataset_manifest_hash": dataset["dataset_manifest_hash"],
            "last_runtime_event_seq": last_seq,
            "management_event_gap_count": gap_count,
            "captured_at": captured,
        }

    def _validate_contract(self) -> dict[str, object]:
        contract = self._payload.get("resolved_contract")
        if not isinstance(contract, dict):
            raise ValueError("START_ATTEMPT lacks a resolved contract")
        model = contract.get("model")
        sync = contract.get("synchronization")
        checkpoint = contract.get("checkpoint_policy")
        update = contract.get("update_policy")
        protocols = contract.get("protocols")
        if (
            self._payload.get("execution_mode") not in {"FRESH", "RETRY_FROM_START"}
            or not isinstance(model, dict)
            or model.get("model_id") != "resnet18_groupnorm"
            or model.get("profile") != "RESNET18_GROUPNORM_V1"
            or model.get("parameter_manifest_hash")
            != self._process._manifest.parameter_manifest_hash
            or not isinstance(sync, dict)
            or sync.get("training_strategy") != "strict_bsp"
            or type(sync.get("expected_workers")) is not int
            or sync["expected_workers"] <= 0
            or not isinstance(checkpoint, dict)
            or checkpoint.get("type") != "after_each_model_update_blocking"
            or checkpoint.get("schema_version") != 1
            or not isinstance(update, dict)
            or update.get("type") not in {"plain_sgd", "plain_sgd_without_momentum"}
            or not isinstance(protocols, dict)
            or protocols.get("dtp_version") != 1
            or protocols.get("mcp_version") != 1
        ):
            raise ValueError("START_ATTEMPT contract is incompatible with Runtime V1")
        return contract

    def _fetch_shard_manifests(self, root: PinnedDatasetManifest) -> tuple[dict[str, object], ...]:
        manifests = []
        for reference in root.value["shards"]:
            shard_id = int(reference["shard_id"])
            url = (
                f"{self._process._dataset_manager_url}/artifacts/v1/dataset-builds/"
                f"{root.dataset_build_id}/shards/{shard_id}/manifest.json"
            )
            with urllib.request.urlopen(url, timeout=30.0) as response:
                content = response.read(4 * 1024 * 1024 + 1)
            if (
                len(content) > 4 * 1024 * 1024
                or sha256_bytes(content) != reference["shard_manifest_sha256"]
            ):
                raise ValueError("Shard Manifest hash/size verification failed")
            value = json.loads(content)
            if (
                not isinstance(value, dict)
                or canonical_json_bytes(value) != content
                or value.get("dataset_build_id") != root.dataset_build_id
                or value.get("shard_id") != shard_id
                or not isinstance(value.get("batches"), list)
            ):
                raise ValueError("Shard Manifest identity/schema verification failed")
            manifests.append(value)
        counts = {int(value["batch_count"]) for value in manifests}
        if len(counts) != 1 or counts != {root.batch_count_per_shard}:
            raise ValueError("All V1 shards must expose the pinned batch count")
        return tuple(manifests)

    @staticmethod
    def _schedule(manifests: tuple[dict[str, object], ...]) -> tuple[BatchAssignment, ...]:
        assignments = []
        for manifest in manifests:
            worker_id = int(manifest["shard_id"])
            for entry in manifest["batches"]:
                assignments.append(
                    BatchAssignment(
                        worker_id,
                        worker_id,
                        int(entry["batch_id"]),
                        int(entry["batch_id"]),
                        int(entry["sample_count"]),
                    )
                )
        return tuple(assignments)

    def _wait_for(self, predicate, timeout: float, description: str) -> None:
        deadline = time.monotonic() + timeout
        while not predicate():
            if self._abort.is_set():
                raise RuntimeError("Attempt aborted")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {description}")
            time.sleep(0.05)


def load_parameter_manifest(path: Path) -> ParameterManifest:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest = ParameterManifest.from_dict(value)
    if re.fullmatch(r"[0-9a-f]{64}", manifest.parameter_manifest_hash) is None:
        raise ValueError("Parameter Manifest hash is invalid")
    return manifest
