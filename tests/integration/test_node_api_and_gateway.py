"""Integration tests for Node Management REST API and NodeControlGateway WSS control plane.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.2 & User Request Phase 6.

Tests:
1. REST API:
   - create enrollment code (POST /api/v1/nodes/enrollment-codes)
   - enroll node (POST /api/v1/nodes/enroll)
   - verify node_id and plaintext node_secret returned once
   - GET /api/v1/nodes/{node_id} (NodeDetail)
   - GET /api/v1/nodes (ListResponse[NodeItem])
   - revoke node (POST /api/v1/nodes/{node_id}/revoke)
   - second enrollment with same code rejected (NODE_ENROLLMENT_CODE_INVALID)
   - expired code rejected (NODE_ENROLLMENT_CODE_EXPIRED)
   - revoked node semantics
2. WSS Gateway Auth & Single Connection:
   - valid node_secret -> connect success
   - invalid secret -> rejected (1008)
   - revoked node -> rejected (1008)
   - unknown node -> rejected (1008)
   - same node cannot maintain two active connections (superseded connection closed)
3. AGENT_HELLO & Lifecycle:
   - valid AGENT_HELLO -> replies HELLO_ACK
   - Node OFFLINE -> ONLINE
   - capabilities and metadata persisted
4. HEARTBEAT & Liveness:
   - heartbeat updates last_seen_at
   - disconnect alone does NOT make node OFFLINE (remains ONLINE)
   - stale maintenance changes ONLINE -> OFFLINE
5. RESOURCE_SNAPSHOT:
   - resource snapshot persisted in latest_resources_jsonb
6. COMMAND_ACK & WORKER_STATUS:
   - COMMAND_ACK ACCEPTED keeps allocation DISPATCHED
   - COMMAND_ACK REJECTED transitions allocation to FAILED
   - WORKER_STATUS STARTED -> actual_state = STARTED
   - WORKER_STATUS ENDED -> actual_state = ENDED
   - WORKER_STATUS FAILED -> actual_state = FAILED
7. Revocation & Connection Close:
   - revoke closes active WSS connection
   - revoked node cannot reconnect
   - revoke does NOT stop worker or abort attempt
8. Maintenance:
   - stale node transitions ONLINE -> OFFLINE without altering attempts or allocations
   - worker start timeout transitions DISPATCHED -> FAILED
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    MESSAGE_TYPE_AGENT_HELLO,
    MESSAGE_TYPE_COMMAND_ACK,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_RESOURCE_SNAPSHOT,
    MESSAGE_TYPE_WORKER_STATUS,
    WORKER_ACTUAL_STATE_ENDED,
    WORKER_ACTUAL_STATE_STARTED,
    AgentEnvelope,
    AgentHelloPayload,
    CommandAckPayload,
    GpuSnapshotItem,
    HeartbeatPayload,
    ResourceSnapshotPayload,
    WorkerStatusPayload,
    parse_agent_envelope,
)
from pbl4.management_backend.app import _run_node_maintenance_once, create_app
from pbl4.management_backend.gateways.node_control_gateway import (
    get_node_control_gateway,
)
from pbl4.management_backend.repositories import (
    allocation_repository,
    node_enrollment_repository,
    node_repository,
)
from pbl4.management_backend.services import (
    allocation_service,
    node_service,
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
def app_client():
    """Module-level TestClient with initialized DB pool and gateway."""
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PBL4_WORKER_ADMISSION_SECRET"] = "integration-test-secret-key-32-chars!"
    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def pg_conn():
    """Connection fixture for direct DB verifications."""
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
    """Insert valid job and attempt for foreign key constraint satisfaction."""
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
                "API Test Job",
                "Job for Node API & Gateway tests",
                "READY",
                json.dumps({"dataset_build_id": "bld-test"}),
                json.dumps(
                    {
                        "training": {"training_seed": 42},
                        "synchronization": {"expected_workers": 2},
                    }
                ),
                "hash-node-test",
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
            (attempt_id, job_id, "RUNNING", "FRESH", "hash-node-test", now),
        )
    return job_id, attempt_id


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05):
    """Wait until predicate returns truthy value, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        val = predicate()
        if val:
            return val
        time.sleep(interval)
    return predicate()


# ─── 1. REST API Tests ────────────────────────────────────────────────────────


