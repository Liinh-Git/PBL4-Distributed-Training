"""Canonical DTP and MCP loopback smoke tests over real TCP sockets."""

from __future__ import annotations

import queue
import socket
import unittest

from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_protocol.messages import McpEnvelope
from pbl4.protocol.messages import (
    Hello,
    HelloAck,
    build_control_frame,
    decode_control_message,
)
from pbl4.runtime.management_endpoint import ManagementEndpoint
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.worker.worker_client import WorkerClient


def hello(node: str) -> Hello:
    return Hello.from_dict(
        {
            "node_label": node,
            "client_instance_id": f"{node}-instance",
            "role": "worker",
            "protocol_version": 1,
            "framework_adapter": "pytorch_model_adapter_v1",
            "supported_tensor_encoding": ["fp32_le_v1"],
            "supported_strategy_capabilities": ["strict_bsp"],
        }
    )


class DtpLoopbackTest(unittest.TestCase):
    def test_runtime_allocates_session_and_rank_after_unbound_hello(self) -> None:
        observed: queue.Queue[tuple[int, int]] = queue.Queue()
        server = ParameterServer("127.0.0.1", 0)
        next_rank = 0

        def on_frame(connection: object, frame: object) -> None:
            nonlocal next_rank
            message = decode_control_message(frame.header.message_type, frame.payload)
            self.assertIsInstance(message, Hello)
            self.assertEqual(frame.header.session_id, 0)
            rank = next_rank
            next_rank += 1
            session = 1001 + rank
            observed.put((session, rank))
            server.bind_identity(connection, session, rank)
            ack = HelloAck.from_dict(
                {
                    "attempt_id": "attempt",
                    "job_id": "job",
                    "session_id": str(session),
                    "worker_id": rank,
                    "expected_workers": 2,
                    "training_strategy": "strict_bsp",
                    "heartbeat_interval_ms": 5000,
                    "heartbeat_timeout_ms": 15000,
                    "tensor_encoding": "fp32_le_v1",
                    "max_tensor_chunk_bytes": 1048576,
                    "server_protocol_version": 1,
                }
            )
            server.send_frame(
                connection,
                build_control_frame(ack, session_id=session, worker_id=rank),
            )

        server.on_frame = on_frame
        server.start()
        workers: list[WorkerClient] = []
        try:
            port = server.bound_address[1]
            for index in range(2):
                worker = WorkerClient("127.0.0.1", port, timeout=5.0)
                worker.connect()
                worker.send_hello(hello(f"node-{index}"))
                workers.append(worker)
            for rank, worker in enumerate(workers):
                reply = worker.recv_frame()
                ack = decode_control_message(reply.header.message_type, reply.payload)
                self.assertIsInstance(ack, HelloAck)
                self.assertEqual(reply.header.session_id, 1001 + rank)
                self.assertEqual(reply.header.worker_id, rank)
                worker.bind_identity(reply.header.session_id, reply.header.worker_id)
            self.assertEqual({observed.get(timeout=2) for _ in workers}, {(1001, 0), (1002, 1)})
        finally:
            for worker in workers:
                worker.close()
            server.stop()

    def test_disconnect_notifies_runtime_with_bound_identity(self) -> None:
        disconnected: queue.Queue[tuple[int, int] | None] = queue.Queue()
        server = ParameterServer(
            "127.0.0.1",
            0,
            on_disconnect=lambda connection, _error: disconnected.put(connection.bound_identity),
        )

        def on_frame(connection: object, frame: object) -> None:
            self.assertIsInstance(
                decode_control_message(frame.header.message_type, frame.payload), Hello
            )
            server.bind_identity(connection, 2001, 0)

        server.on_frame = on_frame
        server.start()
        worker = WorkerClient("127.0.0.1", server.bound_address[1], timeout=5)
        try:
            worker.connect()
            worker.send_hello(hello("disconnecting"))
            worker.close()
            self.assertEqual(disconnected.get(timeout=2), (2001, 0))
        finally:
            worker.close()
            server.stop()

    def test_fake_registration_owner_does_not_reuse_dead_session_on_reconnect(self) -> None:
        sessions = iter((3001, 3002))
        server = ParameterServer("127.0.0.1", 0)

        def on_frame(connection: object, frame: object) -> None:
            self.assertIsInstance(
                decode_control_message(frame.header.message_type, frame.payload), Hello
            )
            session = next(sessions)
            server.bind_identity(connection, session, 0)
            ack = HelloAck.from_dict(
                {
                    "attempt_id": "attempt",
                    "job_id": "job",
                    "session_id": str(session),
                    "worker_id": 0,
                    "expected_workers": 1,
                    "training_strategy": "strict_bsp",
                    "heartbeat_interval_ms": 5000,
                    "heartbeat_timeout_ms": 15000,
                    "tensor_encoding": "fp32_le_v1",
                    "max_tensor_chunk_bytes": 1048576,
                    "server_protocol_version": 1,
                }
            )
            server.send_frame(
                connection,
                build_control_frame(ack, session_id=session, worker_id=0),
            )

        server.on_frame = on_frame
        server.start()
        assigned: list[int] = []
        try:
            for _ in range(2):
                worker = WorkerClient("127.0.0.1", server.bound_address[1], timeout=5)
                worker.connect()
                worker.send_hello(hello("same-client"))
                assigned.append(worker.recv_frame().header.session_id)
                worker.close()
            self.assertEqual(assigned, [3001, 3002])
        finally:
            server.stop()

    def test_bad_magic_closes_only_offending_connection(self) -> None:
        server = ParameterServer("127.0.0.1", 0)
        server.start()
        try:
            port = server.bound_address[1]
            bad = socket.create_connection(("127.0.0.1", port), timeout=5)
            bad.sendall(b"FAIL" + bytes(44))
            self.assertEqual(bad.recv(1), b"")
            bad.close()
            healthy = WorkerClient("127.0.0.1", port, timeout=5)
            healthy.connect()
            healthy.send_hello(hello("healthy"))
            healthy.close()
        finally:
            server.stop()


