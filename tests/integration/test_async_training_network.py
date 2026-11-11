"""Real production Runtime/Worker flow over TCP and HTTP; tiny model keeps it fast."""

import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import torch
from torch import nn
from torch.nn import functional

from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.async_training import resolve_async_training
from pbl4.common.errors import TransportError
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.process import _AttemptRunner
from pbl4.worker.config import WorkerConfig
from pbl4.worker.process import WorkerProcess
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for async network state")
        time.sleep(0.01)


@pytest.mark.parametrize(
    "case", ["normal", "compute_disconnect", "initialization_disconnect", "missing_ack"]
)
def test_production_async_train_rejoin_checkpoint_resume(tmp_path, monkeypatch, case):
    import pbl4.worker.process as worker_module
    from pbl4.worker.worker_client import WorkerClient

    disconnect = case == "compute_disconnect"
    torch.set_num_threads(1)

    def tiny_model(_model_id, *, initialization_seed, device):
        # Build once per Worker without changing another thread's global RNG state.
        model = nn.Sequential(nn.Flatten(), nn.Linear(12, 10))
        with torch.no_grad():
            for parameter in model.parameters():
                parameter.fill_(0.001)
        return model

    monkeypatch.setattr(worker_module, "build_model", tiny_model)
    manifest = PyTorchAdapter(
        tiny_model("small_cnn", initialization_seed=42, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    ).manifest
    data = create_synthetic_dataset_artifacts(
        tmp_path / "artifacts" / "build", dataset_build_id="build"
    )

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path / "artifacts"))
    )
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{http.server_port}/build"
    contract = {
        "dataset": {
            "dataset_build_id": "build",
            "dataset_manifest_hash": data.dataset_manifest_hash,
            "batch_size": 2,
        },
        "model": {
            "model_id": "small_cnn",
            "profile": "SMALL_CNN_V1",
            "parameter_manifest_hash": manifest.parameter_manifest_hash,
        },
        "training": {"epochs": 4, "learning_rate": 0.001, "training_seed": 42},
        "workload": {"policy": "equal", "work_units_per_step": 2},
        "synchronization": {"training_strategy": "async_sgd", "expected_workers": 2},
        "update_policy": {"type": "plain_sgd"},
        "checkpoint_policy": {
            "type": "periodic",
            "schema_version": 2,
            "policy_version": 1,
            "every_n_epochs": 1,
        },
        "protocols": {"dtp_version": 1, "mcp_version": 1},
        "async_training": resolve_async_training({"staleness_threshold": 0}),
    }
    process = SimpleNamespace(
        _manifest=manifest,
        _manifests={},
        _host="127.0.0.1",
        _dtp_port=0,
        _worker_admission_secret=None,
        _require_worker_admission=False,
        _heartbeat_timeout=10,
        _checkpoint_dir=tmp_path / "checkpoints",
        _dataset_manager_url=origin,
        _event_outbox=EventEmitter("outbox", "job"),
        _stopping=threading.Event(),
    )
    management = SimpleNamespace(
        resolve_dataset_build=lambda _: {
            "artifact_base_url": origin,
            "manifest_uri": origin + "/dataset-manifest.json",
        }
    )
    runner = _AttemptRunner(
        process=process,
        management=management,
        payload={
            "job_id": "job",
            "attempt_id": "attempt",
            "resolved_contract": contract,
            "execution_mode": "FRESH",
            "contract_hash": "contract",
        },
    )
    workers, tasks, outcomes = [], [], []
    original_compute = worker_module.TrainingLoop.compute
    in_compute, release, rejoined = threading.Event(), threading.Event(), threading.Event()
    interrupted = []
    original_ready = WorkerClient.send_ready
    original_ack = WorkerClient.send_parameter_applied

    def send_ready(client, **kwargs):
        if case == "initialization_disconnect" and client.worker_id == 0 and not interrupted:
            interrupted.append(client.session_id)
            assert release.wait(5)
        return original_ready(client, **kwargs)

    def send_ack(client, **kwargs):
        if case == "missing_ack" and client.worker_id == 0 and not interrupted:
            interrupted.append(client.session_id)
            runner._server.fence(0, client.session_id)
            raise TransportError("Injected loss before parameter ACK")
        return original_ack(client, **kwargs)

    monkeypatch.setattr(WorkerClient, "send_ready", send_ready)
    monkeypatch.setattr(WorkerClient, "send_parameter_applied", send_ack)

    def compute(loop, assignment):
        if disconnect and assignment.worker_id == 0 and not in_compute.is_set():
            in_compute.set()
            assert release.wait(5)
        if disconnect and assignment.worker_id == 1 and in_compute.is_set():
            assert rejoined.wait(5)
        if case in {"initialization_disconnect", "missing_ack"} and assignment.worker_id == 1:
            assert rejoined.wait(5)
        return original_compute(loop, assignment)

    monkeypatch.setattr(worker_module.TrainingLoop, "compute", compute)

    def launch_workers(active_runner):
        port = active_runner._server.bound_address[1]
        for index in range(2):
            worker = WorkerProcess(
                WorkerConfig(
                    runtime_port=port,
                    cache_dir=str(tmp_path / f"cache-{index}"),
                    node_label=f"node-{index}",
                    heartbeat_interval_seconds=0.2,
                ),
                initialization_seed=42,
                model_id="small_cnn",
                connect_timeout_seconds=5,
            )
            workers.append(worker)
            task = threading.Thread(target=lambda w=worker: outcomes.append(w.run()), daemon=True)
            tasks.append(task)
            task.start()

    try:
        runner.start()
        wait_until(lambda: runner._server is not None and runner._server.bound_address is not None)
        launch_workers(runner)
        recovery_point = None
        if case == "normal":
            wait_until(
                lambda: (
                    runner._coordinator is not None
                    and runner._coordinator.pool.counts["applied_units"] >= 1
                )
            )
            recovery_point = runner._coordinator.checkpoint()
        if disconnect:
            assert in_compute.wait(8)
            # A verified cache must support rejoin without Dataset Manager/HTTP.
            http.shutdown()
            http.server_close()
            session = runner._registry.snapshot()[0]
            runner._server.fence(session.worker_id, session.session_id)
            release.set()
            wait_until(
                lambda: (
                    runner._registry.snapshot()[0].session_id != session.session_id
                    and runner._registry.snapshot()[0].state == "READY"
                ),
                timeout=5,
            )
            rejoined.set()
        if case in {"initialization_disconnect", "missing_ack"}:
            wait_until(lambda: bool(interrupted))
            runner._server.fence(0, interrupted[0])
            release.set()
            wait_until(
                lambda: (
                    runner._registry.snapshot()[0].session_id != interrupted[0]
                    and runner._registry.snapshot()[0].state == "READY"
                ),
                timeout=5,
            )
            rejoined.set()
        runner.join(12)
        assert runner.wait_closed(1), runner.snapshot("test")
        state = runner.snapshot("test")
        assert state["attempt_state"] == "COMPLETED", runner._failure
        progress = state["strategy_state"]
        assert progress["processed_units"] == 16
        assert progress["applied_units"] + progress["dropped_units"] == 16
        summaries = [
            e.details for e in runner._events.peek() if e.event_type == "epoch.metrics.finalized"
        ]
        assert sorted(e["epoch_index"] for e in summaries) == [0, 1, 2, 3]
        assert all(e["sample_count"] > 0 for e in summaries)
        assert all(e["training_loss"] is not None for e in summaries)
        assert all(0 <= e["training_accuracy"] <= 100 for e in summaries)
        assert progress["epoch_progress"] is None
        latest = runner._coordinator._latest
        assert latest.snapshot.async_progress is not None
        assert runner._coordinator._checkpoints.verify(latest) == latest.snapshot
        if recovery_point is not None:
            for task in tasks:
                task.join(2)
            assert all(outcomes)
            source = recovery_point
            runner = _AttemptRunner(
                process=process,
                management=management,
                payload={
                    "job_id": "job",
                    "attempt_id": "attempt-resume",
                    "resolved_contract": contract,
                    "execution_mode": "RESUME",
                    "contract_hash": "contract",
                    "resume_checkpoint": {
                        "checkpoint_id": source.snapshot.checkpoint_id,
                        "source_attempt_id": "attempt",
                        "model_sha256": source.model_sha256,
                        "metadata_sha256": source.metadata_sha256,
                    },
                },
            )
            runner.start()
            wait_until(
                lambda: runner._server is not None and runner._server.bound_address is not None
            )
            launch_workers(runner)
            runner.join(12)
            assert runner.wait_closed(1)
            assert runner.snapshot("test")["attempt_state"] == "COMPLETED", runner._failure
            assert (
                runner._coordinator.pool.counts["applied_units"]
                + runner._coordinator.pool.counts["dropped_units"]
                == 16
            )
            assert (
                runner._coordinator._model.snapshot().model_version
                == runner._coordinator.pool.counts["applied_units"]
            )
    finally:
        release.set()
        rejoined.set()
        runner.abort()
        if runner._server:
            runner._server.stop()
        for worker in workers:
            worker._stop.set()
            worker._client.disconnect()
        for task in tasks:
            task.join(2)
        http.shutdown()
        http.server_close()


