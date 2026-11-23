"""Connection deadlines and generation fencing independent of network timing."""

import threading
from unittest.mock import MagicMock

import pytest

from pbl4.common.errors import TransportError
from pbl4.management_backend.gateways.mcp_port import RealMcpClientPort


@pytest.mark.parametrize("option", ["probe_interval", "probe_timeout"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_probe_settings_must_be_positive_and_finite(option, value):
    with pytest.raises(ValueError):
        RealMcpClientPort("localhost", 1, **{option: value})


def test_request_deadline_closes_socket_even_when_write_is_blocked():
    port = RealMcpClientPort("localhost", 1)
    client = MagicMock()
    closed = threading.Event()
    client.disconnect.side_effect = closed.set
    port._runtime_instance_id = "runtime-test"
    port._client = client
    port._connected.set()

    def blocked_write(*args):
        assert closed.wait(1), "Deadline did not interrupt blocked write"
        raise TransportError("socket closed")

    port._write = blocked_write
    try:
        with pytest.raises(TransportError):
            port._request("GET_STATE", {}, timeout=0.03)
        assert closed.is_set()
        assert not port.is_connected
        assert not port._waiters
    finally:
        port.disconnect()
        port._dispatch_executor.shutdown(wait=True)


def test_old_dispatch_and_dataset_response_do_not_reach_new_connection():
    port = RealMcpClientPort("localhost", 1)
    old, new = MagicMock(), MagicMock()
    port._runtime_instance_id = "runtime-test"
    port._client = old
    port._connected.set()
    blocked = threading.Event()
    release = threading.Event()
    port._dispatch_executor.submit(lambda: (blocked.set(), release.wait(2)))
    assert blocked.wait(1)
    seen = []
    port.set_message_handler(lambda kind, payload: seen.append(kind))
    envelope = MagicMock(message_type="RUNTIME_EVENT")
    port._dispatch(envelope, old)
    port._connection_lost(old)
    port._client = new
    port._connected.set()
    port._connection_lost(old)
    try:
        # Resolver failure still produces a response, which must stay on old TCP.
        port._serve_dataset_resolution(MagicMock(message_id="old-request"), old)
        new.sock.send.assert_not_called()
        assert port.is_connected
        release.set()
        port._dispatch_executor.submit(lambda: None).result(1)
        assert seen == ["DISCONNECTED"]
    finally:
        release.set()
        port.disconnect()
        port._dispatch_executor.shutdown(wait=True)


def test_automatic_connect_cannot_restart_after_shutdown():
    port = RealMcpClientPort("localhost", 1)
    port.disconnect()
    assert not port._connect(automatic=True)
    assert port._closing.is_set()
    port._dispatch_executor.shutdown(wait=True)
