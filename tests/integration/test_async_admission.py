"""Managed rejoin is local, attempt-scoped and cannot replace a live session."""

import contextlib
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.common.worker_admission import issue_worker_join_token, verify_worker_join_token
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.worker_registry import WorkerRegistry
from pbl4.worker.worker_client import WorkerClient


def test_expired_known_credential_rejoins_but_replay_cannot_evict_session(monkeypatch):
    import pbl4.runtime.parameter_server as server_module

    now, checks = [100], []

    def verify(**kwargs):
        checks.append(True)
        return verify_worker_join_token(**kwargs, now=now[0])

    monkeypatch.setattr(server_module, "verify_worker_join_token", verify)
    manifest = ParameterManifest.create([ParameterEntry(0, "weight", (2,), "float32", 2, 0, 8)])
    registry = WorkerRegistry("attempt", 1, allow_rejoin=True)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id="attempt",
        job_id="job",
        expected_workers=1,
        manifest=manifest,
        registry=registry,
        training_strategy="async_sgd",
        worker_admission_secret="secret",
        require_worker_admission=True,
        admission_open=lambda: now[0] < 2000,
    )
    server.start()
    token = issue_worker_join_token(
        "secret", "attempt", "allocation", "node", now=100, ttl_seconds=1
    )
    clients = []

    def client(identity="same-process", credential=token, allocation="allocation"):
        value = WorkerClient(
            *server.bound_address,
            node_label="node",
            manifest=manifest,
            client_instance_id=identity,
            attempt_id="attempt",
            allocation_id=allocation,
            node_id="node",
            worker_join_token=credential,
        )
        clients.append(value)
        return value

    try:
        first = client()
        first.connect()
        old_session = first.session_id
        server.fence(0, old_session)
        now[0] = 1000
        replacement = client()
        replacement.connect()
        assert replacement.session_id != old_session
        assert len(checks) == 1  # Expiry applies to initial admission, not this known binding.
        for replay in (client(), client(identity="different-process")):
            with pytest.raises((ProtocolError, TransportError)):
                replay.connect()
        assert registry.snapshot()[0].session_id == replacement.session_id
        assert replacement.connected
        # A different allocation with an expired token is never a rejoin.
        bad = issue_worker_join_token("secret", "attempt", "other", "node", now=100, ttl_seconds=1)
        with pytest.raises(ProtocolError, match="EXPIRED"):
            client(credential=bad, allocation="other").connect()
        now[0] = 2000
        with pytest.raises(ProtocolError, match="admission is closed"):
            client().connect()
        assert registry.snapshot()[0].session_id == replacement.session_id
    finally:
        for value in clients:
            value.disconnect()
        server.stop()


def test_new_heartbeat_invalidates_a_pending_timeout_observation():
    registry = WorkerRegistry("attempt", 1, allow_rejoin=True)
    registry.register(1, 0)
    observed = registry.snapshot()[0]
    registry.heartbeat(0, 1, 10)
    assert not registry.disconnect_if_unchanged(0, 1, observed.last_heartbeat_at, 11)
    assert registry.disconnect_if_unchanged(0, 1, 10, 11)
    assert not registry.disconnect_if_unchanged(0, 1, 10, 12)


def test_stalled_socket_write_is_bounded_without_blocking_the_supervisor():
    manifest = ParameterManifest.create([ParameterEntry(0, "weight", (2,), "float32", 2, 0, 8)])
    client = WorkerClient("127.0.0.1", 1, node_label="worker", manifest=manifest)
    sender, receiver = socket.socketpair()
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    client._transport._sock = sender
    client._write_timeout_seconds = 0.1
    entered = threading.Event()

    def write(sock, send):
        entered.set()
        for _ in range(4096):
            send(sock, b"x" * 8192)

    def blocked_send():
        with contextlib.suppress(TransportError):
            client._write_frame(sender, SimpleNamespace(write_to=write))

    task = threading.Thread(target=blocked_send, daemon=True)
    try:
        task.start()
        assert entered.wait(2)
        deadline = time.monotonic() + 2
        while not client.write_timed_out(time.monotonic()):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert task.is_alive()  # The peer never reads; the send is actually blocked.
        client.disconnect()
        task.join(2)
        assert not task.is_alive()
        assert client._write_started is None
    finally:
        client.disconnect()
        receiver.close()
