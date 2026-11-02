"""Accepted launches arm management snapshot observation without blocking dispatch."""

import asyncio
import contextlib
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pbl4.management_backend.app import _runtime_snapshot_loop
from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway


@pytest.mark.parametrize("state", ["ACCEPTED", "REJECTED"])
def test_only_accepted_launch_arms_pretraining_observation(state):
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port)

    def dispatch(**kwargs):
        gateway._pending_results[kwargs["command_id"]].set_result({"state": state})
        return True

    with (
        patch("pbl4.management_backend.gateways.runtime_gateway.project_command", return_value={}),
        patch.object(port, "send_command", side_effect=dispatch),
        patch.object(port, "request_state") as request,
    ):
        gateway.send_command_and_wait_result("START_ATTEMPT", "command", "attempt")
    assert gateway._pretraining_attempt_id == ("attempt" if state == "ACCEPTED" else None)
    request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_snapshot_shutdown_waits_for_the_actual_worker_thread(worker_fails):
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def refresh():
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(2)
            if worker_fails:
                raise RuntimeError("Snapshot request failed during shutdown")
        finally:
            finished.set()

    task = asyncio.create_task(
        _runtime_snapshot_loop(SimpleNamespace(refresh_pretraining_snapshot=refresh))
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)  # Deliver cancellation while the thread is still blocked.
        assert not task.done()
        assert not finished.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert finished.is_set()
    finally:
        release.set()
        with contextlib.suppress(asyncio.CancelledError):
            await task
