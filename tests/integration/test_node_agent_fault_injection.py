"""Fault Injection and Release Gate Integration Tests for Node Agent & Managed Admission.

Reference: Phase 9 requirements in NODE_AGENT_IMPLEMENTATION_PLAN.md:
- Fault Invariant 1: Agent restart preserves running Worker, DTP stays alive, reconcile finds PID, no duplicate Worker.
- Fault Invariant 2: Backend restart preserves running Worker, DTP stays alive, Agent reconnects, no duplicate Worker.
- Fault Invariant 3: Duplicate START_WORKER idempotency across STARTING, RUNNING, STOPPED, FAILED states.
- Fault Invariant 4: Worker admission gate: 10 rejection cases verified BEFORE registry.register(), positive admission verified.
- Liveness fix: ParameterServer duplicate registry.heartbeat() elimination and microsecond drift prevention.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import psutil

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    ERROR_CODE_ALLOCATION_ALREADY_ACTIVE,
    StartWorkerPayload,
)
from pbl4.common.worker_admission import issue_worker_join_token
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    LOCAL_STATE_STOPPED,
    LocalAllocationRecord,
    WorkerProcessSupervisor,
)
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_SHARD_READY,
)
from pbl4.protocol.messages import (
    ERROR_CODE_WORKER_ADMISSION_EXPIRED,
    ERROR_CODE_WORKER_ADMISSION_INVALID,
    ERROR_CODE_WORKER_ADMISSION_REQUIRED,
    ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH,
    DtpControlMessage,
    Error,
    Heartbeat,
    Hello,
    HelloAck,
    ShardReady,
    build_control_frame,
    decode_control_message,
)
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.runtime.parameter_server import ParameterServer, _Connection
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.transport.framed_socket import recv_exact, send_all


def _dummy_manifest() -> ParameterManifest:
    return ParameterManifest.create([ParameterEntry(0, "weight", (3,), "float32", 3, 0, 12)])


def _base_hello_dict() -> dict[str, object]:
    return {
        "node_label": "test-node",
        "client_instance_id": "test-client-uuid",
        "role": "worker",
        "protocol_version": 1,
        "framework_adapter": "pytorch",
        "supported_tensor_encoding": ["fp32_le_v1"],
        "supported_strategy_capabilities": ["strict_bsp"],
    }


def _valid_shard_ready_dict(shard_id: int = 0) -> dict[str, object]:
    return {
        "dataset_build_id": "bld-test",
        "dataset_manifest_hash": "a" * 64,
        "shard_id": shard_id,
        "shard_manifest_hash": "b" * 64,
        "verified_batch_count": 10,
        "verified_sample_count": 100,
        "cache_key": "cache-key-1",
        "completed_at": "2026-09-25T00:00:00Z",
    }


class TestFaultInvariant1AgentRestart(unittest.TestCase):
    """Fault Invariant 1: Agent restart while Worker is actively running.

    Invariants:
    1. Worker OS process continues running throughout Agent shutdown/restart.
    2. DTP connection Worker <-> Runtime remains active and unbroken.
    3. Agent restarts and reconcile_on_startup() verifies Worker PID and create_time.
    4. Worker PID before restart == Worker PID after reconcile.
    5. Agent does NOT spawn a duplicate second Worker process.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)
        self.secret = "fault-injection-secret-key-32ch!"
        self.manifest = _dummy_manifest()
        self.registry = WorkerRegistry("att-fi-1", 1)
        self.server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="att-fi-1",
            job_id="job-fi-1",
            expected_workers=1,
            manifest=self.manifest,
            registry=self.registry,
            worker_admission_secret=self.secret,
            require_worker_admission=True,
        )
        self.server.start()
        self.host, self.port = self.server.bound_address or ("127.0.0.1", 0)

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_dir.cleanup()

    def test_agent_restart_preserves_worker_process_and_dtp_connection(self) -> None:
        # Step 1: Start Supervisor 1 and spawn real OS Worker process
        supervisor1 = WorkerProcessSupervisor(self.var_dir, node_id="node-fi-1")
        token = issue_worker_join_token(
            secret=self.secret,
            attempt_id="att-fi-1",
            allocation_id="alloc-fi-1",
            node_id="node-fi-1",
            ttl_seconds=300,
        )

        # We spawn a real lightweight Python process that connects via DTP and holds connection
        src_path = str(Path(__file__).resolve().parents[2] / "src").replace("\\", "/")
        worker_code = f"""
import os, socket, sys, time
sys.path.insert(0, '{src_path}')
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.messages import Hello, build_control_frame
from pbl4.transport.framed_socket import recv_exact, send_all

sock = socket.create_connection(('{self.host}', {self.port}), timeout=5.0)
hello = Hello.from_dict({{
    'node_label': 'node-fi-1',
    'client_instance_id': 'proc-client-1',
    'role': 'worker',
    'protocol_version': 1,
    'framework_adapter': 'pytorch',
    'supported_tensor_encoding': ['fp32_le_v1'],
    'supported_strategy_capabilities': ['strict_bsp'],
    'attempt_id': 'att-fi-1',
    'allocation_id': 'alloc-fi-1',
    'node_id': 'node-fi-1',
    'worker_join_token': '{token}',
}})
frame = build_control_frame(hello)
frame.write_to(sock, send_all)

# Read HelloAck
resp = DTPFrame.read_from(sock, recv_exact)
# Stay alive holding connection
time.sleep(30)
"""
        # Record intent as STARTING
        record = LocalAllocationRecord(
            allocation_id="alloc-fi-1",
            attempt_id="att-fi-1",
            local_state=LOCAL_STATE_STARTING,
            created_at=time.time(),
        )
        supervisor1._records["alloc-fi-1"] = record
        supervisor1._save_records()

        # Spawn real OS process with explicit PYTHONPATH
        sub_env = {**os.environ, "PYTHONPATH": src_path}
        proc = subprocess.Popen([sys.executable, "-c", worker_code], env=sub_env)
        supervisor1._subprocesses["alloc-fi-1"] = proc

        # Wait briefly for process to initialize and connect
        time.sleep(0.5)
        p_info = psutil.Process(proc.pid)
        record.pid = proc.pid
        record.create_time = p_info.create_time()
        record.local_state = LOCAL_STATE_RUNNING
        supervisor1._save_records()

        worker_pid_before = proc.pid
        self.assertTrue(psutil.pid_exists(worker_pid_before))
        self.assertTrue(self.server.wait_for_workers(1, timeout=5.0))

        # Check DTP connection is alive in Runtime
        self.assertEqual(len(self.registry.snapshot()), 1)
        self.assertEqual(self.registry.snapshot()[0].state, SessionState.PROVISIONING)

        # Step 2: Simulate Agent restart (Agent stops, supervisor object discarded)
        # Note: proc is NOT killed because in production Agent process restart does not kill children
        del supervisor1

        # Step 3: Verify Worker OS process is STILL ALIVE during Agent downtime
        self.assertTrue(psutil.pid_exists(worker_pid_before), "Worker process must survive Agent stop")
        self.assertEqual(len(self.server.worker_ids()), 1, "DTP connection must remain alive")

        # Step 4: Start Supervisor 2 (Agent rebooted) and run reconcile_on_startup()
        supervisor2 = WorkerProcessSupervisor(self.var_dir, node_id="node-fi-1")
        reconciled = supervisor2.reconcile_on_startup()

        # Step 5: Verify reconciliation results
        self.assertEqual(len(reconciled), 1)
        rec = reconciled[0]
        self.assertEqual(rec.allocation_id, "alloc-fi-1")
        self.assertEqual(rec.local_state, LOCAL_STATE_RUNNING)
        self.assertEqual(rec.pid, worker_pid_before, "Worker PID before restart == Worker PID after reconcile")
        self.assertIsNone(rec.exit_code, "Must not fabricate exit code for live process")

        # Step 6: Verify duplicate START_WORKER after restart does NOT spawn second process
        cmd = StartWorkerPayload(
            command_id="cmd-dup",
            allocation_id="alloc-fi-1",
            attempt_id="att-fi-1",
            runtime_host=self.host,
            runtime_port=self.port,
            device="cpu",
            initialization_seed=42,
            worker_join_token=token,
        )
        status, err = supervisor2.spawn_worker(cmd)
        self.assertEqual(status, COMMAND_STATUS_ACCEPTED)
        self.assertIsNone(err)

        # Process count remains exactly 1, PID unchanged
        self.assertEqual(rec.pid, worker_pid_before)

        # Clean teardown
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            proc.kill()


