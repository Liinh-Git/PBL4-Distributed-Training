"""Shared deterministic socket fakes for unit tests (stdlib only).

These fakes stand in for real sockets at the exact-byte primitive boundary so
partial reads/writes, EOF, and timeout behaviour can be exercised
deterministically without opening real network connections.
"""

from __future__ import annotations


class ScriptedRecvSocket:
    """recv() stub that yields queued chunks, honouring bufsize like a real socket."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = [bytes(chunk) for chunk in chunks]

    def recv(self, bufsize: int) -> bytes:
        if not self._chunks:
            return b""
        head = self._chunks[0]
        if len(head) <= bufsize:
            return self._chunks.pop(0)
        self._chunks[0] = head[bufsize:]
        return head[:bufsize]


class TimeoutRecvSocket:
    """recv() stub that always times out."""

    def recv(self, bufsize: int) -> bytes:
        raise TimeoutError()


class ResetRecvSocket:
    """recv() stub that always reports a connection reset."""

    def recv(self, bufsize: int) -> bytes:
        raise ConnectionResetError("connection reset by peer")


class ChunkedSendSocket:
    """send() stub that only accepts ``chunk_size`` bytes per call."""

    def __init__(self, chunk_size: int) -> None:
        self.chunk_size = chunk_size
        self.sent = bytearray()
        self.calls = 0

    def send(self, data: bytes) -> int:
        self.calls += 1
        piece = bytes(data[: self.chunk_size])
        self.sent.extend(piece)
        return len(piece)


class ZeroSendSocket:
    """send() stub that always reports an empty send."""

    def __init__(self) -> None:
        self.calls = 0

    def send(self, data: bytes) -> int:
        self.calls += 1
        return 0


class TimeoutSendSocket:
    """send() stub that always times out."""

    def send(self, data: bytes) -> int:
        raise TimeoutError()
