"""Worker Client — DTP/1 network client connecting to Runtime Parameter Server.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Establishing and maintaining persistent DTP/1 TCP connection to Parameter Server.
- Transmitting HELLO, gradient payloads, and receiving parameter broadcast payloads.
- Dispatching protocol frames using DTPHeader and HeaderCodec.

MUST NOT OWN
------------
- Canonical model parameter updates or optimizer steps.
- Direct communication with Management Backend for training operations.
- Dataset shard downloading (owned by ShardDownloader via HTTP).
- Local training loop execution (owned by TrainingLoop).

CRITICAL V1 INVARIANTS
----------------------
- Worker-0 uses the identical DTP/1 TCP path as all other workers; no special-casing.
- Logical worker_id is assigned by Runtime during registration handshake.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class WorkerClient:
    """DTP/1 client for communicating with the Parameter Server.

    Worker-0 uses the same TCP path as every other worker.
    No special-casing for any worker index.
    """

    def __init__(self) -> None:
        raise NotImplementedError
