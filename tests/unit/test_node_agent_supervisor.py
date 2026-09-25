"""Unit tests for WorkerProcessSupervisor.

Reference: Phase 3 requirements in NODE_AGENT_IMPLEMENTATION_PLAN.md:
1. Spawn success.
2. State transition STARTING -> RUNNING.
3. Duplicate START when STARTING/RUNNING is an idempotent no-op (ACCEPTED, no second spawn).
4. START after STOPPED is REJECTED.
5. START after FAILED is REJECTED.
6. Graceful STOP.
7. Force STOP.
8. Duplicate STOP on terminal record is an accepted no-op (ACCEPTED).
9. poll() detects terminated processes.
10. Process exit outside stop flow marks record FAILED.
11. Reconcile reattaches surviving processes.
12. Reconcile on PID / create_time mismatch marks record FAILED.
13. Mismatch does not attach process.
14. exit_code is None (never fabricated) after reconcile failure.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    ERROR_CODE_ALLOCATION_ALREADY_ACTIVE,
    ERROR_CODE_ALLOCATION_NOT_FOUND,
    ERROR_CODE_WORKER_STOP_FAILED,
    StartWorkerPayload,
)
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    LOCAL_STATE_STOPPED,
    LocalAllocationRecord,
    WorkerProcessSupervisor,
)


def _make_start_command(
    allocation_id: str = "alloc-1", attempt_id: str = "att-1"
) -> StartWorkerPayload:
    return StartWorkerPayload(
        command_id="cmd-1",
        allocation_id=allocation_id,
        attempt_id=attempt_id,
        runtime_host="127.0.0.1",
        runtime_port=9999,
        device="cpu",
        initialization_seed=1234,
        worker_join_token="secret-token-xyz",
    )


class TestWorkerProcessSupervisor(unittest.TestCase):
    """Comprehensive test suite for WorkerProcessSupervisor."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)
        self.supervisor = WorkerProcessSupervisor(self.var_dir, node_id="node-test-1")

    def tearDown(self) -> None:
        # Clean up any lingering subprocesses spawned by tests
        for proc in list(self.supervisor._subprocesses.values()):
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        self.temp_dir.cleanup()

    @patch("subprocess.Popen")
    def test_1_and_2_spawn_success_starting_to_running(self, mock_popen: MagicMock) -> None:
        """Spawn creates STARTING intent and transitions cleanly to RUNNING on successful launch."""
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        mock_popen.return_value = fake_proc

        with patch("psutil.Process") as mock_psutil_proc:
            p_inst = MagicMock()
            p_inst.create_time.return_value = 1000.0
            mock_psutil_proc.return_value = p_inst

            cmd = _make_start_command("alloc-1")
            status, err = self.supervisor.spawn_worker(cmd)

            self.assertEqual(status, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err)

            # Record must be RUNNING
            record = self.supervisor.get_record("alloc-1")
            self.assertIsNotNone(record)
            self.assertEqual(record.local_state, LOCAL_STATE_RUNNING)
            self.assertEqual(record.pid, 12345)
            self.assertEqual(record.create_time, 1000.0)

            # Verify CLI arguments do NOT contain the token, but token is in env
            called_args, called_kwargs = mock_popen.call_args
            cmd_list = called_args[0]
            self.assertEqual(cmd_list[0], sys.executable)
            self.assertIn("-m", cmd_list)
            self.assertIn("pbl4.worker.entrypoint", cmd_list)
            self.assertNotIn("secret-token-xyz", cmd_list)

            env = called_kwargs["env"]
            self.assertEqual(env.get("PBL4_WORKER_JOIN_TOKEN"), "secret-token-xyz")

    @patch("psutil.Process")
    @patch("subprocess.Popen")
    def test_3_duplicate_start_when_active_is_accepted_noop(
        self, mock_popen: MagicMock, mock_psutil_proc: MagicMock
    ) -> None:
        """Duplicate START_WORKER does not spawn a second process."""
        mock_psutil_proc.return_value.create_time.return_value = 1000.0
        mock_psutil_proc.return_value.is_running.return_value = True
        fake_proc = MagicMock()
        fake_proc.pid = 1111
        mock_popen.return_value = fake_proc

        cmd = _make_start_command("alloc-dup")
        status1, _ = self.supervisor.spawn_worker(cmd)
        self.assertEqual(status1, COMMAND_STATUS_ACCEPTED)
        self.assertEqual(mock_popen.call_count, 1)

        # Second START
        status2, err2 = self.supervisor.spawn_worker(cmd)
        self.assertEqual(status2, COMMAND_STATUS_ACCEPTED)
        self.assertIsNone(err2)
        # Must NOT call Popen a second time!
        self.assertEqual(mock_popen.call_count, 1)

    @patch("psutil.Process")
    @patch("subprocess.Popen")
    def test_4_and_5_start_after_stopped_or_failed_rejected(
        self, mock_popen: MagicMock, mock_psutil_proc: MagicMock
    ) -> None:
        """START_WORKER for an allocation that previously STOPPED or FAILED is rejected."""
        mock_psutil_proc.return_value.create_time.return_value = 1000.0
        mock_psutil_proc.return_value.is_running.return_value = True
        fake_proc = MagicMock()
        fake_proc.pid = 2222
        mock_popen.return_value = fake_proc

        # Test START after STOPPED
        cmd_stop = _make_start_command("alloc-stop")
        self.supervisor.spawn_worker(cmd_stop)
        self.supervisor.stop_worker("alloc-stop")
        rec = self.supervisor.get_record("alloc-stop")
        self.assertEqual(rec.local_state, LOCAL_STATE_STOPPED)

        status, err = self.supervisor.spawn_worker(cmd_stop)
        self.assertEqual(status, COMMAND_STATUS_REJECTED)
        self.assertEqual(err, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE)

        # Test START after FAILED
        cmd_fail = _make_start_command("alloc-fail")
        self.supervisor.spawn_worker(cmd_fail)
        # Simulate failure
        rec_fail = self.supervisor.get_record("alloc-fail")
        rec_fail.transition_to(LOCAL_STATE_FAILED, exit_code=1)

        status_f, err_f = self.supervisor.spawn_worker(cmd_fail)
        self.assertEqual(status_f, COMMAND_STATUS_REJECTED)
        self.assertEqual(err_f, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE)

    @patch("psutil.Process")
    @patch("subprocess.Popen")
    def test_6_and_7_stop_worker_graceful_and_force(
        self, mock_popen: MagicMock, mock_psutil_proc: MagicMock
    ) -> None:
        """Test stopping a worker gracefully and forcefully."""
        mock_psutil_proc.return_value.create_time.return_value = 1000.0
        mock_psutil_proc.return_value.is_running.return_value = True
        proc_mock = MagicMock()
        proc_mock.pid = 3333
        proc_mock.returncode = 0
        mock_popen.return_value = proc_mock

        cmd = _make_start_command("alloc-stop-test")
        self.supervisor.spawn_worker(cmd)

        # Graceful stop
        status, err = self.supervisor.stop_worker(
            "alloc-stop-test", grace_period_seconds=5.0, force=False
        )
        self.assertEqual(status, COMMAND_STATUS_ACCEPTED)
        self.assertIsNone(err)
        proc_mock.terminate.assert_called_once()
        self.assertEqual(
            self.supervisor.get_record("alloc-stop-test").local_state, LOCAL_STATE_STOPPED
        )

        # Force stop on another worker
        proc_mock2 = MagicMock()
        proc_mock2.pid = 4444
        proc_mock2.returncode = -9
        proc_mock2.wait.side_effect = [subprocess.TimeoutExpired("worker", 10.0), None]
        mock_popen.return_value = proc_mock2

        cmd2 = _make_start_command("alloc-force-test")
        self.supervisor.spawn_worker(cmd2)
        status2, _ = self.supervisor.stop_worker("alloc-force-test", force=True)
        self.assertEqual(status2, COMMAND_STATUS_ACCEPTED)
        proc_mock2.terminate.assert_called_once()
        proc_mock2.kill.assert_called_once()
        self.assertEqual(
            self.supervisor.get_record("alloc-force-test").local_state, LOCAL_STATE_STOPPED
        )

    @patch("psutil.Process")
    @patch("subprocess.Popen")
    def test_force_false_never_kills_stubborn_process(
        self, mock_popen: MagicMock, mock_psutil_proc: MagicMock
    ) -> None:
        mock_psutil_proc.return_value.create_time.return_value = 1000.0
        proc = MagicMock()
        proc.pid = 4555
        proc.wait.side_effect = subprocess.TimeoutExpired("worker", 0.01)
        mock_popen.return_value = proc
        self.supervisor.spawn_worker(_make_start_command("alloc-stubborn"))

        status, error = self.supervisor.stop_worker(
            "alloc-stubborn", grace_period_seconds=0.01, force=False
        )

        self.assertEqual(status, COMMAND_STATUS_REJECTED)
        self.assertEqual(error, ERROR_CODE_WORKER_STOP_FAILED)
        proc.kill.assert_not_called()
        self.assertEqual(
            self.supervisor.get_record("alloc-stubborn").local_state,
            LOCAL_STATE_RUNNING,
        )

    def test_8_duplicate_stop_on_terminal_is_accepted_noop(self) -> None:
        """Duplicate STOP_WORKER on an already STOPPED/FAILED allocation is an accepted no-op."""
        record = LocalAllocationRecord(
            allocation_id="alloc-term",
            attempt_id="att-1",
            local_state=LOCAL_STATE_STOPPED,
            created_at=time.time(),
        )
        self.supervisor._records["alloc-term"] = record

        status, err = self.supervisor.stop_worker("alloc-term")
        self.assertEqual(status, COMMAND_STATUS_ACCEPTED)
        self.assertIsNone(err)

    def test_stop_unknown_allocation_rejected(self) -> None:
        status, err = self.supervisor.stop_worker("alloc-nonexistent")
        self.assertEqual(status, COMMAND_STATUS_REJECTED)
        self.assertEqual(err, ERROR_CODE_ALLOCATION_NOT_FOUND)

    @patch("psutil.Process")
    @patch("subprocess.Popen")
    def test_9_and_10_poll_unexpected_exit_marks_failed(
        self, mock_popen: MagicMock, mock_psutil_proc: MagicMock
    ) -> None:
        """poll() detects that a process exited outside stop_worker and marks it FAILED."""
        mock_psutil_proc.return_value.create_time.return_value = 1000.0
        mock_psutil_proc.return_value.is_running.return_value = True
        fake_proc = MagicMock()
        fake_proc.pid = 5555
        fake_proc.poll.return_value = None  # running initially
        mock_popen.return_value = fake_proc

        cmd = _make_start_command("alloc-poll")
        self.supervisor.spawn_worker(cmd)
        self.assertEqual(self.supervisor.get_record("alloc-poll").local_state, LOCAL_STATE_RUNNING)

        # poll while running
        self.supervisor.poll()
        self.assertEqual(self.supervisor.get_record("alloc-poll").local_state, LOCAL_STATE_RUNNING)

        # process exits unexpectedly with error code 137
        fake_proc.poll.return_value = 137
        self.supervisor.poll()

        rec = self.supervisor.get_record("alloc-poll")
        self.assertEqual(rec.local_state, LOCAL_STATE_FAILED)
        self.assertEqual(rec.exit_code, 137)

    def test_11_reconcile_surviving_process_reattached(self) -> None:
        """Surviving Worker with matching PID and create_time is reattached as RUNNING."""
        rec = LocalAllocationRecord(
            allocation_id="alloc-reconcile-ok",
            attempt_id="att-1",
            local_state=LOCAL_STATE_RUNNING,
            created_at=time.time() - 100,
            pid=9999,
            create_time=5000.0,
        )
        self.supervisor._records[rec.allocation_id] = rec
        self.supervisor._save_records()

        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        mock_proc.status.return_value = psutil.STATUS_RUNNING
        mock_proc.create_time.return_value = 5000.5  # matches within epsilon

        with patch("psutil.Process", return_value=mock_proc):
            reconciled = self.supervisor.reconcile_on_startup()
            matching = next(r for r in reconciled if r.allocation_id == "alloc-reconcile-ok")
            self.assertEqual(matching.local_state, LOCAL_STATE_RUNNING)

    def test_12_13_14_reconcile_mismatch_marks_failed_without_exit_code(self) -> None:
        """PID / create_time mismatch marks record FAILED, does not attach, exit_code is None."""
        # Case A: Process does not exist (NoSuchProcess)
        rec1 = LocalAllocationRecord(
            allocation_id="alloc-dead",
            attempt_id="att-1",
            local_state=LOCAL_STATE_RUNNING,
            created_at=time.time() - 200,
            pid=8888,
            create_time=6000.0,
        )
        # Case B: PID exists but was reused (create_time mismatch)
        rec2 = LocalAllocationRecord(
            allocation_id="alloc-reused",
            attempt_id="att-1",
            local_state=LOCAL_STATE_RUNNING,
            created_at=time.time() - 200,
            pid=8889,
            create_time=6000.0,
        )
        self.supervisor._records = {rec1.allocation_id: rec1, rec2.allocation_id: rec2}
        self.supervisor._save_records()

        def psutil_side_effect(pid: int) -> MagicMock:
            if pid == 8888:
                raise psutil.NoSuchProcess(pid)
            p = MagicMock()
            p.is_running.return_value = True
            p.status.return_value = psutil.STATUS_RUNNING
            p.create_time.return_value = 999999.0  # complete mismatch
            return p

        with patch("psutil.Process", side_effect=psutil_side_effect):
            reconciled = self.supervisor.reconcile_on_startup()
            rec1_after = next(r for r in reconciled if r.allocation_id == "alloc-dead")
            rec2_after = next(r for r in reconciled if r.allocation_id == "alloc-reused")

            # 12 & 13: Both marked FAILED and not attached
            self.assertEqual(rec1_after.local_state, LOCAL_STATE_FAILED)
            self.assertEqual(rec2_after.local_state, LOCAL_STATE_FAILED)

            # 14: exit_code is None (never fabricated)
            self.assertIsNone(rec1_after.exit_code)
            self.assertIsNone(rec2_after.exit_code)


