from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
import torch
from torch.nn import functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.small_cnn import SmallCNN
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.protocol.messages import DatasetAssignment, ShardReady, StepStart, Stop
from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.context import BatchAssignment, Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from pbl4.worker.worker_client import WorkerClient
from tests.test_checkpoint_mechanics import TestOnlySerializer


def _adapter(seed: int = 123) -> PyTorchAdapter:
    torch.manual_seed(seed)
    return PyTorchAdapter(SmallCNN(), functional.cross_entropy, local_gradient_reduction="mean")


def _flatten(bundle: TensorBundle) -> bytes:
    return (
        np.concatenate([value.reshape(-1) for value in bundle.tensors])
        .astype("<f4", copy=False)
        .tobytes()
    )


def _bundle(raw: bytes, adapter: PyTorchAdapter) -> TensorBundle:
    flat = np.frombuffer(raw, dtype="<f4")
    tensors = tuple(
        flat[entry.byte_offset // 4 : (entry.byte_offset + entry.byte_length) // 4]
        .reshape(entry.shape)
        .astype(np.float32, copy=True)
        for entry in adapter.manifest.parameters
    )
    return TensorBundle(adapter.manifest.parameter_manifest_hash, tensors)


@dataclass(frozen=True)
class _Key:
    shard_id: int


class _MemoryShard:
    def __init__(self, shard_id: int, batches: dict[int, tuple[np.ndarray, np.ndarray]]) -> None:
        self.key = _Key(shard_id)
        self._batches = batches

    def load_batch(self, batch_id: int):
        x, y = self._batches[batch_id]
        return x, y, tuple(f"{self.key.shard_id}:{batch_id}:{i}" for i in range(len(x)))


def _wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for distributed state")
        time.sleep(0.005)


def test_terminal_stop_disconnect_is_clean(caplog) -> None:
    manifest = _adapter().manifest
    registry = WorkerRegistry("attempt-stop", 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id="attempt-stop",
        job_id="job-stop",
        expected_workers=1,
        manifest=manifest,
        registry=registry,
    )
    server.start()
    holder: dict[str, WorkerClient] = {}

    def on_message(message, _operation_id):
        if isinstance(message, Stop):
            holder["client"].disconnect()

    try:
        host, port = server.bound_address or ("", 0)
        client = WorkerClient(
            host, port, node_label="worker-stop", manifest=manifest, message_handler=on_message
        )
        holder["client"] = client
        client.connect()
        assert server.wait_for_workers(1, 3.0)
        server.send_stop(
            attempt_state="COMPLETED",
            reason_code="ATTEMPT_COMPLETED",
            reason="Schedule complete.",
        )
        _wait_until(lambda: server.worker_ids() == ())
        assert not any(
            record.name == "pbl4.transport.tcp_server"
            and "Connection handler failed" in record.getMessage()
            for record in caplog.records
        )
    finally:
        if "client" in holder:
            holder["client"].disconnect()
        server.stop()


def test_three_worker_real_dtp_strict_bsp_numerical_oracle_and_three_steps(tmp_path) -> None:
    counts = (4, 7, 5)
    learning_rate = 0.025
    adapters = [_adapter() for _ in counts]
    manifest = adapters[0].manifest
    assert all(adapter.manifest == manifest for adapter in adapters)
    theta0_bytes = _flatten(adapters[0].export_parameters())
    theta0 = np.frombuffer(theta0_bytes, dtype="<f4").copy()

    batches: list[dict[int, tuple[np.ndarray, np.ndarray]]] = []
    for worker_id, count in enumerate(counts):
        worker_batches = {}
        for batch_id in range(3):
            rng = np.random.default_rng(10_000 + worker_id * 100 + batch_id)
            worker_batches[batch_id] = (
                rng.normal(size=(count, 3, 2, 2)).astype(np.float32),
                rng.integers(0, 10, size=count, dtype=np.int64),
            )
        batches.append(worker_batches)

    registry = WorkerRegistry("attempt-network", len(counts))
    init_received = threading.Event()
    init_transfer: dict[str, bytes] = {}
    coordinator_holder: dict[str, Coordinator] = {}
    published_versions: list[int] = []
    contribution_versions: list[int] = []
    checkpoint_complete = threading.Event()

    def on_model_init(transfer) -> None:
        assert transfer.identity.worker_id == 0
        assert transfer.metadata["transfer_purpose"] == "model_init"
        init_transfer["data"] = transfer.data
        init_received.set()

    def on_gradient(contribution) -> None:
        coordinator = coordinator_holder["value"]
        _, published = coordinator.admit(contribution)
        contribution_versions.append(coordinator.snapshot()["model_version"])
        if published is not None:
            published_versions.append(published.model_version)
            server.broadcast_parameters(
                published._parameters,
                operation_id=contribution.operation_id,
                source_step_id=contribution.step_id,
                model_version=published.model_version,
            )

    def on_parameter_applied(ack) -> None:
        coordinator = coordinator_holder["value"]
        if coordinator.parameter_applied(ack):
            assert coordinator.checkpoint() is not None
            checkpoint_complete.set()

    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id="attempt-network",
        job_id="job-network",
        expected_workers=len(counts),
        manifest=manifest,
        registry=registry,
        gradient_handler=on_gradient,
        parameter_applied_handler=on_parameter_applied,
        model_init_handler=on_model_init,
        max_tensor_chunk_bytes=97,
    )
    server.start()
    clients: list[WorkerClient] = []
    assignment_events = [threading.Event() for _ in counts]
    pending: list[StepAssignment | None] = [None for _ in counts]
    loops = [TrainingLoop(adapters[w], _MemoryShard(w, batches[w]), 0) for w in range(3)]

    try:
        host, port = server.bound_address or ("", 0)
        for worker_id in range(3):
            holder: dict[str, WorkerClient] = {}

            def on_message(message, operation_id, *, index=worker_id, client_holder=holder):
                if isinstance(message, DatasetAssignment):
                    assignment_events[index].set()
                    return
                if isinstance(message, StepStart):
                    assignment = StepAssignment(
                        attempt_id=message.attempt_id,
                        session_id=client_holder["client"].session_id,
                        worker_id=client_holder["client"].worker_id,
                        operation_id=operation_id,
                        step_id=message.step_id,
                        input_model_version=message.model_version,
                        shard_id=message.shard_id,
                        batch_id=message.batch_id,
                        batch_ordinal=message.batch_ordinal,
                        expected_sample_count=message.expected_sample_count,
                    )
                    pending[index] = assignment
                    computed = loops[index].compute(assignment)
                    client_holder["client"].send_gradient(
                        _flatten(computed.local_gradient.bundle),
                        operation_id=operation_id,
                        model_version=assignment.input_model_version,
                        shard_id=assignment.shard_id,
                        batch_id=assignment.batch_id,
                        batch_ordinal=assignment.batch_ordinal,
                        sample_count=computed.local_gradient.sample_count,
                        tensor_id=index,
                        loss=computed.local_gradient.loss,
                    )

            def on_parameters(transfer, *, index=worker_id, client_holder=holder):
                target_version = int(transfer.metadata["model_version_out"])
                values = _bundle(transfer.data, adapters[index])
                if target_version == 0:
                    adapters[index].apply_parameters(values)
                    client_holder["client"].send_ready(
                        model_version=0,
                        dataset_build_id="build-network",
                        shard_id=index,
                    )
                    return
                assignment = pending[index]
                assert assignment is not None
                eligibility = loops[index].apply_parameters(assignment, target_version, values)
                assert loops[index].consume_parameter_applied() == eligibility
                pending[index] = None
                client_holder["client"].send_parameter_applied(
                    operation_id=eligibility.operation_id,
                    source_step_id=eligibility.step_id,
                    model_version=eligibility.model_version,
                )

            client = WorkerClient(
                host,
                port,
                node_label=f"worker-node-{worker_id}",
                manifest=manifest,
                message_handler=on_message,
                parameter_handler=on_parameters,
            )
            holder["client"] = client
            client.connect()
            clients.append(client)

        assert server.wait_for_workers(3, 3.0)
        assert [client.worker_id for client in clients] == [0, 1, 2]
        session_snapshots = server.worker_snapshots()
        assert all(item["protocol_version"] == 1 for item in session_snapshots)
        assert all(item["connected_at"] for item in session_snapshots)
        assert all(item["last_heartbeat_at"] for item in session_snapshots)

        for worker_id, client in enumerate(clients):
            server.send_dataset_assignment(
                worker_id,
                DatasetAssignment.from_dict(
                    {
                        "dataset_build_id": "build-network",
                        "dataset_manifest_hash": "d" * 64,
                        "shard_id": worker_id,
                        "artifact_base_url": "http://dataset-manager.invalid/artifacts",
                        "root_manifest_path": "manifest.json",
                        "expected_shard_count": 3,
                        "profile": "CNN_IMAGE_CLASSIFICATION_V1",
                    }
                ),
            )
            assert assignment_events[worker_id].wait(2.0)
            client.send_shard_ready(
                ShardReady.from_dict(
                    {
                        "dataset_build_id": "build-network",
                        "dataset_manifest_hash": "d" * 64,
                        "shard_id": worker_id,
                        "shard_manifest_hash": str(worker_id + 1) * 64,
                        "verified_batch_count": 3,
                        "verified_sample_count": counts[worker_id] * 3,
                        "cache_key": f"cache-{worker_id}",
                        "completed_at": "2026-09-09T00:00:00+00:00",
                    }
                )
            )
        _wait_until(lambda: all(s.state == SessionState.SHARD_READY for s in registry.snapshot()))

        for client in clients:
            client.send_model_manifest()
        assert server.wait_for_manifests(3.0)
        clients[0].send_model_init(theta0_bytes, initialization_seed=123)
        assert init_received.wait(3.0)
        assert init_transfer["data"] == theta0_bytes

        model = CanonicalModel(
            np.frombuffer(init_transfer["data"], dtype="<f4").copy(),
            0,
            manifest.parameter_manifest_hash,
        )
        members = tuple(
            Member(session.worker_id, session.session_id) for session in registry.snapshot()
        )
        context = StrategyContext(
            "job-network",
            "attempt-network",
            "contract-network",
            "strict_bsp",
            3,
            "plain_sgd",
            "build-network",
            "d" * 64,
            manifest.parameter_manifest_hash,
            1,
            manifest.total_numel,
            members,
        )
        schedule = tuple(
            BatchAssignment(worker, worker, batch_id, batch_id, counts[worker])
            for worker in range(3)
            for batch_id in range(3)
        )
        checkpoint_context = CheckpointSnapshot(
            "pending",
            1,
            "job-network",
            "attempt-network",
            "contract-network",
            "after_each_model_update_blocking",
            1,
            "strict_bsp",
            "build-network",
            "d" * 64,
            "small_cnn",
            "TEST_ONLY",
            0,
            None,
            "plain_sgd",
            "2026-09-09T00:00:00+00:00",
            ModelSnapshot(0, manifest.parameter_manifest_hash, init_transfer["data"]),
            RecoveryCursor(0, 0),
        )
        coordinator = Coordinator(
            context,
            registry,
            create_policy(context),
            model,
            UpdateEngine(model, "attempt-network", "plain_sgd", learning_rate),
            BatchScheduler(schedule, 42, 1),
            CheckpointPolicy(),
            CheckpointManager(tmp_path / "checkpoints", TestOnlySerializer()),
            checkpoint_context,
            EventEmitter("attempt-network", "job-network"),
        )
        coordinator_holder["value"] = coordinator
        assert coordinator.advance_initialization() == "WAITING_WORKERS"
        assert coordinator.advance_initialization() == "PROVISIONING"
        assert coordinator.advance_initialization() == "INITIALIZING"
        server.mark_model_syncing()
        server.broadcast_parameters(
            init_transfer["data"],
            operation_id=1,
            source_step_id=0,
            model_version=0,
            initialization=True,
        )
        _wait_until(lambda: all(s.state == SessionState.READY for s in registry.snapshot()))
        assert coordinator.advance_initialization() == "RUNNING"

        first_reference: tuple[np.ndarray, np.ndarray] | None = None
        for expected_step in range(3):
            checkpoint_complete.clear()
            operation = coordinator.open_step()
            assert operation.step_id == expected_step
            if expected_step == 0:
                selected = [batches[a.worker_id][a.batch_id] for a in operation.assignments]
                ref_adapter = _adapter()
                reference = ref_adapter.compute_loss_and_gradients(
                    np.concatenate([item[0] for item in selected]),
                    np.concatenate([item[1] for item in selected]),
                )
                first_reference = (
                    np.frombuffer(_flatten(reference.bundle), dtype="<f4").copy(),
                    theta0
                    - np.float32(learning_rate)
                    * np.frombuffer(_flatten(reference.bundle), dtype="<f4"),
                )
            for assignment in operation.assignments:
                server.send_step_start(
                    assignment.worker_id,
                    operation.operation_id,
                    StepStart.from_dict(
                        {
                            "attempt_id": "attempt-network",
                            "epoch": operation.epoch,
                            "step_id": operation.step_id,
                            "batch_ordinal": assignment.batch_ordinal,
                            "model_version": operation.input_model_version,
                            "shard_id": assignment.shard_id,
                            "batch_id": assignment.batch_id,
                            "expected_sample_count": assignment.sample_count,
                            "training_strategy": "strict_bsp",
                            "parameter_manifest_hash": manifest.parameter_manifest_hash,
                        }
                    ),
                )
            assert checkpoint_complete.wait(8.0)
            assert coordinator.snapshot()["step_state"] == "COMMITTED"
            if expected_step == 0:
                assert first_reference is not None
                np.testing.assert_allclose(
                    model.snapshot().parameters,
                    first_reference[1],
                    rtol=2e-5,
                    atol=2e-6,
                )
                for adapter in adapters:
                    np.testing.assert_allclose(
                        np.frombuffer(_flatten(adapter.export_parameters()), dtype="<f4"),
                        model.snapshot().parameters,
                        rtol=0,
                        atol=0,
                    )

        assert published_versions == [1, 2, 3]
        assert contribution_versions[0:3].count(0) == 2
        assert contribution_versions[0:3].count(1) == 1
        assert model.snapshot().model_version == 3
        assert all(loop.local_model_version == 3 for loop in loops)
    finally:
        for client in clients:
            client.disconnect()
        server.stop()
