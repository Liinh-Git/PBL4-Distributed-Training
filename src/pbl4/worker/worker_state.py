"""Worker State — worker-side process lifecycle state.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Local worker process session lifecycle tracking according to the canonical
  Worker Session lifecycle:
  CONNECTING, REGISTERING, PROVISIONING, SHARD_READY, MODEL_SYNCING,
  READY, DISCONNECTED, FAILED.
- Distinguishing lifecycle state from transient computation activity or substates.

MUST NOT OWN
------------
- Global Attempt state machine (owned by Runtime Coordinator).
- Cluster-wide worker session registry (owned by Runtime WorkerRegistry).
- Global synchronization decisions.
- Introducing computation activity (such as TRAINING, STEP_COMPLETED, or COMPLETED)
  into the canonical Worker Session lifecycle field.

CRITICAL V1 INVARIANTS
----------------------
- Worker Session lifecycle state != computation activity/substate.
- Worker session transitions are strictly coordinated via DTP/1 with Runtime.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class WorkerState:
    """Worker-side state machine for tracking lifecycle state."""

    def __init__(self) -> None:
        raise NotImplementedError