def test_async_managed_worker_crash_respawn_rejoins_and_completes(tmp_path, monkeypatch):
    """A respawned managed Worker process reuses deterministic client_instance_id to rejoin."""
    import uuid

    import pbl4.worker.process as worker_module
    from pbl4.common.worker_admission import issue_worker_join_token

    torch.set_num_threads(1)

    def tiny_model(_model_id, *, initialization_seed, device):
        model = nn.Sequential(nn.Flatten(), nn.Linear(12, 10))
        with torch.no_grad():
            for parameter in model.parameters():
                parameter.fill_(0.001)
        return model

    monkeypatch.setattr(worker_module, "build_model", tiny_model)
    manifest = PyTorchAdapter(
        tiny_model("small_cnn", initialization_seed=42, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    ).manifest
    data = create_synthetic_dataset_artifacts(
        tmp_path / "artifacts" / "build", dataset_build_id="build"
    )

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path / "artifacts"))
    )
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{http.server_port}/build"
    secret = "test-admission-secret"
    contract = {
        "dataset": {
            "dataset_build_id": "build",
            "dataset_manifest_hash": data.dataset_manifest_hash,
            "batch_size": 2,
        },
        "model": {
            "model_id": "small_cnn",
            "profile": "SMALL_CNN_V1",
            "parameter_manifest_hash": manifest.parameter_manifest_hash,
        },
        "training": {"epochs": 4, "learning_rate": 0.001, "training_seed": 42},
        "workload": {"policy": "equal", "work_units_per_step": 2},
        "synchronization": {"training_strategy": "async_sgd", "expected_workers": 2},
        "update_policy": {"type": "plain_sgd"},
        "checkpoint_policy": {
            "type": "periodic",
            "schema_version": 2,
            "policy_version": 1,
            "every_n_epochs": 1,
        },
        "protocols": {"dtp_version": 1, "mcp_version": 1},
        "async_training": resolve_async_training({"staleness_threshold": 2}),
    }
    process = SimpleNamespace(
        _manifest=manifest,
        _manifests={},
        _host="127.0.0.1",
        _dtp_port=0,
        _worker_admission_secret=secret,
        _require_worker_admission=True,
        _heartbeat_timeout=10,
        _checkpoint_dir=tmp_path / "checkpoints",
        _dataset_manager_url=origin,
        _event_outbox=EventEmitter("outbox", "job"),
        _stopping=threading.Event(),
    )
    management = SimpleNamespace(
        resolve_dataset_build=lambda _: {
            "artifact_base_url": origin,
            "manifest_uri": origin + "/dataset-manifest.json",
        }
    )
    runner = _AttemptRunner(
        process=process,
        management=management,
        payload={
            "job_id": "job",
            "attempt_id": "attempt",
            "resolved_contract": contract,
            "execution_mode": "FRESH",
            "contract_hash": "contract",
        },
    )
    workers, tasks, outcomes = [], [], []
    original_compute = worker_module.TrainingLoop.compute
    rejoined = threading.Event()
    worker1_calls = 0

    def compute(loop, assignment):
        nonlocal worker1_calls
        if assignment.worker_id == 1:
            worker1_calls += 1
            if worker1_calls >= 2:
                assert rejoined.wait(5)
        return original_compute(loop, assignment)

    monkeypatch.setattr(worker_module.TrainingLoop, "compute", compute)

    try:
        runner.start()
        wait_until(lambda: runner._server is not None and runner._server.bound_address is not None)
        port = runner._server.bound_address[1]

        configs = []
        for index in range(2):
            alloc_id = f"alloc-managed-{index}"
            node_id = f"node-{index}"
            token = issue_worker_join_token(secret, "attempt", alloc_id, node_id)
            cfg = WorkerConfig(
                runtime_port=port,
                cache_dir=str(tmp_path / f"cache-{index}"),
                node_label=node_id,
                heartbeat_interval_seconds=0.2,
                attempt_id="attempt",
                allocation_id=alloc_id,
                node_id=node_id,
                worker_join_token=token,
            )
            configs.append(cfg)
            worker = WorkerProcess(cfg, initialization_seed=42, model_id="small_cnn")
            workers.append(worker)
            task = threading.Thread(target=lambda w=worker: outcomes.append(w.run()), daemon=True)
            tasks.append(task)
            task.start()

        wait_until(
            lambda: (
                runner._coordinator is not None
                and runner._coordinator.pool.counts["applied_units"] >= 1
                and len(runner._registry.snapshot()) == 2
                and all(s.state == "READY" for s in runner._registry.snapshot())
            )
        )

        # Simulate OS process crash of Worker 0 (terminate old WorkerProcess without reconnect)
        crashed_session = runner._registry.snapshot()[0]
        workers[0]._stop.set()
        workers[0]._client.disconnect()
        runner._server.fence(0, crashed_session.session_id)
        wait_until(lambda: runner._registry.snapshot()[0].state == "DISCONNECTED", timeout=5)

        # Spawn fresh replacement WorkerProcess using identical allocation credentials
        respawned = WorkerProcess(configs[0], initialization_seed=42, model_id="small_cnn")
        assert respawned.client_instance_id == workers[0].client_instance_id
        assert respawned.client_instance_id == str(
            uuid.uuid5(uuid.NAMESPACE_OID, "alloc-managed-0")
        )
        workers.append(respawned)
        respawn_outcomes = []
        respawn_task = threading.Thread(
            target=lambda: respawn_outcomes.append(respawned.run()), daemon=True
        )
        tasks.append(respawn_task)
        respawn_task.start()

        wait_until(
            lambda: (
                runner._registry.snapshot()[0].session_id != crashed_session.session_id
                and runner._registry.snapshot()[0].state == "READY"
            ),
            timeout=5,
        )
        rejoined.set()

        runner.join(12)
        assert runner.wait_closed(1), runner.snapshot("test")
        state = runner.snapshot("test")
        assert state["attempt_state"] == "COMPLETED", runner._failure
        assert state["strategy_state"]["processed_units"] == 16
        respawn_task.join(2)
        assert respawn_outcomes == [True]
    finally:
        rejoined.set()
        runner.abort()
        if runner._server:
            runner._server.stop()
        for worker in workers:
            worker._stop.set()
            worker._client.disconnect()
        for task in tasks:
            task.join(2)
        http.shutdown()
        http.server_close()
