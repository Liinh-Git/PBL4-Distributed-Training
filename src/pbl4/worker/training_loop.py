"""Training Loop — worker-side iterative training execution.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Worker iteration cycle:
  batch read -> forward -> loss -> backward -> export gradient ->
  send gradient -> receive updated parameters -> load parameters into model.
- Coordinating local ModelAdapter forward/backward execution.

MUST NOT OWN
------------
- Canonical optimizer updates: worker does NOT call optimizer.step() on the canonical model.
- Synchronization barrier decisions (owned by Runtime SynchronizationPolicy).
- Shard HTTP downloading (owned by ShardDownloader).
- Management telemetry persistence (Management Backend is not accessed as training path).

CRITICAL V1 INVARIANTS
----------------------
- Worker sends contributions and receives canonical parameters strictly via DTP/1.
- Canonical model mutation belongs exclusively to Parameter Server.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class TrainingLoop:
    """Worker-side training loop.

    Cycle: forward → loss → backward → export gradient →
           send gradient → receive parameters → load parameters.

    Does NOT call optimizer.step() on the canonical model.
    """

    def __init__(self) -> None:
        raise NotImplementedError
