"""Protocol-only loopback tests with no Runtime/Backend production wiring."""

from __future__ import annotations

import socket
import unittest

from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import CorrelationTracker, McpEnvelope
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.messages import Hello, build_control_frame, decode_control_message
from pbl4.transport.framed_socket import recv_exact, send_all


class ProtocolLoopbackTest(unittest.TestCase):
    def test_dtp_control_frame_over_connected_peer_sockets(self) -> None:
        sender, receiver = socket.socketpair()
        try:
            message = Hello.from_dict(
                {
                    "node_label": "node",
                    "client_instance_id": "client",
                    "role": "worker",
                    "protocol_version": 1,
                    "framework_adapter": "pytorch_model_adapter_v1",
                    "supported_tensor_encoding": ["fp32_le_v1"],
                    "supported_strategy_capabilities": ["strict_bsp"],
                }
            )
            frame = build_control_frame(message)
            send_all(sender, frame.pack())
            received = DTPFrame.read_from(receiver, recv_exact)
            self.assertEqual(
                decode_control_message(received.header.message_type, received.payload),
                message,
            )
        finally:
            sender.close()
            receiver.close()

    def test_mcp_interleaved_event_and_correlated_response(self) -> None:
        sender, receiver = socket.socketpair()
        tracker = CorrelationTracker()
        request = McpEnvelope(
            message_type="GET_STATE",
            message_id="request",
            correlation_id=None,
            sent_at="2026-09-08T00:00:00Z",
            runtime_instance_id="runtime-1",
            payload={},
        )
        tracker.register_request(request)
        event = McpEnvelope(
            message_type="RUNTIME_EVENT",
            message_id="event",
            correlation_id=None,
            sent_at="2026-09-08T00:00:01Z",
            runtime_instance_id="runtime-1",
            payload={
                "attempt_id": "attempt",
                "job_id": "job",
                "runtime_event_seq": 1,
                "event_type": "worker.registered",
                "event_schema_version": 1,
                "occurred_at": "2026-09-08T00:00:01Z",
                "source_component": "runtime",
                "severity": "INFO",
                "details": {},
            },
        )
        snapshot = McpEnvelope(
            message_type="STATE_SNAPSHOT",
            message_id="snapshot",
            correlation_id="request",
            sent_at="2026-09-08T00:00:02Z",
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
                "captured_at": "2026-09-08T00:00:02Z",
            },
        )
        try:
            send_all(sender, McpCodec.encode(event) + McpCodec.encode(snapshot))
            self.assertIsNone(tracker.accept(McpCodec.read_message(receiver, recv_exact)))
            self.assertEqual(
                tracker.accept(McpCodec.read_message(receiver, recv_exact)), "GET_STATE"
            )
        finally:
            sender.close()
            receiver.close()


if __name__ == "__main__":
    unittest.main()
