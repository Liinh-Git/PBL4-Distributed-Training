"""Unit tests for Worker timeout defaults, deterministic rejoin identity, and NodeAgentConfig."""

from __future__ import annotations

import uuid

import pytest
import torch
from torch import nn

from pbl4.common.errors import ProtocolError
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.protocol.messages import Error, Stop
from pbl4.worker.config import WorkerConfig
from pbl4.worker.process import WorkerProcess


def test_worker_config_connect_timeout_defaults_and_validation() -> None:
    cfg = WorkerConfig(runtime_port=9000)
    assert cfg.connect_timeout_seconds == 60.0

    custom = WorkerConfig(runtime_port=9000, connect_timeout_seconds=15.0)
    assert custom.connect_timeout_seconds == 15.0

    for invalid in (0, -5.0, True):
        with pytest.raises(ValueError):
            WorkerConfig(runtime_port=9000, connect_timeout_seconds=invalid)  # type: ignore[arg-type]


def test_worker_process_deterministic_instance_id_and_retryability(monkeypatch) -> None:
    import pbl4.worker.process as worker_module

    torch.set_num_threads(1)
    monkeypatch.setattr(
        worker_module,
        "build_model",
        lambda *_a, **_kw: nn.Sequential(nn.Flatten(), nn.Linear(12, 10)),
    )

    managed_cfg = WorkerConfig(
        runtime_port=9000,
        attempt_id="att-1",
        allocation_id="alloc-deterministic-42",
        node_id="node-1",
        worker_join_token="token-abc",
    )
    w1 = WorkerProcess(managed_cfg, initialization_seed=42, model_id="small_cnn")
    w2 = WorkerProcess(managed_cfg, initialization_seed=42, model_id="small_cnn")
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "alloc-deterministic-42"))
    assert w1.client_instance_id == expected_id
    assert w2.client_instance_id == expected_id
    assert w1.retryable_failure is True

    unmanaged_1 = WorkerProcess(
        WorkerConfig(runtime_port=9000), initialization_seed=42, model_id="small_cnn"
    )
    unmanaged_2 = WorkerProcess(
        WorkerConfig(runtime_port=9000), initialization_seed=42, model_id="small_cnn"
    )
    assert unmanaged_1.client_instance_id != unmanaged_2.client_instance_id

    # Fatal Runtime Stop(FAILED) marks failure non-retryable (exit code 2)
    w1._on_message(
        Stop.from_dict(
            {
                "reason_code": "ATTEMPT_ABORTED",
                "reason": "stopped",
                "attempt_state": "FAILED",
                "whether_reconnect_allowed": False,
            }
        ),
        0,
    )
    assert w1.retryable_failure is False

    # Non-retryable Error frame marks failure non-retryable
    w2._on_message(
        Error.from_dict(
            {
                "error_code": "WORKER_ADMISSION_INVALID",
                "scope": "SESSION",
                "severity": "ERROR",
                "message": "rejected",
                "retryable": False,
            }
        ),
        0,
    )
    assert w2.retryable_failure is False

    # StrictBSP disconnect marks failure non-retryable; ProtocolError on connect does too
    w_sync = WorkerProcess(
        WorkerConfig(runtime_port=9000), initialization_seed=42, model_id="small_cnn"
    )
    w_sync._on_disconnect()
    assert w_sync.retryable_failure is False

    w_proto = WorkerProcess(
        WorkerConfig(runtime_port=9000), initialization_seed=42, model_id="small_cnn"
    )
    monkeypatch.setattr(
        w_proto._client,
        "connect",
        lambda: (_ for _ in ()).throw(ProtocolError("bad")),
    )
    assert w_proto.run() is False
    assert w_proto.retryable_failure is False


def test_node_agent_config_crash_retry_defaults_and_overrides(monkeypatch) -> None:
    default_cfg = NodeAgentConfig(backend_url="http://127.0.0.1:8000")
    assert default_cfg.max_worker_crash_retries == 3
    assert default_cfg.crash_retry_delay_seconds == 2.0

    # Crash retry settings stay code defaults even if extra env vars are present
    monkeypatch.setenv("PBL4_MAX_WORKER_CRASH_RETRIES", "5")
    monkeypatch.setenv("PBL4_CRASH_RETRY_DELAY_SECONDS", "1.5")
    env_cfg = NodeAgentConfig.from_env(backend_url="http://127.0.0.1:8000")
    assert env_cfg.max_worker_crash_retries == 3
    assert env_cfg.crash_retry_delay_seconds == 2.0

    # Explicit zero overrides must remain allowed without fallback
    zero_cfg = NodeAgentConfig.from_env(
        backend_url="http://127.0.0.1:8000",
        max_worker_crash_retries=0,
        crash_retry_delay_seconds=0.0,
    )
    assert zero_cfg.max_worker_crash_retries == 0
    assert zero_cfg.crash_retry_delay_seconds == 0.0

    for bad_retries in (-1, True, 1.5):
        with pytest.raises(ValueError):
            NodeAgentConfig(
                backend_url="http://127.0.0.1:8000",
                max_worker_crash_retries=bad_retries,  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            NodeAgentConfig.from_env(
                backend_url="http://127.0.0.1:8000",
                max_worker_crash_retries=bad_retries,
            )
    for bad_delay in (-0.5, True):
        with pytest.raises(ValueError):
            NodeAgentConfig(
                backend_url="http://127.0.0.1:8000",
                crash_retry_delay_seconds=bad_delay,  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            NodeAgentConfig.from_env(
                backend_url="http://127.0.0.1:8000",
                crash_retry_delay_seconds=bad_delay,
            )


def test_worker_entrypoint_default_timeout_and_exit_codes(monkeypatch) -> None:
    import sys

    import pbl4.worker.entrypoint as entrypoint_module
    import pbl4.worker.process as worker_module

    monkeypatch.setenv("PBL4_WORKER_CONNECT_TIMEOUT_SECONDS", "12.0")
    monkeypatch.setattr(
        sys, "argv", ["pbl4-worker", "--runtime-port", "9000", "--initialization-seed", "42"]
    )
    captured: dict[str, object] = {}

    class FakeWorkerProcess:
        def __init__(self, cfg, **_kw):
            captured["timeout"] = cfg.connect_timeout_seconds
            self.retryable_failure = bool(captured["retryable"])

        def run(self):
            return bool(captured["run_result"])

    monkeypatch.setattr(worker_module, "WorkerProcess", FakeWorkerProcess)
    outcomes = [(True, True, 0), (False, True, 1), (False, False, 2)]
    for run_result, retryable, expected_code in outcomes:
        captured["run_result"] = run_result
        captured["retryable"] = retryable
        with pytest.raises(SystemExit) as exc:
            entrypoint_module.main()
        assert exc.value.code == expected_code
        assert captured["timeout"] == 60.0
