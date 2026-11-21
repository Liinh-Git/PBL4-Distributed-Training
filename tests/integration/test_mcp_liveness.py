"""MCP must recover from silent partitions that leave TCP sockets open."""

import contextlib
import select
import socket
import threading
import time

import pytest

from pbl4.management_backend.gateways.mcp_port import RealMcpClientPort
from pbl4.runtime.management_endpoint import ManagementEndpoint


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.005)
    assert predicate()


class PartitionProxy:
    """Drop selected directions without closing either peer's TCP socket."""

    def __init__(self, target):
        self.target = target
        self.drop = set()
        self.stop = threading.Event()
        self.sockets = []
        self.threads = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.05)
        self.address = self.listener.getsockname()
        self.accepted = 0
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while not self.stop.is_set():
            try:
                downstream, _ = self.listener.accept()
            except (TimeoutError, OSError):
                continue
            upstream = socket.create_connection(self.target, timeout=1)
            self.sockets.extend([downstream, upstream])
            self.accepted += 1
            thread = threading.Thread(target=self.forward, args=(downstream, upstream), daemon=True)
            self.threads.append(thread)
            thread.start()

    def forward(self, downstream, upstream):
        try:
            while not self.stop.is_set():
                readable, _, _ = select.select([downstream, upstream], [], [], 0.05)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    direction = "request" if source is downstream else "response"
                    if direction not in self.drop:
                        target = upstream if source is downstream else downstream
                        target.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (downstream, upstream):
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)
                sock.close()

    def close(self):
        self.stop.set()
        self.listener.close()
        self.thread.join(2)
        for sock in self.sockets:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        for thread in self.threads:
            thread.join(2)


@pytest.mark.parametrize("directions", [{"request"}, {"response"}, {"request", "response"}])
def test_silent_partition_closes_old_connection_and_reconnects(directions):
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    endpoint.start()
    proxy = PartitionProxy(endpoint.bound_address)
    client = RealMcpClientPort(
        *proxy.address,
        timeout=0.3,
        reconnect_interval=0.05,
        probe_interval=0.05,
        probe_timeout=0.15,
    )
    disconnected = threading.Event()
    received = []

    def inbound(kind, payload):
        received.append(kind)
        if kind == "DISCONNECTED":
            disconnected.set()

    client.set_message_handler(inbound)
    try:
        assert client.connect()
        old = client._client
        proxy.drop = directions
        started = time.monotonic()
        assert disconnected.wait(1)
        assert time.monotonic() - started < 0.8
        assert not client.is_connected
        assert old is not None and not old.connected
        assert not client._waiters
        assert received.count("DISCONNECTED") == 1

        proxy.drop = set()
        client.start_reconnecting()
        client.start_reconnecting()
        wait_until(lambda: client.is_connected)
        assert proxy.accepted >= 2
        assert client._client is not old
        assert client.request_state()["runtime_instance_id"] == endpoint.runtime_instance_id
        # A late reader/timeout from the old connection must not close the new one.
        client._connection_lost(old)
        assert client.is_connected
        client.disconnect()
        accepted = proxy.accepted
        assert not threading.Event().wait(0.15)
        assert proxy.accepted == accepted
        assert not client.is_connected
    finally:
        client.disconnect()
        client._dispatch_executor.shutdown(wait=True)
        proxy.close()
        endpoint.stop()


def test_healthy_idle_runtime_is_probed_without_projecting_snapshots():
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    endpoint.start()
    client = RealMcpClientPort(
        *endpoint.bound_address,
        probe_interval=0.02,
        probe_timeout=0.2,
    )
    seen = []
    client.set_message_handler(lambda kind, payload: seen.append(kind))
    try:
        assert client.connect()
        assert not threading.Event().wait(0.2)
        assert client.is_connected
        assert seen == ["MGMT_HELLO_ACK"]
        assert not client._waiters
    finally:
        client.disconnect()
        client._dispatch_executor.shutdown(wait=True)
        endpoint.stop()


def test_request_state_timeout_invalidates_connection():
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    endpoint.start()
    proxy = PartitionProxy(endpoint.bound_address)
    client = RealMcpClientPort(*proxy.address, timeout=0.1)
    try:
        assert client.connect()
        proxy.drop = {"response"}
        assert client.request_state() is None
        assert not client.is_connected
        assert not client._waiters
    finally:
        client.disconnect()
        client._dispatch_executor.shutdown(wait=True)
        proxy.close()
        endpoint.stop()


def test_probe_deadline_is_independent_of_blocked_projection_handler():
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    endpoint.start()
    proxy = PartitionProxy(endpoint.bound_address)
    client = RealMcpClientPort(
        *proxy.address,
        probe_interval=0.03,
        probe_timeout=0.1,
    )
    entered, release = threading.Event(), threading.Event()

    def blocked_handler(kind, payload):
        if kind == "MGMT_HELLO_ACK":
            entered.set()
            release.wait(2)

    client.set_message_handler(blocked_handler)
    try:
        assert client.connect()
        assert entered.wait(1)
        proxy.drop = {"request", "response"}
        wait_until(lambda: not client.is_connected, timeout=0.8)
        assert not client._waiters
    finally:
        release.set()
        client.disconnect()
        client._dispatch_executor.shutdown(wait=True)
        proxy.close()
        endpoint.stop()
