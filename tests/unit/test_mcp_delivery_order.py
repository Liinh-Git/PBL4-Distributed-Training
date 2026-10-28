"""Semantic handlers must preserve wire order while the reader stays independent."""

import threading
from unittest.mock import MagicMock

from pbl4.management_backend.gateways.mcp_port import RealMcpClientPort


def test_semantic_dispatch_does_not_overtake_blocked_event():
    port = RealMcpClientPort("127.0.0.1", 1)
    first_entered = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    delivered = []

    def handler(kind, payload):
        events = payload if isinstance(payload, list) else [payload]
        for ev in events:
            if ev["seq"] == 1:
                first_entered.set()
                assert release.wait(2)
            delivered.append(ev["seq"])
            if ev["seq"] == 2:
                second_done.set()

    port.set_message_handler(handler)
    try:
        for seq in [1, 2]:
            envelope = MagicMock(message_type="RUNTIME_EVENT")
            envelope.payload.to_dict.return_value = {"seq": seq}
            port._dispatch(envelope)
        assert first_entered.wait(1)
        assert not second_done.wait(0.05)
        release.set()
        assert second_done.wait(2)
        assert delivered == [1, 2]
    finally:
        release.set()
        port.disconnect()