class McpLoopbackTest(unittest.TestCase):
    def test_get_state_response_uses_correlation(self) -> None:
        endpoint = ManagementEndpoint("127.0.0.1", 0)

        def on_message(connection: object, request: McpEnvelope) -> None:
            response = McpEnvelope(
                message_type="STATE_SNAPSHOT",
                message_id="response",
                correlation_id=request.message_id,
                sent_at="2026-09-08T00:00:01Z",
                runtime_instance_id="runtime-1",
                payload={
                    "runtime_instance_id": "runtime-1",
                    "active_job_id": None,
                    "active_attempt_id": None,
                    "attempt_state": None,
                    "training_strategy": None,
                    "checkpoint_policy": None,
                    "epoch": None,
                    "current_operation_id": None,
                    "current_batch_ordinal": None,
                    "model_version": None,
                    "workers": [],
                    "strategy_state": {},
                    "checkpoint_state": None,
                    "latest_checkpoint_id": None,
                    "recovery_cursor": {},
                    "dataset_build_id": None,
                    "dataset_manifest_hash": None,
                    "last_runtime_event_seq": 0,
                    "management_event_gap_count": 0,
                    "captured_at": "2026-09-08T00:00:01Z",
                },
            )
            endpoint.send_message(connection, response)

        endpoint.on_message = on_message
        endpoint.start()
        gateway = RuntimeGateway("127.0.0.1", endpoint.bound_address[1], timeout=5)
        try:
            gateway.connect()
            request = McpEnvelope(
                message_type="GET_STATE",
                message_id="request",
                correlation_id=None,
                sent_at="2026-09-08T00:00:00Z",
                runtime_instance_id="runtime-1",
                payload={},
            )
            gateway.send_message(request)
            response = gateway.recv_message()
            self.assertEqual(response.message_type, "STATE_SNAPSHOT")
            self.assertEqual(response.correlation_id, "request")
        finally:
            gateway.close()
            endpoint.stop()


if __name__ == "__main__":
    unittest.main()
