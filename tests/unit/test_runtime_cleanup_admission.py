"""START waits for old resource cleanup, including abort before Coordinator creation."""

import threading
from unittest.mock import MagicMock, call, patch

import pytest

from pbl4.runtime.process import RuntimeProcess, _AttemptRunner


def _process(tmp_path):
    return RuntimeProcess(
        host="127.0.0.1",
        dtp_port=0,
        management_port=0,
        dataset_manager_url="http://127.0.0.1:1",
        checkpoint_dir=tmp_path,
        parameter_manifest=MagicMock(),
    )


@pytest.mark.parametrize("execution_mode", ["FRESH", "RESUME"])
@pytest.mark.parametrize("aborting", [False, True])
def test_start_waits_until_previous_cleanup_releases_resources(tmp_path, execution_mode, aborting):
    process = _process(tmp_path)
    management = MagicMock()
    old = _AttemptRunner(
        process=process,
        management=management,
        payload={"job_id": "job-1", "attempt_id": "attempt-old"},
    )
    process._active = old
    resolving, allow_resolve = threading.Event(), threading.Event()
    cleaning, allow_cleanup = threading.Event(), threading.Event()
    waiting = threading.Event()
    server = MagicMock()

    def resolve(_request):
        resolving.set()
        if aborting:
            assert allow_resolve.wait(3)
        raise RuntimeError("Injected provisioning failure")

    def stop():
        cleaning.set()
        assert allow_cleanup.wait(3)

    def wait_closed(timeout):
        waiting.set()
        return old._closed.wait(timeout)

    management.resolve_dataset_build.side_effect = resolve
    server.stop.side_effect = stop
    contract = {
        "synchronization": {"expected_workers": 2},
        "dataset": {"dataset_build_id": "build", "dataset_manifest_hash": "a" * 64},
    }
    responses = []
    request = threading.Thread(
        target=lambda: responses.append(
            process._handle_command(
                "START_ATTEMPT",
                {
                    "command_id": "new-command",
                    "attempt_id": "attempt-new",
                    "execution_mode": execution_mode,
                },
            )
        )
    )
    with (
        patch.object(old, "_validate_contract", return_value=contract),
        patch.object(old, "wait_closed", side_effect=wait_closed),
        patch("pbl4.runtime.process.ParameterServer", return_value=server),
        patch("pbl4.runtime.process._AttemptRunner") as new_runner,
    ):
        old._thread.start()
        try:
            assert resolving.wait(1)
            if aborting:
                old.abort()
                assert not old.terminal
            else:
                assert cleaning.wait(1)
            request.start()
            assert waiting.wait(1)
            assert responses == []
            new_runner.return_value.start.assert_not_called()
            allow_resolve.set()
            assert cleaning.wait(1)
            assert not old._closed.is_set()
            assert process._active is old
            allow_cleanup.set()
            request.join(2)
            old.join(2)
            assert not request.is_alive()
            assert old.wait_closed(0)
            assert responses[0]["status"] == "ACCEPTED"
            assert process._active is new_runner.return_value
            new_runner.return_value.start.assert_called_once()
        finally:
            allow_resolve.set()
            allow_cleanup.set()
            old.join(2)
            if request.ident is not None:
                request.join(2)


@pytest.mark.parametrize("closing", [False, True])
def test_running_or_cleanup_timeout_cannot_replace_active_attempt(tmp_path, closing):
    process = _process(tmp_path)
    old = MagicMock(closing=closing)
    old.wait_closed.return_value = False
    process._active = old
    with patch("pbl4.runtime.process._AttemptRunner") as new_runner:
        result = process._handle_command(
            "START_ATTEMPT",
            {"command_id": "new", "attempt_id": "attempt-new"},
        )
    assert result["result_code"] == "ACTIVE_ATTEMPT_EXISTS"
    assert process._active is old
    new_runner.assert_not_called()
    if closing:
        assert old.wait_closed.call_args_list == [call(5.0), call(0)]
    else:
        old.wait_closed.assert_called_once_with(0)


def test_aborted_initialization_cannot_be_treated_as_ready(tmp_path):
    process = _process(tmp_path)
    runner = _AttemptRunner(
        process=process, management=MagicMock(), payload={"job_id": "job", "attempt_id": "attempt"}
    )
    runner.abort()
    with pytest.raises(RuntimeError, match="Attempt aborted"):
        runner._wait_for(lambda: True, 1.0, "initialization")


def test_failed_socket_cleanup_does_not_signal_ready_or_release_owner(tmp_path):
    process = _process(tmp_path)
    runner = _AttemptRunner(
        process=process, management=MagicMock(), payload={"job_id": "job", "attempt_id": "attempt"}
    )
    process._active = runner
    server = MagicMock()
    server.stop.side_effect = OSError("cleanup failed")
    runner._server = server
    with (
        patch.object(runner, "_validate_contract", side_effect=ValueError("invalid contract")),
        pytest.raises(OSError, match="cleanup failed"),
    ):
        runner._run()
    assert not runner.wait_closed(0)
    assert process._active is runner


def test_cleanup_preserves_terminal_snapshot_until_next_start(tmp_path):
    process = _process(tmp_path)
    runner = _AttemptRunner(
        process=process,
        management=MagicMock(),
        payload={
            "job_id": "job",
            "attempt_id": "attempt-old",
            "resolved_contract": {
                "synchronization": {"training_strategy": "strict_bsp"},
                "checkpoint_policy": {"type": "periodic"},
                "dataset": {"dataset_build_id": "build", "dataset_manifest_hash": "a" * 64},
            },
        },
    )
    process._active = runner
    with patch.object(runner, "_validate_contract", side_effect=ValueError("invalid contract")):
        runner._run()
    assert runner.wait_closed(0)
    snapshot = process.snapshot()
    assert snapshot["active_attempt_id"] == "attempt-old"
    assert snapshot["attempt_state"] == "FAILED"
    with patch("pbl4.runtime.process._AttemptRunner") as new_runner:
        result = process._handle_command(
            "START_ATTEMPT", {"command_id": "new", "attempt_id": "attempt-new"}
        )
    assert result["status"] == "ACCEPTED"
    assert process._active is new_runner.return_value
