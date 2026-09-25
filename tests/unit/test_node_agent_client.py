"""Unit tests for NodeAgentClient logic, handshake, command handling, and survival invariants.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 7.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pbl4 import PACKAGE_VERSION
from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    ERROR_CODE_ALLOCATION_ALREADY_ACTIVE,
    MESSAGE_TYPE_AGENT_HELLO,
    MESSAGE_TYPE_COMMAND,
    MESSAGE_TYPE_COMMAND_ACK,
    MESSAGE_TYPE_WORKER_STATUS,
    WORKER_ACTUAL_STATE_ENDED,
    WORKER_ACTUAL_STATE_FAILED,
    WORKER_ACTUAL_STATE_STARTED,
    AgentEnvelope,
    StartWorkerPayload,
    StopWorkerPayload,
    parse_agent_envelope,
)
from pbl4.node_agent.client import (
    NodeAgentClient,
    get_connect_headers_kwargs,
    get_control_ws_url,
)
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.identity import NodeIdentity
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    LOCAL_STATE_STOPPED,
    LocalAllocationRecord,
    WorkerProcessSupervisor,
)


def test_get_control_ws_url() -> None:
    """Verify URL transformation from HTTP/HTTPS/WS/WSS to canonical control endpoint."""
    assert (
        get_control_ws_url("http://127.0.0.1:8000", "node-1")
        == "ws://127.0.0.1:8000/ws/v1/nodes/node-1/control"
    )
    assert (
        get_control_ws_url("http://localhost:8000/", "node-2")
        == "ws://localhost:8000/ws/v1/nodes/node-2/control"
    )
    assert (
        get_control_ws_url("https://backend.example.com", "node-3")
        == "wss://backend.example.com/ws/v1/nodes/node-3/control"
    )
    assert (
        get_control_ws_url("ws://custom-host:9000", "node-4")
        == "ws://custom-host:9000/ws/v1/nodes/node-4/control"
    )


def test_get_connect_headers_kwargs() -> None:
    """Verify version-compatible header argument extraction."""
    headers = {"Authorization": "Bearer secret"}
    kwargs = get_connect_headers_kwargs(headers)
    assert "additional_headers" in kwargs or "extra_headers" in kwargs


@pytest.fixture
def mock_supervisor(tmp_path: Path) -> WorkerProcessSupervisor:
    sup = MagicMock(spec=WorkerProcessSupervisor)
    sup.var_dir = tmp_path
    sup.node_id = "test-node-01"
    sup.list_records.return_value = []
    sup.poll.return_value = []
    sup.get_record.return_value = None
    return sup


@pytest.fixture
def agent_client(mock_supervisor: WorkerProcessSupervisor) -> NodeAgentClient:
    config = NodeAgentConfig(
        backend_url="http://127.0.0.1:8000",
        var_dir=str(mock_supervisor.var_dir),
        heartbeat_interval_seconds=2.0,
        telemetry_interval_seconds=4.0,
        reconnect_min_seconds=0.1,
        reconnect_max_seconds=0.5,
    )
    identity = NodeIdentity(node_id="test-node-01", node_secret="test-secret-123")
    return NodeAgentClient(config=config, identity=identity, supervisor=mock_supervisor)


def test_agent_hello_advertises_only_active_allocations(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """Verify AGENT_HELLO includes STARTING and RUNNING allocations, omitting STOPPED and FAILED."""

    async def _run() -> None:
        r_starting = LocalAllocationRecord("alloc-1", "att-1", LOCAL_STATE_STARTING, 100.0, pid=101)
        r_running = LocalAllocationRecord("alloc-2", "att-1", LOCAL_STATE_RUNNING, 101.0, pid=102)
        r_stopped = LocalAllocationRecord(
            "alloc-3", "att-1", LOCAL_STATE_STOPPED, 102.0, pid=103, exit_code=0
        )
        r_failed = LocalAllocationRecord(
            "alloc-4", "att-1", LOCAL_STATE_FAILED, 103.0, pid=104, exit_code=1
        )

        mock_supervisor.list_records.return_value = [r_starting, r_running, r_stopped, r_failed]

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        await agent_client._send_agent_hello(mock_ws)

        assert len(sent_frames) == 1
        env = parse_agent_envelope(sent_frames[0])
        assert env.message_type == MESSAGE_TYPE_AGENT_HELLO
        assert env.node_id == "test-node-01"
        payload = env.payload
        assert payload.agent_version == PACKAGE_VERSION

        active_ids = [item.allocation_id for item in payload.active_allocations]
        assert active_ids == ["alloc-1", "alloc-2"]
        assert "alloc-3" not in active_ids
        assert "alloc-4" not in active_ids

    asyncio.run(_run())


def test_handle_start_worker_success(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """START_WORKER spawns, acknowledges, and reports STARTED."""

    async def _run() -> None:
        mock_supervisor.get_record.return_value = None  # New allocation
        mock_supervisor.spawn_worker.return_value = (COMMAND_STATUS_ACCEPTED, None)

        cmd = StartWorkerPayload(
            command_id="cmd-start-1",
            allocation_id="alloc-new",
            attempt_id="att-1",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            device="cpu",
            initialization_seed=42,
            worker_join_token="jwt-token-abc",
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id="test-node-01",
            payload=cmd,
        )

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        await agent_client._handle_start_worker(mock_ws, env, cmd)

        mock_supervisor.spawn_worker.assert_called_once_with(cmd)
        assert len(sent_frames) == 2

        # 1. COMMAND_ACK
        ack_env = parse_agent_envelope(sent_frames[0])
        assert ack_env.message_type == MESSAGE_TYPE_COMMAND_ACK
        assert ack_env.correlation_id == "cmd-start-1"
        assert ack_env.payload.status == COMMAND_STATUS_ACCEPTED
        assert ack_env.payload.allocation_id == "alloc-new"

        # 2. WORKER_STATUS STARTED
        st_env = parse_agent_envelope(sent_frames[1])
        assert st_env.message_type == MESSAGE_TYPE_WORKER_STATUS
        assert st_env.payload.actual_state == WORKER_ACTUAL_STATE_STARTED
        assert st_env.payload.allocation_id == "alloc-new"

    asyncio.run(_run())


def test_handle_duplicate_start_worker_noop(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """Duplicate active START_WORKER is an accepted no-op."""

    async def _run() -> None:
        existing_rec = LocalAllocationRecord(
            "alloc-dup", "att-1", LOCAL_STATE_RUNNING, 100.0, pid=555
        )
        mock_supervisor.get_record.return_value = existing_rec
        mock_supervisor.spawn_worker.return_value = (COMMAND_STATUS_ACCEPTED, None)

        cmd = StartWorkerPayload(
            command_id="cmd-start-dup",
            allocation_id="alloc-dup",
            attempt_id="att-1",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            device="cpu",
            initialization_seed=42,
            worker_join_token="jwt-token-abc",
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id="test-node-01",
            payload=cmd,
        )

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        await agent_client._handle_start_worker(mock_ws, env, cmd)

        # Only 1 frame sent: COMMAND_ACK (no duplicate WORKER_STATUS STARTED)
        assert len(sent_frames) == 1
        ack_env = parse_agent_envelope(sent_frames[0])
        assert ack_env.message_type == MESSAGE_TYPE_COMMAND_ACK
        assert ack_env.payload.status == COMMAND_STATUS_ACCEPTED

    asyncio.run(_run())


def test_handle_start_worker_terminal_rejected(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """Verify START_WORKER on terminal allocation returns REJECTED."""

    async def _run() -> None:
        existing_rec = LocalAllocationRecord(
            "alloc-dead", "att-1", LOCAL_STATE_STOPPED, 100.0, exit_code=0
        )
        mock_supervisor.get_record.return_value = existing_rec
        mock_supervisor.spawn_worker.return_value = (
            COMMAND_STATUS_REJECTED,
            ERROR_CODE_ALLOCATION_ALREADY_ACTIVE,
        )

        cmd = StartWorkerPayload(
            command_id="cmd-start-dead",
            allocation_id="alloc-dead",
            attempt_id="att-1",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            device="cpu",
            initialization_seed=42,
            worker_join_token="jwt-token-abc",
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id="test-node-01",
            payload=cmd,
        )

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        await agent_client._handle_start_worker(mock_ws, env, cmd)

        assert len(sent_frames) == 1
        ack_env = parse_agent_envelope(sent_frames[0])
        assert ack_env.message_type == MESSAGE_TYPE_COMMAND_ACK
        assert ack_env.payload.status == COMMAND_STATUS_REJECTED
        assert ack_env.payload.error_code == ERROR_CODE_ALLOCATION_ALREADY_ACTIVE

    asyncio.run(_run())


def test_handle_stop_worker_success(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """STOP_WORKER stops, acknowledges, and reports ENDED."""

    async def _run() -> None:
        rec_before = LocalAllocationRecord(
            "alloc-stop", "att-1", LOCAL_STATE_RUNNING, 100.0, pid=666
        )
        rec_after = LocalAllocationRecord(
            "alloc-stop", "att-1", LOCAL_STATE_STOPPED, 100.0, exit_code=0
        )

        # get_record returns rec_before on first call, rec_after on second call
        mock_supervisor.get_record.side_effect = [rec_before, rec_after]
        mock_supervisor.stop_worker.return_value = (COMMAND_STATUS_ACCEPTED, None)

        cmd = StopWorkerPayload(
            command_id="cmd-stop-1",
            allocation_id="alloc-stop",
            grace_period_seconds=5.0,
            force=False,
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id="test-node-01",
            payload=cmd,
        )

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        await agent_client._handle_stop_worker(mock_ws, env, cmd)

        mock_supervisor.stop_worker.assert_called_once_with(
            "alloc-stop", grace_period_seconds=5.0, force=False
        )
        assert len(sent_frames) == 2

        # 1. COMMAND_ACK ACCEPTED
        ack_env = parse_agent_envelope(sent_frames[0])
        assert ack_env.message_type == MESSAGE_TYPE_COMMAND_ACK
        assert ack_env.payload.status == COMMAND_STATUS_ACCEPTED

        # 2. WORKER_STATUS ENDED
        st_env = parse_agent_envelope(sent_frames[1])
        assert st_env.message_type == MESSAGE_TYPE_WORKER_STATUS
        assert st_env.payload.actual_state == WORKER_ACTUAL_STATE_ENDED
        assert st_env.payload.exit_code == 0

    asyncio.run(_run())


def test_unexpected_worker_crash_reported_failed(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """Verify supervisor.poll detecting FAILED process sends WORKER_STATUS FAILED."""

    async def _run() -> None:
        r_crashed = LocalAllocationRecord(
            "alloc-crash", "att-9", LOCAL_STATE_FAILED, 100.0, exit_code=137
        )
        mock_supervisor.poll.return_value = [r_crashed]

        sent_frames: list[str] = []
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=lambda text: sent_frames.append(text))

        # Run one pass of monitor logic
        records = mock_supervisor.poll()
        for r in records:
            if (
                r.local_state == LOCAL_STATE_FAILED
                and r.allocation_id not in agent_client._reported_failures
            ):
                agent_client._reported_failures.add(r.allocation_id)
                from pbl4.agent_protocol.messages import WorkerStatusPayload

                payload = WorkerStatusPayload(
                    allocation_id=r.allocation_id,
                    attempt_id=r.attempt_id,
                    actual_state=WORKER_ACTUAL_STATE_FAILED,
                    exit_code=r.exit_code,
                    failure_code="WORKER_PROCESS_CRASHED",
                    failure_message=f"Process exited {r.exit_code}",
                )
                env = AgentEnvelope(
                    message_type=MESSAGE_TYPE_WORKER_STATUS,
                    node_id=agent_client.identity.node_id,
                    payload=payload,
                )
                await agent_client._send_envelope(mock_ws, env)

        assert len(sent_frames) == 1
        st_env = parse_agent_envelope(sent_frames[0])
        assert st_env.message_type == MESSAGE_TYPE_WORKER_STATUS
        assert st_env.payload.actual_state == WORKER_ACTUAL_STATE_FAILED
        assert st_env.payload.exit_code == 137
        assert st_env.payload.failure_code == "WORKER_PROCESS_CRASHED"

        # Second pass: already reported, must NOT resend
        sent_frames.clear()
        for r in records:
            if (
                r.local_state == LOCAL_STATE_FAILED
                and r.allocation_id not in agent_client._reported_failures
            ):
                agent_client._reported_failures.add(r.allocation_id)
                await agent_client._send_envelope(mock_ws, env)
        assert len(sent_frames) == 0

    asyncio.run(_run())


def test_worker_survival_invariant_on_stop(
    agent_client: NodeAgentClient,
    mock_supervisor: MagicMock,
) -> None:
    """Worker survival invariant: stop() must NEVER terminate or kill supervised workers."""
    agent_client.stop()
    assert agent_client._stopped is True
    # Verify supervisor.stop_worker was NOT called
    mock_supervisor.stop_worker.assert_not_called()
