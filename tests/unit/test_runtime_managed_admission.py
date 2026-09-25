"""Unit tests for Phase 2: DTP Hello extension, Runtime admission gate, and Worker identity.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Section 14
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
import unittest

from pbl4.common.errors import ProtocolError
from pbl4.common.worker_admission import issue_worker_join_token
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    UNASSIGNED_WORKER_ID,
)
from pbl4.protocol.messages import (
    ERROR_CODE_WORKER_ADMISSION_EXPIRED,
    ERROR_CODE_WORKER_ADMISSION_INVALID,
    ERROR_CODE_WORKER_ADMISSION_REQUIRED,
    ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH,
    Error,
    Hello,
    HelloAck,
    build_control_frame,
    decode_control_message,
)
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.worker_registry import WorkerRegistry
from pbl4.transport.framed_socket import recv_exact
from pbl4.worker.config import WorkerConfig
from pbl4.worker.worker_client import WorkerClient


def dummy_manifest() -> ParameterManifest:
    return ParameterManifest.create([ParameterEntry(0, "weight", (3,), "float32", 3, 0, 12)])


class TestHelloManagedValidation(unittest.TestCase):
    """Test cases 1 - 7: Hello managed identity all-or-none validation."""

    def _base_hello_dict(self) -> dict[str, object]:
        return {
            "node_label": "node-1",
            "client_instance_id": "client-uuid-1",
            "role": "worker",
            "protocol_version": 1,
            "framework_adapter": "pytorch",
            "supported_tensor_encoding": ["fp32_le_v1"],
            "supported_strategy_capabilities": ["strict_bsp"],
        }

    def test_1_unmanaged_hello_valid(self) -> None:
        hello = Hello.from_dict(self._base_hello_dict())
        self.assertFalse(hello.is_managed)
        self.assertNotIn("attempt_id", hello.to_dict())

    def test_2_managed_hello_valid(self) -> None:
        d = self._base_hello_dict()
        d.update(
            {
                "attempt_id": "attempt-1",
                "allocation_id": "alloc-1",
                "node_id": "node-1",
                "worker_join_token": "token.sig",
            }
        )
        hello = Hello.from_dict(d)
        self.assertTrue(hello.is_managed)
        self.assertEqual(hello.attempt_id, "attempt-1")
        self.assertEqual(hello.allocation_id, "alloc-1")
        self.assertEqual(hello.node_id, "node-1")
        self.assertEqual(hello.worker_join_token, "token.sig")
        self.assertIn("***REDACTED***", repr(hello))
        self.assertNotIn("token.sig", repr(hello))

    def test_3_missing_attempt_id_rejected(self) -> None:
        d = self._base_hello_dict()
        d.update({"allocation_id": "a", "node_id": "n", "worker_join_token": "t"})
        with self.assertRaises(ProtocolError) as ctx:
            Hello.from_dict(d)
        self.assertIn("all-or-none", str(ctx.exception))

    def test_4_missing_allocation_id_rejected(self) -> None:
        d = self._base_hello_dict()
        d.update({"attempt_id": "att", "node_id": "n", "worker_join_token": "t"})
        with self.assertRaises(ProtocolError) as ctx:
            Hello.from_dict(d)
        self.assertIn("all-or-none", str(ctx.exception))

    def test_5_missing_node_id_rejected(self) -> None:
        d = self._base_hello_dict()
        d.update({"attempt_id": "att", "allocation_id": "a", "worker_join_token": "t"})
        with self.assertRaises(ProtocolError) as ctx:
            Hello.from_dict(d)
        self.assertIn("all-or-none", str(ctx.exception))

    def test_6_missing_token_rejected(self) -> None:
        d = self._base_hello_dict()
        d.update({"attempt_id": "att", "allocation_id": "a", "node_id": "n"})
        with self.assertRaises(ProtocolError) as ctx:
            Hello.from_dict(d)
        self.assertIn("all-or-none", str(ctx.exception))

    def test_7_managed_fields_partial_combinations(self) -> None:
        for fields in [
            {"attempt_id": "att"},
            {"allocation_id": "a"},
            {"node_id": "n"},
            {"worker_join_token": "t"},
            {"attempt_id": "att", "allocation_id": "a"},
        ]:
            d = self._base_hello_dict()
            d.update(fields)
            with self.subTest(fields=fields):
                with self.assertRaises(ProtocolError) as ctx:
                    Hello.from_dict(d)
                self.assertIn("all-or-none", str(ctx.exception))


class TestRuntimeAdmissionGate(unittest.TestCase):
    """Runtime admission verification, ordering, and duplicate rejection."""

    def setUp(self) -> None:
        self.secret = "admission-secret-key-123"
        self.attempt_id = "attempt-test-01"
        self.allocation_id = "alloc-test-01"
        self.node_id = "node-test-01"
        self.registry = WorkerRegistry(self.attempt_id, 1)
        self.server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id=self.attempt_id,
            job_id="job-test-01",
            expected_workers=1,
            manifest=dummy_manifest(),
            registry=self.registry,
            worker_admission_secret=self.secret,
            require_worker_admission=True,
        )

    def _send_hello_and_get_reply(
        self, server_sock: socket.socket, client_sock: socket.socket, hello_msg: Hello
    ):
        # Run server._serve_connection in background thread
        thread = threading.Thread(
            target=self.server._serve_connection,
            args=(server_sock, ("127.0.0.1", 12345)),
            daemon=True,
        )
        thread.start()

        # Send Hello frame from client
        frame = build_control_frame(hello_msg, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
        frame.write_to(client_sock, lambda s, b: s.sendall(b))

        # Read reply from client socket
        try:
            frame = DTPFrame.read_from(client_sock, recv_exact)
            reply = decode_control_message(frame.header.message_type, frame.payload)
            return reply
        except Exception:
            return None
        finally:
            for conn in list(self.server._connections.values()):
                conn.terminal_stop_sent = True
            thread.join(timeout=1.0)

    def _make_valid_hello(
        self, allocation_id: str | None = None, exp_offset: float = 600.0
    ) -> Hello:
        alloc = allocation_id or self.allocation_id
        token = issue_worker_join_token(
            self.secret,
            self.attempt_id,
            alloc,
            self.node_id,
            ttl_seconds=int(exp_offset),
        )
        return Hello.from_dict(
            {
                "node_label": "worker-node",
                "client_instance_id": "client-1",
                "role": "worker",
                "protocol_version": 1,
                "framework_adapter": "pytorch",
                "supported_tensor_encoding": ["fp32_le_v1"],
                "supported_strategy_capabilities": ["strict_bsp"],
                "attempt_id": self.attempt_id,
                "allocation_id": alloc,
                "node_id": self.node_id,
                "worker_join_token": token,
            }
        )

    def test_8_valid_token_successful_admission(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            hello = self._make_valid_hello()
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, HelloAck)
            self.assertEqual(len(self.server.worker_ids()), 1)
            self.assertEqual(len(self.registry.snapshot()), 1)
            snapshots = self.server.worker_snapshots()
            self.assertEqual(snapshots[0]["allocation_id"], self.allocation_id)
            self.assertEqual(snapshots[0]["node_id"], self.node_id)
        finally:
            s_sock.close()
            c_sock.close()

    def test_9_invalid_signature_rejected_before_register(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            # Token signed with wrong secret
            bad_token = issue_worker_join_token(
                "wrong-secret",
                self.attempt_id,
                self.allocation_id,
                self.node_id,
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": self.allocation_id,
                    "node_id": self.node_id,
                    "worker_join_token": bad_token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            self.assertEqual(reply.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
            # Worker count must NOT increase
            self.assertEqual(len(self.server.worker_ids()), 0)
            self.assertEqual(len(self.registry.snapshot()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_10_expired_token_rejected_before_register(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            expired_token = issue_worker_join_token(
                self.secret,
                self.attempt_id,
                self.allocation_id,
                self.node_id,
                ttl_seconds=10,
                now=time.time() - 20,
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": self.allocation_id,
                    "node_id": self.node_id,
                    "worker_join_token": expired_token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            self.assertEqual(reply.error_code, ERROR_CODE_WORKER_ADMISSION_EXPIRED)
            self.assertEqual(len(self.server.worker_ids()), 0)
            self.assertEqual(len(self.registry.snapshot()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_11_wrong_attempt_rejected(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            token = issue_worker_join_token(
                self.secret,
                "other-attempt",
                self.allocation_id,
                self.node_id,
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": "other-attempt",
                    "allocation_id": self.allocation_id,
                    "node_id": self.node_id,
                    "worker_join_token": token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            self.assertEqual(reply.error_code, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH)
            self.assertEqual(len(self.server.worker_ids()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_12_wrong_allocation_rejected(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            # Token generated for alloc-A but hello claims alloc-B
            token = issue_worker_join_token(
                self.secret,
                self.attempt_id,
                "alloc-A",
                self.node_id,
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": "alloc-B",
                    "node_id": self.node_id,
                    "worker_join_token": token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            self.assertEqual(reply.error_code, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH)
            self.assertEqual(len(self.server.worker_ids()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_13_wrong_node_rejected(self) -> None:
        s_sock, c_sock = socket.socketpair()
        try:
            token = issue_worker_join_token(
                self.secret,
                self.attempt_id,
                self.allocation_id,
                "node-A",
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": self.allocation_id,
                    "node_id": "node-B",
                    "worker_join_token": token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            self.assertEqual(reply.error_code, ERROR_CODE_WORKER_ADMISSION_SCOPE_MISMATCH)
            self.assertEqual(len(self.server.worker_ids()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_14_and_15_admission_failure_before_register_ordering(self) -> None:
        """Prove with a spy/mock that verify happens and fails before register is called."""
        s_sock, c_sock = socket.socketpair()
        try:
            original_register = self.registry.register
            register_called = []

            def spy_register(*args, **kwargs):
                register_called.append(True)
                return original_register(*args, **kwargs)

            self.registry.register = spy_register

            bad_token = issue_worker_join_token(
                "invalid-secret", self.attempt_id, self.allocation_id, self.node_id
            )
            hello = Hello.from_dict(
                {
                    "node_label": "worker-node",
                    "client_instance_id": "client-1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": self.allocation_id,
                    "node_id": self.node_id,
                    "worker_join_token": bad_token,
                }
            )
            reply = self._send_hello_and_get_reply(s_sock, c_sock, hello)
            self.assertIsInstance(reply, Error)
            # Register was NEVER called!
            self.assertEqual(len(register_called), 0)
            self.assertEqual(len(self.registry.snapshot()), 0)
        finally:
            s_sock.close()
            c_sock.close()

    def test_16_17_18_duplicate_allocation_rejection(self) -> None:
        """Keep one allocation id admitted after acceptance and disconnect."""
        # 16. First admission accepted
        s1, c1 = socket.socketpair()
        try:
            hello = self._make_valid_hello("alloc-fixed")
            reply1 = self._send_hello_and_get_reply(s1, c1, hello)
            self.assertIsInstance(reply1, HelloAck)
            self.assertEqual(len(self.server.worker_ids()), 1)
        finally:
            s1.close()
            c1.close()

        # 17. Second admission of same allocation_id rejected
        s2, c2 = socket.socketpair()
        try:
            hello2 = self._make_valid_hello("alloc-fixed")
            reply2 = self._send_hello_and_get_reply(s2, c2, hello2)
            self.assertIsInstance(reply2, Error)
            self.assertEqual(reply2.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
            self.assertIn("already been admitted", reply2.message)
        finally:
            s2.close()
            c2.close()

        # 18. Disconnect old session, third connection still rejected
        s3, c3 = socket.socketpair()
        try:
            hello3 = self._make_valid_hello("alloc-fixed")
            reply3 = self._send_hello_and_get_reply(s3, c3, hello3)
            self.assertIsInstance(reply3, Error)
            self.assertEqual(reply3.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
        finally:
            s3.close()
            c3.close()

    def test_concurrent_duplicate_allocation_admits_exactly_once(self) -> None:
        """Concurrent HELLO messages cannot race past allocation idempotency."""
        pairs = [socket.socketpair(), socket.socketpair()]
        threads: list[threading.Thread] = []
        barrier = threading.Barrier(3)

        def send_hello(client_sock: socket.socket) -> None:
            barrier.wait()
            build_control_frame(
                self._make_valid_hello("alloc-concurrent"),
                session_id=0,
                worker_id=UNASSIGNED_WORKER_ID,
            ).write_to(client_sock, lambda sock, payload: sock.sendall(payload))

        try:
            for index, (server_sock, client_sock) in enumerate(pairs):
                client_sock.settimeout(2.0)
                thread = threading.Thread(
                    target=self.server._serve_connection,
                    args=(server_sock, ("127.0.0.1", 20000 + index)),
                    daemon=True,
                )
                thread.start()
                threads.append(thread)
                threading.Thread(
                    target=send_hello,
                    args=(client_sock,),
                    daemon=True,
                ).start()

            barrier.wait()
            replies = [
                decode_control_message(frame.header.message_type, frame.payload)
                for frame in (DTPFrame.read_from(client, recv_exact) for _, client in pairs)
            ]

            assert sum(isinstance(reply, HelloAck) for reply in replies) == 1
            errors = [reply for reply in replies if isinstance(reply, Error)]
            assert len(errors) == 1
            assert errors[0].error_code == ERROR_CODE_WORKER_ADMISSION_INVALID
            assert "already been admitted" in errors[0].message
            assert len(self.registry.snapshot()) == 1
            assert self.server._admitted_allocation_ids == {"alloc-concurrent"}
        finally:
            for connection in list(self.server._connections.values()):
                connection.terminal_stop_sent = True
            for server_sock, client_sock in pairs:
                with contextlib.suppress(OSError):
                    client_sock.shutdown(socket.SHUT_RDWR)
                server_sock.close()
                client_sock.close()
            for thread in threads:
                thread.join(timeout=1.0)


class TestRuntimeModes(unittest.TestCase):
    """Test cases 19 - 23: Runtime mode handling (managed vs explicit unmanaged mode)."""

    def setUp(self) -> None:
        self.secret = "mode-test-secret"
        self.attempt_id = "attempt-mode"
        self.manifest = dummy_manifest()

    def test_19_require_admission_missing_secret_fails_on_connection(self) -> None:
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id=self.attempt_id,
            job_id="job-1",
            expected_workers=1,
            manifest=self.manifest,
            registry=WorkerRegistry(self.attempt_id, 1),
            worker_admission_secret=None,
            require_worker_admission=True,
        )
        s, c = socket.socketpair()
        try:
            token = issue_worker_join_token(self.secret, self.attempt_id, "alloc-1", "node-1")
            hello = Hello.from_dict(
                {
                    "node_label": "w",
                    "client_instance_id": "c1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": "alloc-1",
                    "node_id": "node-1",
                    "worker_join_token": token,
                }
            )
            # Background serve
            t = threading.Thread(
                target=server._serve_connection, args=(s, ("127.0.0.1", 1)), daemon=True
            )
            t.start()
            frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
            frame.write_to(c, lambda sk, b: sk.sendall(b))

            frame = DTPFrame.read_from(c, recv_exact)
            msg = decode_control_message(frame.header.message_type, frame.payload)
            self.assertIsInstance(msg, Error)
            self.assertEqual(msg.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
            for conn in list(server._connections.values()):
                conn.terminal_stop_sent = True
            t.join(timeout=1.0)
        finally:
            s.close()
            c.close()

    def test_20_require_admission_unmanaged_hello_rejected(self) -> None:
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id=self.attempt_id,
            job_id="job-1",
            expected_workers=1,
            manifest=self.manifest,
            registry=WorkerRegistry(self.attempt_id, 1),
            worker_admission_secret=self.secret,
            require_worker_admission=True,
        )
        s, c = socket.socketpair()
        try:
            unmanaged_hello = Hello.from_dict(
                {
                    "node_label": "w",
                    "client_instance_id": "c1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                }
            )
            t = threading.Thread(
                target=server._serve_connection, args=(s, ("127.0.0.1", 1)), daemon=True
            )
            t.start()
            frame = build_control_frame(
                unmanaged_hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID
            )
            frame.write_to(c, lambda sk, b: sk.sendall(b))

            frame_reply = DTPFrame.read_from(c, recv_exact)
            msg = decode_control_message(frame_reply.header.message_type, frame_reply.payload)
            self.assertIsInstance(msg, Error)
            self.assertEqual(msg.error_code, ERROR_CODE_WORKER_ADMISSION_REQUIRED)
            for conn in list(server._connections.values()):
                conn.terminal_stop_sent = True
            t.join(timeout=1.0)
        finally:
            s.close()
            c.close()

    def test_21_unmanaged_mode_accepts_unmanaged_hello(self) -> None:
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id=self.attempt_id,
            job_id="job-1",
            expected_workers=1,
            manifest=self.manifest,
            registry=WorkerRegistry(self.attempt_id, 1),
            worker_admission_secret=None,
            require_worker_admission=False,  # explicit unmanaged mode
        )
        s, c = socket.socketpair()
        try:
            unmanaged_hello = Hello.from_dict(
                {
                    "node_label": "w",
                    "client_instance_id": "c1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                }
            )
            t = threading.Thread(
                target=server._serve_connection, args=(s, ("127.0.0.1", 1)), daemon=True
            )
            t.start()
            frame = build_control_frame(
                unmanaged_hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID
            )
            frame.write_to(c, lambda sk, b: sk.sendall(b))

            frame_reply = DTPFrame.read_from(c, recv_exact)
            msg = decode_control_message(frame_reply.header.message_type, frame_reply.payload)
            self.assertIsInstance(msg, HelloAck)
            self.assertEqual(len(server.worker_ids()), 1)
            for conn in list(server._connections.values()):
                conn.terminal_stop_sent = True
            t.join(timeout=1.0)
        finally:
            s.close()
            c.close()

    def test_22_and_23_unmanaged_mode_verifies_managed_hello(self) -> None:
        """Verify managed credentials even in explicit unmanaged mode."""
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id=self.attempt_id,
            job_id="job-1",
            expected_workers=1,
            manifest=self.manifest,
            registry=WorkerRegistry(self.attempt_id, 1),
            worker_admission_secret=self.secret,
            require_worker_admission=False,  # unmanaged mode
        )
        # 22. Valid token in unmanaged mode -> accept
        s1, c1 = socket.socketpair()
        try:
            token = issue_worker_join_token(self.secret, self.attempt_id, "alloc-1", "node-1")
            hello1 = Hello.from_dict(
                {
                    "node_label": "w",
                    "client_instance_id": "c1",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": "alloc-1",
                    "node_id": "node-1",
                    "worker_join_token": token,
                }
            )
            t1 = threading.Thread(
                target=server._serve_connection, args=(s1, ("127.0.0.1", 1)), daemon=True
            )
            t1.start()
            build_control_frame(hello1).write_to(c1, lambda sk, b: sk.sendall(b))
            frame1 = DTPFrame.read_from(c1, recv_exact)
            msg1 = decode_control_message(frame1.header.message_type, frame1.payload)
            self.assertIsInstance(msg1, HelloAck)
            for conn in list(server._connections.values()):
                conn.terminal_stop_sent = True
            t1.join(timeout=1.0)
        finally:
            s1.close()
            c1.close()

        # 23. Invalid token in unmanaged mode -> reject
        s2, c2 = socket.socketpair()
        try:
            bad_token = issue_worker_join_token("wrong-key", self.attempt_id, "alloc-2", "node-2")
            hello2 = Hello.from_dict(
                {
                    "node_label": "w",
                    "client_instance_id": "c2",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                    "attempt_id": self.attempt_id,
                    "allocation_id": "alloc-2",
                    "node_id": "node-2",
                    "worker_join_token": bad_token,
                }
            )
            t2 = threading.Thread(
                target=server._serve_connection, args=(s2, ("127.0.0.1", 1)), daemon=True
            )
            t2.start()
            build_control_frame(hello2).write_to(c2, lambda sk, b: sk.sendall(b))
            frame2 = DTPFrame.read_from(c2, recv_exact)
            msg2 = decode_control_message(frame2.header.message_type, frame2.payload)
            self.assertIsInstance(msg2, Error)
            self.assertEqual(msg2.error_code, ERROR_CODE_WORKER_ADMISSION_INVALID)
            for conn in list(server._connections.values()):
                conn.terminal_stop_sent = True
            t2.join(timeout=1.0)
        finally:
            s2.close()
            c2.close()


class TestWorkerIdentityAndClient(unittest.TestCase):
    """Worker identity stability and initialization-seed requirements."""

    def test_24_worker_config_all_or_none(self) -> None:
        # All present
        c = WorkerConfig(
            node_label="nl",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            attempt_id="att",
            allocation_id="alloc",
            node_id="node",
            worker_join_token="token",
        )
        self.assertTrue(c.is_managed)

        # None present
        c_unmanaged = WorkerConfig(
            node_label="nl",
            runtime_host="127.0.0.1",
            runtime_port=9000,
        )
        self.assertFalse(c_unmanaged.is_managed)

        # Partial
        with self.assertRaises(ValueError):
            WorkerConfig(
                node_label="nl",
                runtime_host="127.0.0.1",
                runtime_port=9000,
                attempt_id="att",
            )

    def test_25_token_not_in_config_repr(self) -> None:
        secret_token = "secret-token-do-not-leak"
        c = WorkerConfig(
            node_label="nl",
            runtime_host="127.0.0.1",
            runtime_port=9000,
            attempt_id="att",
            allocation_id="alloc",
            node_id="node",
            worker_join_token=secret_token,
        )
        self.assertNotIn(secret_token, repr(c))

    def test_26_and_27_client_instance_id_generated_once_not_in_connect(self) -> None:
        manifest = dummy_manifest()
        fixed_uuid = "custom-fixed-uuid-1234"
        client = WorkerClient(
            "127.0.0.1",
            9000,
            node_label="worker-01",
            manifest=manifest,
            client_instance_id=fixed_uuid,
        )
        # client_instance_id is stable and matches passed ID
        self.assertEqual(client.client_instance_id, fixed_uuid)

        # An implicit client_instance_id is also stable for the client lifetime.
        client2 = WorkerClient(
            "127.0.0.1",
            9000,
            node_label="worker-01",
            manifest=manifest,
        )
        uuid_first = client2.client_instance_id
        self.assertIsInstance(uuid_first, str)
        self.assertTrue(len(uuid_first) > 10)
        # Calling multiple times doesn't change it
        self.assertEqual(client2.client_instance_id, uuid_first)

    def test_28_initialization_seed_still_required(self) -> None:
        from pbl4.worker.process import WorkerProcess

        config = WorkerConfig(
            node_label="nl",
            runtime_host="127.0.0.1",
            runtime_port=9000,
        )
        # Missing initialization_seed raises TypeError
        with self.assertRaises(TypeError):
            WorkerProcess(config)  # type: ignore[call-arg]

        # Valid initialization_seed works and process has client_instance_id
        proc = WorkerProcess(config, initialization_seed=42)
        self.assertIsInstance(proc.client_instance_id, str)
        self.assertTrue(len(proc.client_instance_id) > 10)


if __name__ == "__main__":
    unittest.main()