class TestRealProcessSupervisorIntegration(unittest.TestCase):
    """End-to-end unit test spawning a real Python subprocess and testing supervisor control."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)
        self.supervisor = WorkerProcessSupervisor(self.var_dir, node_id="node-real")

    def tearDown(self) -> None:
        for proc in list(self.supervisor._subprocesses.values()):
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_real_process_spawn_poll_stop_lifecycle(self) -> None:
        """Test with a real sleeping Python process to verify OS process handle management."""
        # Custom spawn executing sleep in python
        record = LocalAllocationRecord(
            allocation_id="real-alloc-1",
            attempt_id="att-1",
            local_state=LOCAL_STATE_STARTING,
            created_at=time.time(),
        )
        self.supervisor._records["real-alloc-1"] = record

        # Spawn a real Python process that sleeps for 5 seconds
        args = [sys.executable, "-c", "import time; time.sleep(5)"]
        proc = subprocess.Popen(args)
        self.supervisor._subprocesses["real-alloc-1"] = proc
        record.pid = proc.pid
        record.create_time = psutil.Process(proc.pid).create_time()
        record.transition_to(LOCAL_STATE_RUNNING)

        self.assertEqual(record.local_state, LOCAL_STATE_RUNNING)
        self.assertTrue(psutil.pid_exists(proc.pid))

        # Stop worker gracefully
        status, err = self.supervisor.stop_worker("real-alloc-1", grace_period_seconds=2.0)
        self.assertEqual(status, COMMAND_STATUS_ACCEPTED)
        self.assertIsNone(err)
        self.assertEqual(record.local_state, LOCAL_STATE_STOPPED)

        # Process should no longer be running
        time.sleep(0.1)
        self.assertFalse(
            psutil.Process(proc.pid).is_running() if psutil.pid_exists(proc.pid) else False
        )


if __name__ == "__main__":
    unittest.main()