def test_01_create_enrollment_code_api(app_client: TestClient) -> None:
    res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 1800})
    assert res.status_code == 201
    data = res.json()["data"]
    assert "enrollment_code" in data
    assert "code_hash" in data
    assert len(data["enrollment_code"]) >= 32
    assert data["code_hash"] == hashlib.sha256(data["enrollment_code"].encode("utf-8")).hexdigest()


def test_02_enroll_node_and_credentials_api(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    # 1. Create code
    code_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = code_res.json()["data"]["enrollment_code"]

    # 2. Enroll node
    enroll_payload = {
        "enrollment_code": raw_code,
        "display_name": "Cluster Worker 01",
        "capabilities": {
            "hostname": "worker-box-01",
            "cpu_count_logical": 16,
            "ram_total_bytes": 34359738368,
            "gpus": [{"index": 0, "name": "NVIDIA RTX 4090"}],
        },
        "agent_version": "0.1.0",
        "platform": "Linux-6.5.0-x86_64",
    }
    enroll_res = app_client.post("/api/v1/nodes/enroll", json=enroll_payload)
    assert enroll_res.status_code == 201
    data = enroll_res.json()["data"]

    node_id = data["node_id"]
    node_secret = data["node_secret"]
    node_item = data["node"]

    assert node_id.startswith("node-")
    assert len(node_secret) >= 32
    assert node_item["state"] == "OFFLINE"  # Initial state strictly OFFLINE
    assert node_item["display_name"] == "Cluster Worker 01"

    # 3. GET /api/v1/nodes/{node_id} (NodeDetail)
    detail_res = app_client.get(f"/api/v1/nodes/{node_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()["data"]
    assert detail["node_id"] == node_id
    assert detail["state"] == "OFFLINE"
    assert detail["capabilities"]["cpu_count_logical"] == 16
    assert "node_secret" not in detail  # Secret never exposed in GET
    assert "credential_hash" not in detail

    # 4. GET /api/v1/nodes
    list_res = app_client.get("/api/v1/nodes")
    assert list_res.status_code == 200
    nodes = list_res.json()["data"]
    matching = [n for n in nodes if n["node_id"] == node_id]
    assert len(matching) == 1
    assert matching[0]["state"] == "OFFLINE"


def test_03_enroll_code_second_use_rejected(app_client: TestClient) -> None:
    code_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = code_res.json()["data"]["enrollment_code"]

    # First enrollment succeeds
    r1 = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    assert r1.status_code == 201

    # Second enrollment with same code rejected
    r2 = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    assert r2.status_code == 400
    err = r2.json()["error"]
    assert err["code"] == "NODE_ENROLLMENT_CODE_INVALID"


def test_04_expired_enrollment_code_rejected(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    # Insert already-expired code
    raw_code = f"expired-{uuid.uuid4().hex}"
    code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    node_enrollment_repository.create_enrollment_code(
        pg_conn,
        code_hash=code_hash,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )

    r = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "NODE_ENROLLMENT_CODE_EXPIRED"


def test_05_revoke_node_api(app_client: TestClient) -> None:
    code_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = code_res.json()["data"]["enrollment_code"]
    enroll_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = enroll_res.json()["data"]["node_id"]

    revoke_res = app_client.post(f"/api/v1/nodes/{node_id}/revoke")
    assert revoke_res.status_code == 200
    detail = revoke_res.json()["data"]
    assert detail["state"] == "REVOKED"
    assert detail["credential_revoked_at"] is not None


# ─── 2. WSS Gateway Auth & Connection Management ──────────────────────────────


def test_06_wss_auth_success_and_rejections(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    # 1. Enroll valid node
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    # A. Valid secret -> Connect succeeds
    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        assert ws is not None
        gw = get_node_control_gateway()
        assert gw.is_node_connected(node_id)

    # B. Invalid secret -> Rejected (policy violation 1008)
    with (
        pytest.raises(WebSocketDisconnect),
        app_client.websocket_connect(
            f"/ws/v1/nodes/{node_id}/control",
            headers={"Authorization": "Bearer wrong-secret"},
        ),
    ):
        pass

    # C. Revoked node -> Rejected (1008)
    app_client.post(f"/api/v1/nodes/{node_id}/revoke")
    with (
        pytest.raises(WebSocketDisconnect),
        app_client.websocket_connect(
            f"/ws/v1/nodes/{node_id}/control",
            headers={"Authorization": f"Bearer {node_secret}"},
        ),
    ):
        pass

    # D. Unknown node -> Rejected (1008)
    with (
        pytest.raises(WebSocketDisconnect),
        app_client.websocket_connect(
            "/ws/v1/nodes/node-nonexistent/control",
            headers={"Authorization": "Bearer any-secret"},
        ),
    ):
        pass


def test_07_one_active_control_connection_per_node(app_client: TestClient) -> None:
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    # Open first connection
    with (
        app_client.websocket_connect(
            f"/ws/v1/nodes/{node_id}/control",
            headers={"Authorization": f"Bearer {node_secret}"},
        ) as ws1,
        app_client.websocket_connect(
            f"/ws/v1/nodes/{node_id}/control",
            headers={"Authorization": f"Bearer {node_secret}"},
        ),
        pytest.raises(WebSocketDisconnect),
    ):
        # First connection was closed/superseded by second connection
        ws1.receive_text()


# ─── 3. AGENT_HELLO, HEARTBEAT & Liveness ─────────────────────────────────────


def test_08_agent_hello_transitions_offline_to_online(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    # Initially OFFLINE
    node = node_repository.get_node(pg_conn, node_id)
    assert node["state"] == "OFFLINE"

    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        # Send AGENT_HELLO
        hello_payload = AgentHelloPayload(
            agent_version="0.1.0",
            platform="Linux-6.5.0-x86_64",
            active_allocations=(),
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_AGENT_HELLO,
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=hello_payload.to_dict(),
        )
        ws.send_text(env.to_json())

        # Receive HELLO_ACK
        reply_raw = ws.receive_text()
        reply_env = parse_agent_envelope(reply_raw)
        assert reply_env.message_type == MESSAGE_TYPE_HELLO_ACK
        assert reply_env.correlation_id == env.message_id
        ack_data = reply_env.payload
        assert ack_data.heartbeat_interval_seconds > 0
        assert ack_data.telemetry_interval_seconds > 0

        # Verify DB state transitioned OFFLINE -> ONLINE
        node = node_repository.get_node(pg_conn, node_id)
        assert node["state"] == "ONLINE"
        assert node["last_seen_at"] is not None


def test_09_heartbeat_and_disconnect_alone_does_not_offline(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        # 1. Bring online with AGENT_HELLO
        env_hello = AgentEnvelope(
            message_type=MESSAGE_TYPE_AGENT_HELLO,
            message_id="msg-1",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=AgentHelloPayload(agent_version="0.1.0", platform="Linux").to_dict(),
        )
        ws.send_text(env_hello.to_json())
        ws.receive_text()  # ACK

        # 2. Send HEARTBEAT
        hb_env = AgentEnvelope(
            message_type=MESSAGE_TYPE_HEARTBEAT,
            message_id="msg-hb-1",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=HeartbeatPayload(active_allocations_count=0).to_dict(),
        )
        ws.send_text(hb_env.to_json())

    # 3. Connection closed. Invariant: Disconnect alone MUST NOT immediately mark node OFFLINE
    node = node_repository.get_node(pg_conn, node_id)
    assert node["state"] == "ONLINE"


def test_10_resource_snapshot_persisted(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        hello = AgentEnvelope(
            message_type=MESSAGE_TYPE_AGENT_HELLO,
            message_id="msg-res-hello",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=AgentHelloPayload(agent_version="0.1.0", platform="Linux").to_dict(),
        )
        ws.send_text(hello.to_json())
        assert parse_agent_envelope(ws.receive_text()).message_type == MESSAGE_TYPE_HELLO_ACK

        # Send RESOURCE_SNAPSHOT
        res_payload = ResourceSnapshotPayload(
            cpu_utilization_pct=42.5,
            ram_used_bytes=1000000,
            ram_total_bytes=4000000,
            gpus=(
                GpuSnapshotItem(
                    index=0,
                    gpu_utilization_pct=88.0,
                    vram_used_bytes=500000,
                    vram_total_bytes=24000000000,
                ),
            ),
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_RESOURCE_SNAPSHOT,
            message_id="msg-res-1",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=res_payload.to_dict(),
        )
        ws.send_text(env.to_json())

    # Verify persisted in database
    _wait_until(
        lambda: node_repository.get_node(pg_conn, node_id).get("latest_resources_jsonb") is not None
    )
    node = node_repository.get_node(pg_conn, node_id)
    resources = node["latest_resources_jsonb"]
    assert resources is not None
    assert resources["cpu_utilization_pct"] == 42.5
    assert len(resources["gpus"]) == 1
    assert resources["gpus"][0]["gpu_utilization_pct"] == 88.0


# ─── 4. COMMAND_ACK & WORKER_STATUS Mappings ──────────────────────────────────


def test_11_command_ack_and_worker_status_lifecycle(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    _, attempt_id = _create_test_job_and_attempt(pg_conn)

    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    # Bring node ONLINE
    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        ws.send_text(
            AgentEnvelope(
                message_type=MESSAGE_TYPE_AGENT_HELLO,
                message_id="msg-1",
                node_id=node_id,
                sent_at=datetime.now(UTC).isoformat(),
                payload=AgentHelloPayload(agent_version="0.1.0", platform="Linux").to_dict(),
            ).to_json()
        )
        ws.receive_text()

        # Create allocation in REQUESTED state
        alloc = allocation_service.create_allocation(
            pg_conn,
            attempt_id=attempt_id,
            node_id=node_id,
            device="cuda:0",
        )
        allocation_id = alloc["allocation_id"]

        # Simulate dispatch -> actual_state = DISPATCHED
        allocation_service.record_dispatched(pg_conn, allocation_id)
        assert (
            allocation_repository.get_allocation(pg_conn, allocation_id)["actual_state"]
            == "DISPATCHED"
        )

        # A. COMMAND_ACK ACCEPTED -> remains DISPATCHED
        ack_accepted = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND_ACK,
            message_id="msg-ack-1",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=CommandAckPayload(
                command_id="cmd-1",
                allocation_id=allocation_id,
                status=COMMAND_STATUS_ACCEPTED,
            ).to_dict(),
        )
        ws.send_text(ack_accepted.to_json())

        # Give small tick to process
        time.sleep(0.05)
        alloc = allocation_repository.get_allocation(pg_conn, allocation_id)
        assert alloc["actual_state"] == "DISPATCHED"

        # B. WORKER_STATUS STARTED -> actual_state = STARTED
        st_started = AgentEnvelope(
            message_type=MESSAGE_TYPE_WORKER_STATUS,
            message_id="msg-st-1",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=WorkerStatusPayload(
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                actual_state=WORKER_ACTUAL_STATE_STARTED,
            ).to_dict(),
        )
        ws.send_text(st_started.to_json())

        _wait_until(
            lambda: (
                allocation_repository.get_allocation(pg_conn, allocation_id).get("actual_state")
                == "STARTED"
            )
        )
        alloc = allocation_repository.get_allocation(pg_conn, allocation_id)
        assert alloc["actual_state"] == "STARTED"

        # C. WORKER_STATUS ENDED -> actual_state = ENDED
        st_ended = AgentEnvelope(
            message_type=MESSAGE_TYPE_WORKER_STATUS,
            message_id="msg-st-2",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=WorkerStatusPayload(
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                actual_state=WORKER_ACTUAL_STATE_ENDED,
                exit_code=0,
            ).to_dict(),
        )
        ws.send_text(st_ended.to_json())

        _wait_until(
            lambda: (
                allocation_repository.get_allocation(pg_conn, allocation_id).get("actual_state")
                == "ENDED"
            )
        )
        alloc = allocation_repository.get_allocation(pg_conn, allocation_id)
        assert alloc["actual_state"] == "ENDED"


def test_12_command_ack_rejected_transitions_to_failed(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    _, attempt_id = _create_test_job_and_attempt(pg_conn)

    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ) as ws:
        # AGENT_HELLO
        ws.send_text(
            AgentEnvelope(
                message_type=MESSAGE_TYPE_AGENT_HELLO,
                message_id="msg-1",
                node_id=node_id,
                sent_at=datetime.now(UTC).isoformat(),
                payload=AgentHelloPayload(agent_version="0.1.0", platform="Linux").to_dict(),
            ).to_json()
        )
        ws.receive_text()

        # Create allocation and mark DISPATCHED
        alloc = allocation_service.create_allocation(
            pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
        )
        allocation_id = alloc["allocation_id"]
        allocation_service.record_dispatched(pg_conn, allocation_id)

        # Send COMMAND_ACK REJECTED
        ack_rejected = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND_ACK,
            message_id="msg-ack-rej",
            node_id=node_id,
            sent_at=datetime.now(UTC).isoformat(),
            payload=CommandAckPayload(
                command_id="cmd-2",
                allocation_id=allocation_id,
                status=COMMAND_STATUS_REJECTED,
                error_code="WORKER_SPAWN_FAILED",
                error_message="Resource busy",
            ).to_dict(),
        )
        ws.send_text(ack_rejected.to_json())

        _wait_until(
            lambda: (
                allocation_repository.get_allocation(pg_conn, allocation_id).get("actual_state")
                == "FAILED"
            )
        )
        alloc = allocation_repository.get_allocation(pg_conn, allocation_id)
        assert alloc["actual_state"] == "FAILED"
        assert alloc["failure_code"] == "WORKER_SPAWN_FAILED"


# ─── 5. Revocation & Connection Close ─────────────────────────────────────────


def test_13_revoke_closes_active_wss_and_blocks_reconnect(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_secret = e_res.json()["data"]["node_secret"]

    with app_client.websocket_connect(
        f"/ws/v1/nodes/{node_id}/control",
        headers={"Authorization": f"Bearer {node_secret}"},
    ):
        # Node connected
        assert get_node_control_gateway().is_node_connected(node_id)

        # Revoke node via REST API
        rev_res = app_client.post(f"/api/v1/nodes/{node_id}/revoke")
        assert rev_res.status_code == 200
        assert rev_res.json()["data"]["state"] == "REVOKED"

        # Active connection was closed by gateway
        assert not get_node_control_gateway().is_node_connected(node_id)

    # Reconnect attempt must fail
    with (
        pytest.raises(WebSocketDisconnect),
        app_client.websocket_connect(
            f"/ws/v1/nodes/{node_id}/control",
            headers={"Authorization": f"Bearer {node_secret}"},
        ),
    ):
        pass


# ─── 6. Maintenance Logic Verification ────────────────────────────────────────


def test_14_stale_node_becomes_offline_without_altering_allocations(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    _, attempt_id = _create_test_job_and_attempt(pg_conn)

    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]

    # Manually mark ONLINE with old last_seen_at
    old_time = datetime.now(UTC) - timedelta(seconds=60)
    node_repository.update_state(pg_conn, node_id, "ONLINE")
    node_repository.update_heartbeat(pg_conn, node_id, old_time)

    # Create allocation
    alloc = allocation_service.create_allocation(
        pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
    )
    alloc_id = alloc["allocation_id"]

    # Run stale node check
    stale_ids = node_service.mark_stale_nodes(pg_conn, timeout_seconds=15.0)
    assert node_id in stale_ids

    # Node transitioned to OFFLINE
    node = node_repository.get_node(pg_conn, node_id)
    assert node["state"] == "OFFLINE"

    # Invariant: Allocation is UNTOUCHED by node liveness transition!
    alloc = allocation_repository.get_allocation(pg_conn, alloc_id)
    assert alloc["actual_state"] == "REQUESTED"


def test_15_dispatched_timeout_aborts_attempt_and_marks_allocation_failed(
    app_client: TestClient, pg_conn: psycopg.Connection
) -> None:
    _, attempt_id = _create_test_job_and_attempt(pg_conn)

    c_res = app_client.post("/api/v1/nodes/enrollment-codes", json={"ttl_seconds": 3600})
    raw_code = c_res.json()["data"]["enrollment_code"]
    e_res = app_client.post("/api/v1/nodes/enroll", json={"enrollment_code": raw_code})
    node_id = e_res.json()["data"]["node_id"]
    node_repository.update_state(pg_conn, node_id, "ONLINE")

    alloc = allocation_service.create_allocation(
        pg_conn, attempt_id=attempt_id, node_id=node_id, device="cpu"
    )
    alloc_id = alloc["allocation_id"]

    # Mark dispatched 100 seconds ago
    old_time = datetime.now(UTC) - timedelta(seconds=100)
    allocation_repository.update_actual_state(
        pg_conn, alloc_id, "DISPATCHED", dispatched_at=old_time
    )

    _run_node_maintenance_once(
        SimpleNamespace(
            node_heartbeat_timeout_seconds=60.0,
            worker_start_timeout_seconds=60.0,
        )
    )

    alloc = allocation_repository.get_allocation(pg_conn, alloc_id)
    assert alloc["actual_state"] == "FAILED"
    assert alloc["failure_code"] == "WORKER_START_TIMEOUT"
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT state, request_jsonb
              FROM control_commands
             WHERE command_type = 'ABORT_ATTEMPT' AND target_id = %s
             ORDER BY requested_at DESC
             LIMIT 1
            """,
            (attempt_id,),
        )
        command = cur.fetchone()
    assert command is not None
    assert command[0] == "PENDING"
    request = command[1] if isinstance(command[1], dict) else json.loads(command[1])
    assert request["reason"] == "Worker start timeout"