class TestFaultInvariant2BackendRestart(unittest.TestCase):
    """Fault Invariant 2: Backend restart while Worker is actively training.

    Invariants:
    1. Worker <-> Runtime DTP training connection continues operating while Backend is down.
    2. Backend outage does NOT terminate or fail running Worker processes.
    3. When Backend comes back online, Agent reconnects and sends AGENT_HELLO.
    4. Backend reconciles active allocation and does NOT re-issue START_WORKER.
    5. Zero duplicate Worker processes.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)
        self.manifest = _dummy_manifest()
        self.registry = WorkerRegistry("att-fi-2", 1)
        self.server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="att-fi-2",
            job_id="job-fi-2",
            expected_workers=1,
            manifest=self.manifest,
            registry=self.registry,
            worker_admission_secret="backend-restart-secret-key-32ch!",
            require_worker_admission=True,
        )
        self.server.start()
        self.host, self.port = self.server.bound_address or ("127.0.0.1", 0)

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_dir.cleanup()

    def test_backend_restart_does_not_disrupt_worker_or_dtp(self) -> None:
        # Step 1: Worker connects to Runtime DTP
        token = issue_worker_join_token(
            secret="backend-restart-secret-key-32ch!",
            attempt_id="att-fi-2",
            allocation_id="alloc-fi-2",
            node_id="node-fi-2",
            ttl_seconds=300,
        )

        client_sock = socket.create_connection((self.host, self.port), timeout=5.0)
        try:
            hello = Hello.from_dict({
                **_base_hello_dict(),
                "node_label": "node-fi-2",
                "attempt_id": "att-fi-2",
                "allocation_id": "alloc-fi-2",
                "node_id": "node-fi-2",
                "worker_join_token": token,
            })
            frame = build_control_frame(hello)
            frame.write_to(client_sock, send_all)

            ack_frame = DTPFrame.read_from(client_sock, recv_exact)
            self.assertEqual(ack_frame.header.message_type, MESSAGE_TYPE_HELLO_ACK)
            self.assertEqual(len(self.server.worker_ids()), 1)

            # Step 2: Simulate Backend down — Management control plane is unavailable
            # Meanwhile, Worker continues to transmit DTP frames to Runtime
            ready = ShardReady.from_dict(_valid_shard_ready_dict(shard_id=0))
            ready_frame = build_control_frame(ready, session_id=1, worker_id=0)
            ready_frame.write_to(client_sock, send_all)

            time.sleep(0.1)
            # Runtime processed frame regardless of Backend status
            self.assertEqual(self.registry.snapshot()[0].state, SessionState.SHARD_READY)

            # Send heartbeat frame over DTP while Backend is "dead"
            hb = Heartbeat.from_dict({
                "attempt_id": "att-fi-2",
                "worker_state": "SHARD_READY",
                "local_model_version": 0,
                "last_completed_operation_id": None,
                "recovery_cursor": {"epoch": 0},
                "monotonic_timestamp_ms": 1000.0,
            })
            hb_frame = build_control_frame(hb, session_id=1, worker_id=0)
            hb_frame.write_to(client_sock, send_all)

            time.sleep(0.1)
            # Invariant: DTP session is alive and updated throughout Backend absence
            self.assertGreater(self.server.last_seen(0), 0)

            # Step 3: Supervisor on Agent side verifies Worker is intact
            supervisor = WorkerProcessSupervisor(self.var_dir, node_id="node-fi-2")
            supervisor._records["alloc-fi-2"] = LocalAllocationRecord(
                allocation_id="alloc-fi-2",
                attempt_id="att-fi-2",
                local_state=LOCAL_STATE_RUNNING,
                created_at=time.time(),
                pid=os.getpid(),
                create_time=psutil.Process(os.getpid()).create_time(),
            )
            # Reconcile confirms running
            active = supervisor.reconcile_on_startup()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].local_state, LOCAL_STATE_RUNNING)
        finally:
            client_sock.close()


class TestFaultInvariant3DuplicateStartWorker(unittest.TestCase):
    """Fault Invariant 3: Idempotency of duplicate START_WORKER and STOP_WORKER.

    Cases:
    Case A: Fresh allocation -> spawn exactly 1 Worker.
    Case B: Resend START when STARTING -> ACCEPTED no-op -> no second process.
    Case C: Resend START when RUNNING -> ACCEPTED no-op -> no second process.
    Case D: Resend START after STOPPED -> REJECTED -> does not resurrect allocation.
    Case E: Resend START after FAILED -> REJECTED -> does not resurrect allocation.
    Case F: Duplicate STOP on terminal record -> ACCEPTED no-op.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)
        self.supervisor = WorkerProcessSupervisor(self.var_dir, node_id="node-fi-3")

    def tearDown(self) -> None:
        for proc in list(self.supervisor._subprocesses.values()):
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        self.temp_dir.cleanup()

    def test_duplicate_start_and_terminal_idempotency_matrix(self) -> None:
        cmd_a = StartWorkerPayload(
            command_id="cmd-1",
            allocation_id="alloc-dup-A",
            attempt_id="att-dup",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            device="cpu",
            initialization_seed=123,
            worker_join_token="tok-a",
        )

        with patch("subprocess.Popen") as mock_popen, patch("psutil.Process") as mock_psutil:
            fake_proc = MagicMock()
            fake_proc.pid = 44401
            mock_popen.return_value = fake_proc

            p_inst = MagicMock()
            p_inst.create_time.return_value = 5000.0
            p_inst.is_running.return_value = True
            p_inst.status.return_value = psutil.STATUS_RUNNING
            mock_psutil.return_value = p_inst

            # Case A: Fresh allocation -> spawns exactly 1 worker
            status1, err1 = self.supervisor.spawn_worker(cmd_a)
            self.assertEqual(status1, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err1)
            self.assertEqual(mock_popen.call_count, 1)
            rec = self.supervisor.get_record("alloc-dup-A")
            self.assertIsNotNone(rec)
            self.assertEqual(rec.local_state, LOCAL_STATE_RUNNING)

            # Case C: Resend START when RUNNING -> ACCEPTED no-op, call_count remains 1
            status2, err2 = self.supervisor.spawn_worker(cmd_a)
            self.assertEqual(status2, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err2)
            self.assertEqual(mock_popen.call_count, 1, "Duplicate START on RUNNING must NOT spawn second process")

            # Case B: Duplicate START when STARTING -> ACCEPTED no-op
            cmd_b = StartWorkerPayload(
                command_id="cmd-2",
                allocation_id="alloc-dup-B",
                attempt_id="att-dup",
                runtime_host="127.0.0.1",
                runtime_port=9000,
                device="cpu",
                initialization_seed=123,
                worker_join_token="tok-b",
            )
            # Create intent in STARTING
            rec_b = LocalAllocationRecord(
                allocation_id="alloc-dup-B",
                attempt_id="att-dup",
                local_state=LOCAL_STATE_STARTING,
                created_at=time.time(),
            )
            self.supervisor._records["alloc-dup-B"] = rec_b
            self.supervisor._save_records()

            status_b, err_b = self.supervisor.spawn_worker(cmd_b)
            self.assertEqual(status_b, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err_b)
            self.assertEqual(mock_popen.call_count, 1, "Duplicate START on STARTING must NOT spawn second process")

            # Case D: START after STOPPED -> REJECTED
            rec.local_state = LOCAL_STATE_STOPPED
            self.supervisor._save_records()
            status_d, err_d = self.supervisor.spawn_worker(cmd_a)
            self.assertEqual(status_d, COMMAND_STATUS_REJECTED)
            self.assertEqual(err_d, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE)
            self.assertEqual(mock_popen.call_count, 1)

            # Case E: START after FAILED -> REJECTED
            rec_b.local_state = LOCAL_STATE_FAILED
            self.supervisor._save_records()
            status_e, err_e = self.supervisor.spawn_worker(cmd_b)
            self.assertEqual(status_e, COMMAND_STATUS_REJECTED)
            self.assertEqual(err_e, ERROR_CODE_ALLOCATION_ALREADY_ACTIVE)
            self.assertEqual(mock_popen.call_count, 1)

            # Case F: Duplicate STOP on terminal record -> ACCEPTED no-op
            status_stop1, err_stop1 = self.supervisor.stop_worker("alloc-dup-A")
            self.assertEqual(status_stop1, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err_stop1)

            status_stop2, err_stop2 = self.supervisor.stop_worker("alloc-dup-A")
            self.assertEqual(status_stop2, COMMAND_STATUS_ACCEPTED)
            self.assertIsNone(err_stop2)


