"""Unit tests for pbl4.transport exact-byte primitives (partial I/O, EOF, timeout)."""

from __future__ import annotations

import unittest

from pbl4.common.errors import TransportError
from pbl4.transport.framed_socket import recv_exact, send_all
from tests.unit.fake_sockets import (
    ChunkedSendSocket,
    ResetRecvSocket,
    ScriptedRecvSocket,
    TimeoutRecvSocket,
    TimeoutSendSocket,
    ZeroSendSocket,
)


class RecvExactTest(unittest.TestCase):
    def test_returns_exact_bytes_across_fragmented_chunks(self) -> None:
        sock = ScriptedRecvSocket([b"ab", b"cde", b"f"])
        self.assertEqual(recv_exact(sock, 6), b"abcdef")

    def test_handles_coalesced_chunk_larger_than_requested(self) -> None:
        sock = ScriptedRecvSocket([b"abcdef"])
        self.assertEqual(recv_exact(sock, 3), b"abc")
        self.assertEqual(recv_exact(sock, 3), b"def")

    def test_zero_bytes_returns_empty_without_calling_recv(self) -> None:
        self.assertEqual(recv_exact(ScriptedRecvSocket([]), 0), b"")

    def test_eof_mid_read_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            recv_exact(ScriptedRecvSocket([b"abc"]), 5)

    def test_timeout_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            recv_exact(TimeoutRecvSocket(), 4)

    def test_connection_reset_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            recv_exact(ResetRecvSocket(), 4)

    def test_negative_count_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            recv_exact(ScriptedRecvSocket([b"x"]), -1)


class SendAllTest(unittest.TestCase):
    def test_sends_all_bytes_despite_partial_writes(self) -> None:
        sock = ChunkedSendSocket(3)
        send_all(sock, b"abcdef")
        self.assertEqual(bytes(sock.sent), b"abcdef")
        self.assertEqual(sock.calls, 2)

    def test_empty_payload_sends_nothing(self) -> None:
        sock = ChunkedSendSocket(3)
        send_all(sock, b"")
        self.assertEqual(sock.calls, 0)

    def test_single_chunk_within_limit_is_one_call(self) -> None:
        sock = ChunkedSendSocket(16)
        send_all(sock, b"hello")
        self.assertEqual(bytes(sock.sent), b"hello")
        self.assertEqual(sock.calls, 1)

    def test_zero_byte_send_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            send_all(ZeroSendSocket(), b"abc")

    def test_timeout_raises_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            send_all(TimeoutSendSocket(), b"abc")


if __name__ == "__main__":
    unittest.main()
