---
name: distributed-debug
description: >
  Diagnostic workflow for Node/Agent orchestration and distributed training failures,
  hangs, deadlocks, Work Unit issues, and discrepancies using correlation tracing.
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
- `[NODE_AGENT]`: Node enrollment, Agent WSS, WorkerAllocation/process supervision, and admission
- `[DBS_WORKLOAD]`: Work Unit assignment/cache/compute and epoch-plan statistics

---

## 3. Core Principle: Find First Divergence

> [!CAUTION]
> **Anti-Pattern Warning**: Never attempt to "fix" distributed race conditions or timeouts by inserting arbitrary `sleep()`, randomly extending timeout thresholds, or adding blind retries. Locate the **exact first divergent event** across processes.

---

## 4. Correlation Identifiers

Align multi-process logs across Runtime, Workers, and Backend using canonical correlation fields:
- `job_id`: Top-level training job UUID
- `attempt_id`: Specific execution attempt UUID (attempts are immutable)
- `node_id`: Long-lived enrolled Node identity
- `allocation_id`: Backend WorkerAllocation and Agent lifecycle idempotency identity
- `command_id`: Agent control command correlation identifier
- `session_id`: Unique uint64 worker connection session ID
- `worker_id`: Logical worker rank assigned by Runtime
- `operation_id`: DTP/1 neutral 8-byte operation correlation identifier
- `step_id`: Step iteration index (Strict BSP projection)
- `model_version`: Monotonic parameter publication counter
- `tensor_id`: Specific tensor descriptor when debugging transfer
- `checkpoint_id`: Checkpoint descriptor when debugging durability/resume
- `runtime_event_seq`: Monotonic runtime telemetry event sequence

---

## 5. Root-Cause Taxonomy

Classify the first divergence into the owning stage; do not collapse Agent control
failures into DTP framing merely because a Worker eventually fails to connect:

1. **Node Enrollment & Authentication**: one-time enrollment code, persisted Node identity, node-secret verification, revoke state, or secret redaction failure.
2. **Agent WSS Control Connection**: outbound connect/auth, `AGENT_HELLO`, heartbeat/resource reporting, ONLINE/OFFLINE timeout, or reconnect/reconciliation failure.
3. **Worker Command Dispatch**: `START_WORKER`/`STOP_WORKER`, `command_id` correlation, `allocation_id` idempotency, command ACK, or Backend allocation transition failure.
4. **Local Process Supervisor**: spawn, PID/create-time verification, restart reconciliation, graceful/forced stop, or Worker status reporting failure.
5. **Worker Admission**: managed HELLO token/scope/expiry/duplicate-allocation validation before registration. Do not classify these as tensor-framing failures.
6. **Transport and DTP/MCP Framing**: socket reset/closure, partial exact-byte read/write, magic/version/type/header corruption on the protocol actually in use.
7. **Identity, Session, and Canonical Assignment**: attempt/session/worker mismatch, stale connection, batch cursor, or legacy/Work Unit assignment mismatch.
8. **Work Unit Cache & Compute**: provisioning readiness, multi-shard cache verification, assigned Work Unit load, local weighted gradient, or `compute_ms` measurement failure.
9. **Synchronization, Aggregation, and Update**: contribution barrier race, stale/future/duplicate rejection, sample weighting, tensor shape/dtype, or double update.
10. **Broadcast & `PARAMETER_APPLIED`**: parameter chunk broadcast desync, Worker local model update failure, or missing/dropped ACK.
11. **Checkpoint Durability & Resume**: durable-write/hash failure, cursor restoration, DBS warm-up mode, or new-Attempt recovery desynchronization.
12. **DBS Epoch Statistics & Plan**: incomplete/invalid committed statistics, epoch-boundary plan freeze, integer projection, or equal/DBS global-set mismatch.
13. **Management Projection & Reconnect**: Backend MCP reconnect, database projection, or telemetry reconciliation failure that does not itself imply training failure.

---

## 6. Critical Path Failure Invariant

> [!IMPORTANT]
> **Management Backend / DB / WebUI Failure ≠ Attempt Failure**:
> If the Management Backend, PostgreSQL, or WebUI crashes or disconnects, the agent must **NOT** conclude that the training Attempt failed, provided the training data plane (Runtime ↔ Workers over DTP/1) is intact according to the canonical failure model.

---

## 7. Resolution & Handoff Pipeline

1. **Root Cause Classification**: Categorize using the 13-stage taxonomy.
2. **Automated Regression Test**: Write an automated reproduction test demonstrating the failure condition.
3. **Three-way handoff**:
   - **Route A**: Protocol/wire semantic defect → `protocol-change` PRIMARY.
   - **Route B**: Domain/API/persistence/checkpoint semantic defect → `contract-change` PRIMARY.
   - **Route C**: Canonical semantics unchanged, implementation-only defect → direct implementation fix → regression test → `architecture-guard` if relevant → `distributed-verification` if relevant → `release-gate`. Do not force an implementation-only bug through contract-change.
4. All routes finish with relevant verification and `release-gate`; reuse resolved canonical context.
