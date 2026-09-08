"""Loopback integration tests for DTP/1 and MCP/1 connection endpoints.

Exercises ParameterServer <-> WorkerClient and ManagementEndpoint <->
RuntimeGateway over real loopback TCP sockets (ephemeral ports), stdlib only.
"""

from __future__ import annotations

import queue
import socket
import struct
import unittest

from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_protocol.messages import McpEnvelope
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_HELLO_ACK,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
)
from pbl4.protocol.messages import build_frame
from pbl4.runtime.management_endpoint import (
    ManagementConnection,
    ManagementEndpoint,
)
from pbl4.runtime.parameter_server import ParameterServer, WorkerConnection
from pbl4.worker.worker_client import WorkerClient


def make_envelope(**overrides: object) -> McpEnvelope:
    fields: dict[str, object] = {
        "message_type": "backend.command",
        "message_id": "msg-0001",
        "correlation_id": "op-0001",
        "sent_at": "2026-09-08T00:00:00+00:00",
        "runtime_instance_id": "runtime-1",
        "payload": {"action": "QUERY_STATE"},
    }
    fields.update(overrides)
    return McpEnvelope(**fields)


class ParameterServerLoopbackTest(unittest.TestCase):
    def test_two_workers_hello_and_reply_over_tcp(self) -> None:
        received: queue.Queue[DTPFrame] = queue.Queue()
        server = ParameterServer("127.0.0.1", 0)
        next_worker_rank = 0

        def on_frame(connection: WorkerConnection, frame: DTPFrame) -> None:
            nonlocal next_worker_rank
            received.put(frame)
            if frame.header.message_type == MESSAGE_TYPE_HELLO:
                assigned_session_id = 100 + next_worker_rank
                assigned_worker_id = next_worker_rank
                next_worker_rank += 1
                reply = build_frame(
                    MESSAGE_TYPE_HELLO_ACK,
                    session_id=assigned_session_id,
                    worker_id=assigned_worker_id,
                )
                server.send_frame(connection, reply)

        server.on_frame = on_frame
        server.start()
        port = server.bound_address[1]
        workers: list[WorkerClient] = []
        try:
            for _ in range(2):
                worker = WorkerClient("127.0.0.1", port, timeout=5.0)
                worker.connect()
                worker.send_hello()
                workers.append(worker)
            for index, worker in enumerate(workers):
                reply = worker.recv_frame()
                self.assertEqual(reply.header.message_type, MESSAGE_TYPE_HELLO_ACK)
                self.assertEqual(reply.header.session_id, 100 + index)
                self.assertEqual(reply.header.worker_id, index)
            hello_frames = [received.get(timeout=5.0) for _ in range(2)]
            for frame in hello_frames:
                self.assertEqual(frame.header.message_type, MESSAGE_TYPE_HELLO)
                self.assertEqual(frame.header.session_id, UNBOUND_SESSION)
                self.assertEqual(frame.header.worker_id, UNASSIGNED_WORKER_ID)
        finally:
            for worker in workers:
                worker.close()
            server.stop()

    def test_malformed_frame_closes_only_offending_connection(self) -> None:
        server = ParameterServer("127.0.0.1", 0)
        server.on_frame = lambda connection, frame: None
        server.start()
        port = server.bound_address[1]
        try:
            raw = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            raw.sendall(b"XXXX" + bytes(44))
            self.assertEqual(raw.recv(1), b"")
            raw.close()

            # A healthy worker must still be served after the violation.
            worker = WorkerClient("127.0.0.1", port, timeout=5.0)
            worker.connect()
            worker.send_hello()
            worker.close()
        finally:
            server.stop()


class ManagementEndpointLoopbackTest(unittest.TestCase):
    def test_gateway_roundtrip_and_violation_isolation(self) -> None:
        endpoint = ManagementEndpoint("127.0.0.1", 0)
        received: queue.Queue[McpEnvelope] = queue.Queue()

        def on_message(connection: ManagementConnection, envelope: McpEnvelope) -> None:
            received.put(envelope)
            endpoint.send_message(
                connection,
                McpEnvelope(
                    message_type="runtime.ack",
                    message_id=f"ack-for-{envelope.message_id}",
                    correlation_id=envelope.message_id,
                    sent_at=envelope.sent_at,
                    runtime_instance_id="runtime-1",
                    payload={"accepted": True},
                ),
            )

        endpoint.on_message = on_message
        endpoint.start()
        port = endpoint.bound_address[1]
        try:
            gateway = RuntimeGateway("127.0.0.1", port, timeout=5.0)
            gateway.connect()
            gateway.send_message(make_envelope(payload={"action": "ABORT"}))
            ack = gateway.recv_message()
            self.assertEqual(ack.message_type, "runtime.ack")
            self.assertEqual(ack.correlation_id, "msg-0001")
            self.assertTrue(ack.payload["accepted"])
            inbound = received.get(timeout=5.0)
            self.assertEqual(inbound.payload["action"], "ABORT")

            # Invalid JSON body must close only the offending connection.
            raw = socket.create_connection(("127.0.0.1", port), timeout=5.0)
            raw.sendall(struct.pack(">I", 4) + b"nope")
            self.assertEqual(raw.recv(1), b"")
            raw.close()

            # The healthy gateway connection must still work afterwards.
            gateway.send_message(make_envelope(message_id="msg-0002"))
            self.assertEqual(gateway.recv_message().correlation_id, "msg-0002")
            gateway.close()
        finally:
            endpoint.stop()


if __name__ == "__main__":
    unittest.main()