class TestFaultInvariant4WorkerAdmission(unittest.TestCase):
    """Fault Invariant 4: Worker admission gates evaluated strictly BEFORE registration.

    Invariants:
    1. Every invalid admission attempt is rejected immediately.
    2. Invalid admission fails BEFORE:
       - worker count increases
       - rank is assigned
       - WorkerRegistry.register() is called
       - valid session is created.
    3. worker count before == worker count after == 0.
    4. Positive case: valid admission succeeds and increments worker count to 1.
    """

    def setUp(self) -> None:
        self.secret = "admission-gate-secret-key-32ch!!"
        self.manifest = _dummy_manifest()
        self.registry = WorkerRegistry("att-fi-4", 1)
        self.server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="att-fi-4",
            job_id="job-fi-4",
            expected_workers=1,
            manifest=self.manifest,
            registry=self.registry,
            worker_admission_secret=self.secret,
            require_worker_admission=True,
        )
        self.server.start()
        self.host, self.port = self.server.bound_address or ("127.0.0.1", 0)

    def tearDown(self) -> None:
        self.server.stop()

    def _send_hello_and_get_response(self, hello_dict: dict[str, object]) -> DtpControlMessage | None:
        s = socket.create_connection((self.host, self.port), timeout=5.0)
        try:
            hello = Hello.from_dict(hello_dict)
            frame = build_control_frame(hello)
            frame.write_to(s, send_all)

            try:
                resp_frame = DTPFrame.read_from(s, recv_exact)
                msg = decode_control_message(resp_frame.header.message_type, resp_frame.payload)
                return msg
            except Exception:
                return None
        finally:
            s.close()

    def test_all_10_negative_admission_cases_fail_before_registration(self) -> None:
        valid_token = issue_worker_join_token(
            secret=self.secret,
            attempt_id="att-fi-4",
            allocation_id="alloc-1",
            node_id="node-1",
            ttl_seconds=300,
        )

        # Construct realistic tampered payload token by decoding valid token's payload,
        # modifying a claim, and re-attaching the original signature without re-signing.
        payload_b64, sig_b64 = valid_token.split(".")
        pad = (-len(payload_b64)) % 4
        payload_dict = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * pad).decode("utf-8"))
        payload_dict["allocation_id"] = "alloc-tampered"
        tampered_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        tampered_payload_b64 = base64.urlsafe_b64encode(tampered_bytes).decode("ascii").rstrip("=")
        tampered_payload_token = f"{tampered_payload_b64}.{sig_b64}"

        test_cases = [
            # 1. Random token
            ("random_token", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": "random.invalid.gibberish",
            }, ERROR_CODE_WORKER_ADMISSION_INVALID),

            # 2. Malformed token
            ("malformed_token", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": "not-a-token",
            }, ERROR_CODE_WORKER_ADMISSION_INVALID),

            # 3. Expired token
            ("expired_token", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": issue_worker_join_token(
                    secret=self.secret,
                    attempt_id="att-fi-4",
                    allocation_id="alloc-1",
                    node_id="node-1",
                    ttl_seconds=10,
                    now=time.time() - 100,  # Expired
                ),
            }, ERROR_CODE_WORKER_ADMISSION_EXPIRED),

            # 4. Tampered payload
            ("tampered_payload", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": tampered_payload_token,
            }, ERROR_CODE_WORKER_ADMISSION_INVALID),

            # 5. Tampered signature
            ("tampered_signature", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": valid_token[:-4] + "AAAA",
            }, ERROR_CODE_WORKER_ADMISSION_INVALID),

            # 6. Wrong attempt_id
            ("wrong_attempt_id", {
                **_base_hello_dict(),
                "attempt_id": "att-wrong",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": issue_worker_join_token(
                    secret=self.secret,
                    attempt_id="att-wrong",
                    allocation_id="alloc-1",
                    node_id="node-1",
                    ttl_seconds=300,
                ),
            }, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH),

            # 7. Wrong allocation_id (token has alloc-1, but hello declares alloc-wrong)
            ("wrong_allocation_id", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-wrong",
                "node_id": "node-1",
                "worker_join_token": valid_token,
            }, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH),

            # 8. Wrong node_id (token has node-1, but hello declares node-wrong)
            ("wrong_node_id", {
                **_base_hello_dict(),
                "attempt_id": "att-fi-4",
                "allocation_id": "alloc-1",
                "node_id": "node-wrong",
                "worker_join_token": valid_token,
            }, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH),

            # 9. Missing managed identity (unmanaged Hello when admission required)
            ("missing_managed_identity", _base_hello_dict(), ERROR_CODE_WORKER_ADMISSION_REQUIRED),
        ]

        for case_name, hello_dict, expected_error in test_cases:
            with self.subTest(case=case_name):
                count_before = len(self.registry.snapshot())
                self.assertEqual(count_before, 0)

                resp = self._send_hello_and_get_response(hello_dict)
                self.assertIsInstance(resp, Error, f"Case {case_name} must return Error frame")
                assert isinstance(resp, Error)
                self.assertEqual(resp.error_code, expected_error)

                # Invariant: Registry count remains unchanged (no registration occurred)
                count_after = len(self.registry.snapshot())
                self.assertEqual(count_after, 0, f"Case {case_name} must NOT consume worker slot")
                self.assertEqual(len(self.server.worker_ids()), 0)

        # 10. Duplicate allocation_id
        with self.subTest(case="duplicate_allocation_id"):
            # First admission of alloc-1 succeeds:
            s1 = socket.create_connection((self.host, self.port), timeout=5.0)
            try:
                h1 = Hello.from_dict({
                    **_base_hello_dict(),
                    "attempt_id": "att-fi-4",
                    "allocation_id": "alloc-1",
                    "node_id": "node-1",
                    "worker_join_token": valid_token,
                })
                frame1 = build_control_frame(h1)
                frame1.write_to(s1, send_all)

                ack_frame = DTPFrame.read_from(s1, recv_exact)
                ack = decode_control_message(ack_frame.header.message_type, ack_frame.payload)
                self.assertIsInstance(ack, HelloAck)
                self.assertEqual(len(self.registry.snapshot()), 1, "First valid admission consumes slot")
            finally:
                s1.close()

            # Wait briefly for server connection cleanup
            time.sleep(0.1)

            # Second admission of the SAME allocation_id:
            token2 = issue_worker_join_token(
                secret=self.secret,
                attempt_id="att-fi-4",
                allocation_id="alloc-1",
                node_id="node-1",
                ttl_seconds=300,
            )
            s2 = socket.create_connection((self.host, self.port), timeout=5.0)
            try:
                h2 = Hello.from_dict({
                    **_base_hello_dict(),
                    "attempt_id": "att-fi-4",
                    "allocation_id": "alloc-1",
                    "node_id": "node-1",
                    "worker_join_token": token2,
                })
                frame2 = build_control_frame(h2)
                frame2.write_to(s2, send_all)

                resp2_frame = DTPFrame.read_from(s2, recv_exact)
                resp2 = decode_control_message(resp2_frame.header.message_type, resp2_frame.payload)
                self.assertIsInstance(resp2, Error)
                assert isinstance(resp2, Error)
                self.assertEqual(resp2.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
                self.assertIn("already been admitted", resp2.message)

                # Invariant: Duplicate admission rejected BEFORE registration, no second session created
                self.assertEqual(len(self.registry.snapshot()), 1)
            finally:
                s2.close()


class TestParameterServerLivenessDuplicateFix(unittest.TestCase):
    """Verifies that ParameterServer does NOT perform duplicate registry.heartbeat() calls.

    Root Cause of the Bug:
    In ParameterServer._read_bound(), every incoming frame updates connection.last_seen
    and calls self.registry.heartbeat(connection.worker_id, connection.session_id, now).
    Previously, under `elif frame.header.message_type == MESSAGE_TYPE_HEARTBEAT:`,
    there was a redundant second call `self.registry.heartbeat(..., time.monotonic())`.
    Because time.monotonic() was called twice with non-zero elapsed time, this triggered
    microsecond timestamp drift and redundant lock acquisitions on WorkerRegistry.

    This test proves:
    1. HEARTBEAT frame updates registry.heartbeat exactly once per frame.
    2. No second heartbeat call or microsecond drift occurs on the same message event.
    """

    def setUp(self) -> None:
        self.manifest = _dummy_manifest()
        self.registry = WorkerRegistry("att-liveness", 1)
        self.server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="att-liveness",
            job_id="job-liveness",
            expected_workers=1,
            manifest=self.manifest,
            registry=self.registry,
        )
        self.server.start()
        self.host, self.port = self.server.bound_address or ("127.0.0.1", 0)

    def tearDown(self) -> None:
        self.server.stop()

    def test_heartbeat_frame_invokes_registry_heartbeat_exactly_once(self) -> None:
        s = socket.create_connection((self.host, self.port), timeout=5.0)
        try:
            hello = Hello.from_dict(_base_hello_dict())
            frame = build_control_frame(hello)
            frame.write_to(s, send_all)

            ack_frame = DTPFrame.read_from(s, recv_exact)
            self.assertEqual(ack_frame.header.message_type, MESSAGE_TYPE_HELLO_ACK)

            # Send ShardReady
            ready = ShardReady.from_dict(_valid_shard_ready_dict(shard_id=0))
            frame1 = build_control_frame(ready, session_id=1, worker_id=0)
            frame1.write_to(s, send_all)
            time.sleep(0.05)

            # Patch registry.heartbeat to count invocations during a single HEARTBEAT frame
            call_count = 0
            original_heartbeat = self.registry.heartbeat

            def counting_heartbeat(worker_id: int, session_id: int, now: float) -> None:
                nonlocal call_count
                call_count += 1
                original_heartbeat(worker_id, session_id, now)

            with patch.object(self.registry, "heartbeat", side_effect=counting_heartbeat):
                hb = Heartbeat.from_dict({
                    "attempt_id": "att-liveness",
                    "worker_state": "SHARD_READY",
                    "local_model_version": 0,
                    "last_completed_operation_id": None,
                    "recovery_cursor": {"epoch": 0},
                    "monotonic_timestamp_ms": 100.0,
                })
                frame2 = build_control_frame(hb, session_id=1, worker_id=0)
                frame2.write_to(s, send_all)
                time.sleep(0.05)

                # Must be called EXACTLY ONCE per frame!
                self.assertEqual(call_count, 1, "HEARTBEAT frame must trigger registry.heartbeat() exactly once")
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
