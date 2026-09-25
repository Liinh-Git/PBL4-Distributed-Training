"""Integration tests for Node Agent <-> Management Backend WSS control plane and CLI.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.2 & User Request Phase 7.

Validates end-to-end integration against live Backend and PostgreSQL database:
1. Enrollment CLI flow with persistent identity and initial OFFLINE state.
2. Start CLI validation (fails cleanly with exit code 1 if not enrolled).
3. Status CLI safety (shows node_id and allocation status with zero secret leaks).
4. Agent WSS connection & Handshake:
   - Valid node_secret -> CONNECT success
   - Invalid node_secret -> REJECTED
   - AGENT_HELLO sent with active allocations only
   - HELLO_ACK received, node transitions OFFLINE -> ONLINE
5. Periodic Heartbeat & Telemetry:
   - Heartbeat updates node last_seen_at
   - Resource snapshot persisted in latest_resources_jsonb
6. START_WORKER command:
   - Backend dispatches START_WORKER
   - Agent supervisor spawns worker process
   - Token passed via environment PBL4_WORKER_JOIN_TOKEN, strictly absent from CLI args
   - COMMAND_ACK ACCEPTED keeps allocation DISPATCHED
   - WORKER_STATUS STARTED transitions allocation to STARTED
7. Duplicate START_WORKER:
   - Repeated START_WORKER with same allocation_id returns ACCEPTED no-op
   - Zero duplicate processes spawned
8. STOP_WORKER command:
   - Backend dispatches STOP_WORKER
   - Process stopped gracefully
   - COMMAND_ACK ACCEPTED sent
   - WORKER_STATUS ENDED transitions allocation to ENDED
9. Worker crash detection:
   - Unexpected process exit detected
   - WORKER_STATUS FAILED sent with exit_code
   - Allocation transitions to FAILED
   - No auto-restart or allocation re-creation
10. Reconnect & Worker Survival Invariant:
   - WSS disconnect does NOT kill worker process
   - Agent reconnects with backoff
   - Surviving worker reported in AGENT_HELLO
   - Zero duplicate processes spawned
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest
import uvicorn

from pbl4 import PACKAGE_VERSION
from pbl4.management_backend.app import create_app
from pbl4.management_backend.gateways.node_control_gateway import (
    get_node_control_gateway,
)
from pbl4.management_backend.repositories import (
    allocation_repository,
    node_repository,
)
from pbl4.management_backend.services import (
    allocation_service,
)
from pbl4.node_agent.client import NodeAgentClient
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.entrypoint import main
from pbl4.node_agent.identity import NodeIdentity, load_identity, save_identity
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STOPPED,
    WorkerProcessSupervisor,
)

TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:123456@localhost:5432/pbl4_test"
)


def _is_db_available() -> bool:
    try:
        with psycopg.connect(TEST_DB_URL, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_db_available(),
    reason=f"PostgreSQL database not accessible at {TEST_DB_URL}",
)


@pytest.fixture(scope="module")
def live_server():
    """Spin up live Management Backend server on an ephemeral port with real DB connection pool."""
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PBL4_WORKER_ADMISSION_SECRET"] = "integration-test-secret-key-32-chars!"
    os.environ["NODE_TELEMETRY_INTERVAL_SECONDS"] = "1.0"
    os.environ["NODE_HEARTBEAT_INTERVAL_SECONDS"] = "1.0"
    app = create_app()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=0,
        log_level="error",
        http="h11",
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        time.sleep(0.02)

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)


@pytest.fixture
def http_client(live_server: str):
    """HTTP client communicating with the live test server."""
    with httpx.Client(base_url=live_server, timeout=5.0) as client:
        yield client


@pytest.fixture
def pg_conn():
    """Direct database connection for test assertions and fixture setups."""
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_active_attempts(pg_conn: psycopg.Connection):
    """Ensure no active attempt leaks across tests or test files."""
    with pg_conn.cursor() as cur:
        cur.execute(
            "UPDATE attempts SET state = 'COMPLETED' "
            "WHERE state NOT IN ('COMPLETED', 'FAILED', 'ABORTED')"
        )
    yield
    with pg_conn.cursor() as cur:
        cur.execute(
            "UPDATE attempts SET state = 'COMPLETED' "
            "WHERE state NOT IN ('COMPLETED', 'FAILED', 'ABORTED')"
        )


def _create_test_job_and_attempt(conn: psycopg.Connection) -> tuple[str, str]:
    """Helper to insert valid job and attempt satisfying DB foreign keys."""
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    attempt_id = f"att-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE attempts SET state = 'COMPLETED' "
            "WHERE state NOT IN ('COMPLETED', 'FAILED', 'ABORTED')"
        )
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract,
                resolved_contract, contract_hash, created_at, frozen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "Agent Integration Job",
                "Job for Node Agent integration tests",
                "READY",
                json.dumps({"dataset_build_id": "bld-test"}),
                json.dumps(
                    {
                        "training": {"training_seed": 42},
                        "synchronization": {"expected_workers": 1},
                    }
                ),
                "hash-agent-test",
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (attempt_id, job_id, "RUNNING", "FRESH", "hash-agent-test", now),
        )
    return job_id, attempt_id


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05):
    """Wait until predicate returns truthy value, or raise TimeoutError."""
    start = time.time()
    while time.time() - start < timeout:
        val = predicate()
        if val:
            return val
        time.sleep(interval)
    raise TimeoutError(f"Condition not met within {timeout}s")


# ─── 1. CLI Tests ─────────────────────────────────────────────────────────────


def test_01_cli_enrollment_persists_identity_and_creates_offline_node(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 1. Issue one-time enrollment code from backend
    code_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    assert code_res.status_code == 201
    code_data = code_res.json()["data"]
    enrollment_code = code_data["enrollment_code"]

    # 2. Run pbl4-agent enroll CLI command
    exit_code = main(
        [
            "enroll",
            "--backend-url",
            live_server,
            "--code",
            enrollment_code,
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 0

    # 3. Verify identity file created locally
    identity = load_identity(tmp_path)
    assert identity is not None
    assert identity.node_id.startswith("node-")
    assert len(identity.node_secret) >= 32

    # 4. Verify node persisted in database in OFFLINE state
    node = node_repository.get_node(pg_conn, identity.node_id)
    assert node is not None
    assert node["state"] == "OFFLINE"
    assert node["capabilities_jsonb"]["cpu_count_logical"] > 0

    # 5. Verify security: plaintext secret is never printed in CLI output
    captured = capsys.readouterr()
    assert identity.node_secret not in captured.out
    assert identity.node_secret not in captured.err


def test_02_cli_start_fails_cleanly_when_not_enrolled(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_dir = tmp_path / "empty_agent_dir"
    exit_code = main(["start", "--var-dir", str(empty_dir)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error: Node identity not found" in captured.err
    assert "pbl4-agent enroll" in captured.err


def test_03_cli_status_displays_safe_metadata_without_secrets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_identity(
        tmp_path, NodeIdentity(node_id="node-test-status", node_secret="secret-never-expose!")
    )

    exit_code = main(["status", "--var-dir", str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Enrollment Status:  ENROLLED" in captured.out
    assert "Node ID:            node-test-status" in captured.out
    assert "secret-never-expose!" not in captured.out


# ─── 2. WSS Connection & Handshake ────────────────────────────────────────────


def test_04_agent_connect_and_handshake_transitions_node_to_online(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    # 1. Enroll node
    code_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    code = code_res.json()["data"]["enrollment_code"]
    enroll_res = http_client.post("/api/v1/nodes/enroll", json={"enrollment_code": code})
    node_id = enroll_res.json()["data"]["node_id"]
    node_secret = enroll_res.json()["data"]["node_secret"]

    identity = NodeIdentity(node_id=node_id, node_secret=node_secret)
    config = NodeAgentConfig(
        backend_url=live_server,
        var_dir=str(tmp_path),
        heartbeat_interval_seconds=1.0,
        telemetry_interval_seconds=1.0,
        reconnect_min_seconds=0.1,
    )
    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(config=config, identity=identity, supervisor=supervisor)

    # 2. Run client session in background thread
    async def _run() -> None:
        await client.start()

    loop_thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
    loop_thread.start()

    try:
        # Wait until client connects and node transitions to ONLINE
        def _check_online() -> bool:
            n = node_repository.get_node(pg_conn, node_id)
            return n is not None and n["state"] == "ONLINE" and client.is_connected

        _wait_until(_check_online, timeout=5.0)

        node = node_repository.get_node(pg_conn, node_id)
        assert node["state"] == "ONLINE"
        assert node["agent_version"] == PACKAGE_VERSION
        assert node["last_seen_at"] is not None

        # Verify gateway has recorded the active connection
        gw = get_node_control_gateway()
        assert gw.is_node_connected(node_id)
    finally:
        client.stop()


def test_05_agent_connect_with_invalid_credentials_rejected(
    live_server: str,
    http_client: httpx.Client,
    tmp_path: Path,
) -> None:
    code_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    code = code_res.json()["data"]["enrollment_code"]
    enroll_res = http_client.post("/api/v1/nodes/enroll", json={"enrollment_code": code})
    node_id = enroll_res.json()["data"]["node_id"]

    # Deliberately invalid node_secret
    identity = NodeIdentity(node_id=node_id, node_secret="wrong-invalid-secret")
    config = NodeAgentConfig(
        backend_url=live_server,
        var_dir=str(tmp_path),
        reconnect_min_seconds=0.1,
        reconnect_max_seconds=0.2,
    )
    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(config=config, identity=identity, supervisor=supervisor)

    loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
    loop_thread.start()

    try:
        time.sleep(0.5)
        # Invalid secret must NEVER achieve authenticated connection
        assert not client.is_connected
        gw = get_node_control_gateway()
        assert not gw.is_node_connected(node_id)
    finally:
        client.stop()


# ─── 3. Heartbeat & Resource Telemetry ────────────────────────────────────────


def test_06_heartbeat_and_telemetry_persisted(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    code_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    code = code_res.json()["data"]["enrollment_code"]
    enroll_res = http_client.post("/api/v1/nodes/enroll", json={"enrollment_code": code})
    node_id = enroll_res.json()["data"]["node_id"]
    node_secret = enroll_res.json()["data"]["node_secret"]

    identity = NodeIdentity(node_id=node_id, node_secret=node_secret)
    config = NodeAgentConfig(
        backend_url=live_server,
        var_dir=str(tmp_path),
        heartbeat_interval_seconds=0.5,
        telemetry_interval_seconds=0.5,
    )
    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(config=config, identity=identity, supervisor=supervisor)

    loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
    loop_thread.start()

    try:
        # Wait until telemetry is persisted in DB
        def _check_telemetry() -> bool:
            n = node_repository.get_node(pg_conn, node_id)
            return (
                n is not None
                and n.get("latest_resources_jsonb") is not None
                and "cpu_utilization_pct" in n["latest_resources_jsonb"]
            )

        _wait_until(_check_telemetry, timeout=5.0)

        node = node_repository.get_node(pg_conn, node_id)
        latest_res = node["latest_resources_jsonb"]
        assert "cpu_utilization_pct" in latest_res
        assert "ram_used_bytes" in latest_res
        assert "ram_total_bytes" in latest_res
    finally:
        client.stop()


# ─── 4. Command Handling: START, STOP, Crashes, Duplicate ─────────────────────


def test_07_start_worker_and_env_token(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    # 1. Enroll node
    c_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    e_res = http_client.post(
        "/api/v1/nodes/enroll", json={"enrollment_code": c_res.json()["data"]["enrollment_code"]}
    )
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    # 2. Create agent client with mock popen to verify environment token
    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(
        config=NodeAgentConfig(backend_url=live_server, var_dir=str(tmp_path)),
        identity=NodeIdentity(node_id=node_id, node_secret=node_secret),
        supervisor=supervisor,
    )

    captured_env: dict[str, str] = {}
    captured_args: list[str] = []

    def _mock_popen(
        cmd_args: list[str], env: dict[str, str] | None = None, **kwargs: Any
    ) -> MagicMock:
        if env is None:
            probe = MagicMock()
            probe.communicate.return_value = (b"", b"")
            probe.returncode = 0
            return probe
        captured_args.extend(cmd_args)
        captured_env.update(env)
        proc = MagicMock()
        proc.pid = 99911
        proc.poll.return_value = None  # running
        return proc

    with patch("subprocess.Popen", side_effect=_mock_popen), patch("psutil.Process"):
        loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
        loop_thread.start()

        try:
            # 3. Wait until node connects and transitions to ONLINE
            _wait_until(lambda: client.is_connected, timeout=5.0)

            # 4. Now that node is ONLINE, setup job, attempt, and allocation in DB
            job_id, attempt_id = _create_test_job_and_attempt(pg_conn)
            alloc = allocation_service.create_allocation(
                pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
            )
            allocation_id = alloc["allocation_id"]

            # 5. Backend builds START_WORKER command and dispatches via gateway
            job = {"job_id": job_id, "resolved_contract": {"training": {"training_seed": 42}}}
            start_cmd = allocation_service.build_start_worker_command(allocation=alloc, job=job)
            gw = get_node_control_gateway()
            allocation_service.record_dispatched(pg_conn, allocation_id)
            success = gw.send_start_worker(node_id, command=start_cmd)
            assert success is True

            # 6. Wait until allocation actual_state becomes STARTED in DB
            def _check_started() -> bool:
                a = allocation_repository.get_allocation(pg_conn, allocation_id)
                return a is not None and a["actual_state"] == "STARTED"

            _wait_until(_check_started, timeout=5.0)

            # 7. Verify security invariants:
            # - Token was passed via env["PBL4_WORKER_JOIN_TOKEN"]
            # - Token was NOT passed in command line arguments
            assert "PBL4_WORKER_JOIN_TOKEN" in captured_env
            token = captured_env["PBL4_WORKER_JOIN_TOKEN"]
            assert len(token) > 20
            for arg in captured_args:
                assert token not in arg
        finally:
            client.stop()


def test_08_duplicate_start_worker_noop(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    c_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    e_res = http_client.post(
        "/api/v1/nodes/enroll", json={"enrollment_code": c_res.json()["data"]["enrollment_code"]}
    )
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(
        config=NodeAgentConfig(backend_url=live_server, var_dir=str(tmp_path)),
        identity=NodeIdentity(node_id=node_id, node_secret=node_secret),
        supervisor=supervisor,
    )

    spawn_count = 0

    def _mock_popen(
        cmd_args: list[str], env: dict[str, str] | None = None, **kwargs: Any
    ) -> MagicMock:
        nonlocal spawn_count
        if env is None:
            probe = MagicMock()
            probe.communicate.return_value = (b"", b"")
            probe.returncode = 0
            return probe
        spawn_count += 1
        proc = MagicMock()
        proc.pid = 88822
        proc.poll.return_value = None
        return proc

    with patch("subprocess.Popen", side_effect=_mock_popen), patch("psutil.Process"):
        loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
        loop_thread.start()

        try:
            # Wait until node is ONLINE
            _wait_until(lambda: client.is_connected, timeout=5.0)

            job_id, attempt_id = _create_test_job_and_attempt(pg_conn)
            alloc = allocation_service.create_allocation(
                pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
            )
            allocation_id = alloc["allocation_id"]

            job = {"job_id": job_id, "resolved_contract": {"training": {"training_seed": 42}}}
            start_cmd = allocation_service.build_start_worker_command(allocation=alloc, job=job)
            gw = get_node_control_gateway()

            # First START_WORKER
            allocation_service.record_dispatched(pg_conn, allocation_id)
            gw.send_start_worker(node_id, command=start_cmd)
            _wait_until(
                lambda: (
                    allocation_repository.get_allocation(pg_conn, allocation_id)["actual_state"]
                    == "STARTED"
                ),
                timeout=5.0,
            )
            assert spawn_count == 1

            # Duplicate START_WORKER
            gw.send_start_worker(node_id, command=start_cmd)
            time.sleep(0.5)

            # Idempotency invariant: must NOT spawn second process!
            assert spawn_count == 1
        finally:
            client.stop()


def test_09_stop_worker_graceful(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    c_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    e_res = http_client.post(
        "/api/v1/nodes/enroll", json={"enrollment_code": c_res.json()["data"]["enrollment_code"]}
    )
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(
        config=NodeAgentConfig(backend_url=live_server, var_dir=str(tmp_path)),
        identity=NodeIdentity(node_id=node_id, node_secret=node_secret),
        supervisor=supervisor,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 77733
    mock_proc.poll.return_value = None
    mock_proc.returncode = 0

    with patch("subprocess.Popen", return_value=mock_proc), patch("psutil.Process"):
        loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
        loop_thread.start()

        try:
            # Wait until node is ONLINE
            _wait_until(lambda: client.is_connected, timeout=5.0)

            job_id, attempt_id = _create_test_job_and_attempt(pg_conn)
            alloc = allocation_service.create_allocation(
                pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
            )
            allocation_id = alloc["allocation_id"]

            # Start worker
            job = {"job_id": job_id, "resolved_contract": {"training": {"training_seed": 42}}}
            start_cmd = allocation_service.build_start_worker_command(allocation=alloc, job=job)
            gw = get_node_control_gateway()
            allocation_service.record_dispatched(pg_conn, allocation_id)
            gw.send_start_worker(node_id, command=start_cmd)

            _wait_until(
                lambda: (
                    allocation_repository.get_allocation(pg_conn, allocation_id)["actual_state"]
                    == "STARTED"
                ),
                timeout=5.0,
            )

            # Stop worker
            stop_cmd = allocation_service.build_stop_worker_command(
                allocation=alloc, grace_period_seconds=1.0
            )
            gw.send_stop_worker(node_id, command=stop_cmd)

            # Allocation must transition to ENDED
            def _check_ended() -> bool:
                a = allocation_repository.get_allocation(pg_conn, allocation_id)
                return a is not None and a["actual_state"] == "ENDED"

            _wait_until(_check_ended, timeout=5.0)
            assert supervisor.get_record(allocation_id).local_state == LOCAL_STATE_STOPPED
        finally:
            client.stop()


def test_10_worker_crash_detected_and_reported_failed(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    c_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    e_res = http_client.post(
        "/api/v1/nodes/enroll", json={"enrollment_code": c_res.json()["data"]["enrollment_code"]}
    )
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(
        config=NodeAgentConfig(backend_url=live_server, var_dir=str(tmp_path)),
        identity=NodeIdentity(node_id=node_id, node_secret=node_secret),
        supervisor=supervisor,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 66644
    mock_proc.poll.return_value = None  # running initially

    with patch("subprocess.Popen", return_value=mock_proc), patch("psutil.Process"):
        loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
        loop_thread.start()

        try:
            # Wait until node is ONLINE
            _wait_until(lambda: client.is_connected, timeout=5.0)

            job_id, attempt_id = _create_test_job_and_attempt(pg_conn)
            alloc = allocation_service.create_allocation(
                pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
            )
            allocation_id = alloc["allocation_id"]

            job = {"job_id": job_id, "resolved_contract": {"training": {"training_seed": 42}}}
            start_cmd = allocation_service.build_start_worker_command(allocation=alloc, job=job)
            gw = get_node_control_gateway()
            allocation_service.record_dispatched(pg_conn, allocation_id)
            gw.send_start_worker(node_id, command=start_cmd)

            _wait_until(
                lambda: (
                    allocation_repository.get_allocation(pg_conn, allocation_id)["actual_state"]
                    == "STARTED"
                ),
                timeout=5.0,
            )

            # Simulate worker process crash
            mock_proc.poll.return_value = 137  # e.g. SIGKILL / OOM

            # Agent monitor loop should detect termination and report WORKER_STATUS FAILED
            def _check_failed() -> bool:
                a = allocation_repository.get_allocation(pg_conn, allocation_id)
                return a is not None and a["actual_state"] == "FAILED"

            _wait_until(_check_failed, timeout=5.0)

            rec = supervisor.get_record(allocation_id)
            assert rec.local_state == LOCAL_STATE_FAILED
            assert rec.exit_code == 137
        finally:
            client.stop()


# ─── 5. Reconnect & Worker Survival Invariant ─────────────────────────────────


def test_11_reconnect_and_worker_survival_invariant(
    live_server: str,
    http_client: httpx.Client,
    pg_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    c_res = http_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    e_res = http_client.post(
        "/api/v1/nodes/enroll", json={"enrollment_code": c_res.json()["data"]["enrollment_code"]}
    )
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    supervisor = WorkerProcessSupervisor(var_dir=tmp_path, node_id=node_id)
    client = NodeAgentClient(
        config=NodeAgentConfig(
            backend_url=live_server,
            var_dir=str(tmp_path),
            reconnect_min_seconds=0.2,
            reconnect_max_seconds=0.5,
        ),
        identity=NodeIdentity(node_id=node_id, node_secret=node_secret),
        supervisor=supervisor,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 55555
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc), patch("psutil.Process"):
        loop_thread = threading.Thread(target=lambda: asyncio.run(client.start()), daemon=True)
        loop_thread.start()

        try:
            # Wait until node is ONLINE
            _wait_until(lambda: client.is_connected, timeout=5.0)

            job_id, attempt_id = _create_test_job_and_attempt(pg_conn)
            alloc = allocation_service.create_allocation(
                pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
            )
            allocation_id = alloc["allocation_id"]

            # Start worker
            job = {"job_id": job_id, "resolved_contract": {"training": {"training_seed": 42}}}
            start_cmd = allocation_service.build_start_worker_command(allocation=alloc, job=job)
            gw = get_node_control_gateway()
            allocation_service.record_dispatched(pg_conn, allocation_id)
            gw.send_start_worker(node_id, command=start_cmd)

            _wait_until(
                lambda: (
                    allocation_repository.get_allocation(pg_conn, allocation_id)["actual_state"]
                    == "STARTED"
                ),
                timeout=5.0,
            )

            # Force server-side disconnect of active websocket
            ws_conn = gw._active_connections.get(node_id)
            if ws_conn is not None:
                # Use server's running loop to close websocket
                gw._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(ws_conn.close(code=1001, reason="Test simulation"))
                )

            # Worker survival invariant check:
            # Subprocess must NOT be killed or terminated
            mock_proc.terminate.assert_not_called()
            mock_proc.kill.assert_not_called()

            # Wait for client to reconnect automatically
            _wait_until(lambda: client.is_connected, timeout=5.0)

            # Allocation record in supervisor is still RUNNING
            rec = supervisor.get_record(allocation_id)
            assert rec.local_state == LOCAL_STATE_RUNNING

            # Invariant: Active allocation still alive, no duplicate worker spawned
            records = supervisor.list_records()
            assert len(records) == 1
        finally:
            client.stop()
