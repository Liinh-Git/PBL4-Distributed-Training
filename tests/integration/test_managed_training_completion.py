"""Production training with Worker OS processes owned exclusively by Node Agent."""

import asyncio
import functools
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from torch.nn import functional

from pbl4.adapter.models.factory import build_model
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.agent_protocol.messages import AgentEnvelope, StartWorkerPayload, parse_agent_envelope
from pbl4.common.async_training import resolve_async_training
from pbl4.common.worker_admission import issue_worker_join_token
from pbl4.management_backend.services.allocation_service import AllocationService
from pbl4.node_agent.client import NodeAgentClient
from pbl4.node_agent.supervisor import WorkerProcessSupervisor
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.process import _AttemptRunner
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


def wait_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for managed training")
        time.sleep(0.02)


@pytest.mark.parametrize(("strategy", "shard_count"), [("strict_bsp", 1), ("async_sgd", 3)])
def test_managed_workers_wait_for_agent_after_training(
    tmp_path, strategy, shard_count, monkeypatch
):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    manifest = PyTorchAdapter(
        build_model("small_cnn", initialization_seed=42, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    ).manifest
    data = create_synthetic_dataset_artifacts(
        tmp_path / "artifacts" / "build", dataset_build_id="build", shard_count=shard_count
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
            "shard_count": shard_count,
        },
        "model": {
            "model_id": "small_cnn",
            "profile": "SMALL_CNN_V1",
            "parameter_manifest_hash": manifest.parameter_manifest_hash,
        },
        "training": {"epochs": 2, "learning_rate": 0.001, "training_seed": 42},
        "workload": {"policy": "equal", "work_units_per_step": 2},
        "synchronization": {"training_strategy": strategy, "expected_workers": 2},
        "update_policy": {"type": "plain_sgd"},
        "checkpoint_policy": {
            "type": "periodic",
            "schema_version": 2 if strategy == "async_sgd" else 1,
            "policy_version": 1,
            "every_n_epochs": 1,
        },
        "protocols": {"dtp_version": 1, "mcp_version": 1},
        "async_training": resolve_async_training({"staleness_threshold": 0}),
    }
    if strategy == "strict_bsp":
        contract.pop("async_training")
    process = SimpleNamespace(
        _manifest=manifest,
        _manifests={},
        _host="127.0.0.1",
        _dtp_port=0,
        _worker_admission_secret="test-secret",
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
    training_ready, training_release = threading.Event(), threading.Event()
    original_loop = runner._training_loop

    def gated_training(coordinator, server):
        training_ready.set()
        if not training_release.wait(30):
            raise TimeoutError("Test did not release training gate")
        return original_loop(coordinator, server)

    runner._training_loop = gated_training
    agents = [
        WorkerProcessSupervisor(tmp_path / f"agent-{i}", node_id=f"node-{i}") for i in range(2)
    ]
    try:
        runner.start()
        wait_until(lambda: runner._server is not None and runner._server.bound_address is not None)
        for i, agent in enumerate(agents):
            command = StartWorkerPayload(
                command_id=f"start-{i}",
                allocation_id=f"allocation-{i}",
                attempt_id="attempt",
                runtime_host="127.0.0.1",
                runtime_port=runner._server.bound_address[1],
                device="cpu",
                initialization_seed=42,
                model_id="small_cnn",
                worker_join_token=issue_worker_join_token(
                    "test-secret", "attempt", f"allocation-{i}", f"node-{i}"
                ),
            )
            assert agent.spawn_worker(command) == ("ACCEPTED", None)
        assert training_ready.wait(30), runner.snapshot("test")
        if strategy == "async_sgd":
            # Rejoin the same Agent-owned OS process before issuing any training work.
            session = runner._registry.snapshot()[0]
            pid = agents[0].get_record("allocation-0").pid
            runner._server.fence(session.worker_id, session.session_id)
            wait_until(
                lambda: (
                    runner._registry.snapshot()[0].session_id != session.session_id
                    and runner._registry.snapshot()[0].state == "READY"
                )
            )
            assert agents[0].get_record("allocation-0").pid == pid
        training_release.set()
        assert runner.wait_closed(45), runner.snapshot("test")
        assert runner.snapshot("test")["attempt_state"] == "COMPLETED", runner._failure
        # Runtime has closed DTP. Only Node Agent may now terminate these processes.
        for i, agent in enumerate(agents):
            agent.poll()
            record = agent.get_record(f"allocation-{i}")
            assert record.local_state == "RUNNING"
            assert agent._subprocesses[f"allocation-{i}"].poll() is None
            client = NodeAgentClient.__new__(NodeAgentClient)
            client.identity = SimpleNamespace(node_id=f"node-{i}")
            client.supervisor = agent
            client._send_lock = asyncio.Lock()
            ws = AsyncMock()
            command = AllocationService.build_stop_worker_command(
                allocation={"allocation_id": f"allocation-{i}"},
                force=True,
            )
            envelope = AgentEnvelope(message_type="COMMAND", node_id=f"node-{i}", payload=command)
            asyncio.run(client._handle_stop_worker(ws, envelope, command))
            messages = [parse_agent_envelope(call.args[0]) for call in ws.send.call_args_list]
            assert messages[0].payload.status == "ACCEPTED"
            assert messages[1].payload.actual_state == "ENDED"
            assert agent.get_record(f"allocation-{i}").local_state == "STOPPED"
            assert agent.stop_worker(f"allocation-{i}", force=True) == ("ACCEPTED", None)
    finally:
        training_release.set()
        for i, agent in enumerate(agents):
            agent.stop_worker(f"allocation-{i}", force=True)
        runner.abort()
        runner.join(5)
        http.shutdown()
        http.server_close()
