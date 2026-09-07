---
name: distributed-debug
description: >
  Diagnostic workflow for investigating distributed execution failures,
  hangs, deadlocks, and discrepancies using structured correlation tracing.
---

# Distributed Debug

## 1. When to Activate

Use this skill **EXCLUSIVELY AS A DIAGNOSTIC WORKFLOW** when investigating:
- Cluster hangs, deadlocks, or premature barrier releases
- Worker handshake, session rejection, or registration failures
- Gradient aggregation divergence or tensor transfer errors
- Parameter broadcast stall or missing `PARAMETER_APPLIED` acknowledgments
- Checkpoint persistence failures or recovery desynchronization

*(Do NOT auto-trigger this skill during routine feature implementation)*.

---

## 2. Canonical Source References

Consult the canonical technical documents registered in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):
- `[TRAINING_RUNTIME]`: Runtime state machines, coordinator flow, session lifecycle
- `[SYNC_STRICT_BSP]`: Barrier semantics, admission rules, and error codes
- `[DTP1]`: DTP/1 wire framing and socket expectations
- `[MCP1]`: MCP/1 telemetry stream and event sequence
- `[CHECKPOINT]`: Checkpoint durability contracts
- `[RECOVERY]`: Failure classification, retry boundaries, and resume into NEW Attempt

---

## 3. Core Principle: Find First Divergence

> [!CAUTION]
> **Anti-Pattern Warning**: Never attempt to "fix" distributed race conditions or timeouts by inserting arbitrary `sleep()`, randomly extending timeout thresholds, or adding blind retries. Locate the **exact first divergent event** across processes.

---

## 4. Correlation Identifiers

Align multi-process logs across Runtime, Workers, and Backend using canonical correlation fields:
- `job_id`: Top-level training job UUID
- `attempt_id`: Specific execution attempt UUID (attempts are immutable)
- `session_id`: Unique uint64 worker connection session ID
- `worker_id`: Logical worker rank assigned by Runtime
- `operation_id`: DTP/1 neutral 8-byte operation correlation identifier
- `step_id`: Step iteration index (Strict BSP projection)
- `model_version`: Monotonic parameter publication counter
- `tensor_id`: Specific tensor descriptor when debugging transfer
- `checkpoint_id`: Checkpoint descriptor when debugging durability/resume
- `runtime_event_seq`: Monotonic runtime telemetry event sequence

---

## 5. Eight-Stage Root-Cause Taxonomy

Classify any observed divergence into one of the 8 canonical failure stages:

1. **Transport**: Socket reset/closure, TCP buffer stall, partial frame read/write (`recv_exact` breach).
2. **DTP / MCP Framing & Protocol**: Magic bytes mismatch, unsupported protocol version, invalid message type, corrupted header length.
3. **Identity & Session Validation**: Attempt ID mismatch, expired/invalid session ID, unregistered worker, assigned shard/batch mismatch.
4. **Synchronization Policy & Admission**: Contribution barrier race, rejected stale/future model version, duplicate contribution rejection.
5. **Aggregation & Parameter Update**: Sample count calculation mismatch, tensor shape/dtype incompatibility, numerical instability (NaN/Inf), double update attempt.
6. **Broadcast & `PARAMETER_APPLIED`**: Parameter chunk broadcast desync, worker local model update failure, missing or dropped ACK frame.
7. **Checkpoint Durability & Resume**: Disk I/O failure, checkpoint manifest hash verification mismatch, state restoration desync into new attempt.
8. **Management Projection & Reconnect**: WebSocket drop, backend MCP client reconnect backoff, database telemetry write contention.

---

## 6. Critical Path Failure Invariant

> [!IMPORTANT]
> **Management Backend / DB / WebUI Failure ≠ Attempt Failure**:
> If the Management Backend, PostgreSQL, or WebUI crashes or disconnects, the agent must **NOT** conclude that the training Attempt failed, provided the training data plane (Runtime ↔ Workers over DTP/1) is intact according to the canonical failure model.

---

## 7. Resolution & Handoff Pipeline

1. **Root Cause Classification**: Categorize using the 8-stage taxonomy.
2. **Automated Regression Test**: Write an automated reproduction test demonstrating the failure condition.
3. **Three-way handoff**:
   - **Route A**: Protocol/wire semantic defect → `protocol-change` PRIMARY.
   - **Route B**: Domain/API/persistence/checkpoint semantic defect → `contract-change` PRIMARY.
   - **Route C**: Canonical semantics unchanged, implementation-only defect → direct implementation fix → regression test → `architecture-guard` if relevant → `distributed-verification` if relevant → `release-gate`. Do not force an implementation-only bug through contract-change.
4. All routes finish with relevant verification and `release-gate`; reuse resolved canonical context.
