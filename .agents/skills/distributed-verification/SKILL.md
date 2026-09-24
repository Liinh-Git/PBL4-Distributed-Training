---
name: distributed-verification
description: >
  Verification checklist and invariant oracle for Worker admission, Work Unit and DBS
  correctness, synchronization, gradient aggregation, and checkpoint durability gates.
---

# Distributed Verification

## 1. When to Activate

Activate this skill during Phase 3 of the pipeline whenever a change impacts:
- Runtime synchronization policies (`src/pbl4/runtime/synchronization/`)
- Gradient aggregation and parameter updates (`Aggregator`, `UpdateEngine`, `ParameterServer`)
- Worker contribution admission, validation, or acknowledgment
- Step progression gates and checkpoint durability coordination
- DTP/1 tensor transmission integrity
- Managed Worker admission before registration
- Work Unit assignment, multi-unit Worker compute, or DBS workload scheduling

---

## 2. Canonical Source References

Consult the canonical technical documents registered in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):
- `[SYNC_STRICT_BSP]`: Strict BSP V1 admission rules, barrier handling, and aggregation semantics
- `[TRAINING_RUNTIME]`: Parameter Server state machine and Coordinator orchestration
- `[CHECKPOINT]`: Durability gate mechanics and Step `COMMITTED` criteria
- `[DTP1]`: Binary wire streaming and correlation identity rules
- `[NODE_AGENT]`: Managed Worker admission and control/data-plane separation
- `[DBS_WORKLOAD]`: Work Unit assignment, weighted compute, resume warm-up, and workload invariants

> [!WARNING]
> **Drive Unavailable Fail-safe**: If verification rules or tolerance thresholds require canonical clarification and Drive is inaccessible, **HALT** and report `BLOCKED_CANONICAL_SOURCE_UNAVAILABLE`.

---

## 3. Strict BSP V1 Contribution Verification Checklist

Each worker contribution received by the Runtime must be verified against:
- [ ] **Attempt Identity**: Matches the currently running `attempt_id`.
- [ ] **Session Identity**: Matches an active registered worker `session_id`.
- [ ] **Worker Identity**: Matches the assigned logical `worker_id` for that session.
- [ ] **Operation Identity**: Matches the current in-flight generic `operation_id`.
- [ ] **Step Iteration**: Matches the current Strict BSP `step_id` (strategy layer projection).
- [ ] **Model Version Alignment**: Targets the exact current canonical `model_version`.
- [ ] **Canonical Assignment**: Matches the Runtime-owned assignment for that Worker and operation. Legacy assigned-shard mode validates its single assigned batch. Work Unit mode verifies that the Worker received and loaded the complete canonical `work_units[]` list, while Runtime validates the existing operation, cursor, first-unit compatibility fields, and total sample count without inventing an assignment echo/hash; neither mode assumes `shard_id == worker_id`.
- [ ] **Batch Cursor**: Matches the current global batch/recovery cursor and operation assignment.
- [ ] **Sample Count**: Positive integer equal to the actual total samples in all Work Units processed by that Worker.
- [ ] **Gradient & Manifest Integrity**: Gradient representation is compatible with canonical model contract:
  - `parameter_manifest_hash` / model contract identity
  - Tensor ordering and layout match expected parameter structure
  - `total_numel` and `total_bytes` match expected gradient size
  - Encoding and dtype alignment (gradients are not mislabeled as "weights")
- [ ] **Logical Contribution Uniqueness**:
  - Contribution identity anchors strictly on the semantic key: `(attempt_id, step_id, worker_id)` (or equivalent strategy-owned logical contribution key).
  - Exactly **one** contribution accepted per logical worker per step.
  - **Session Validation vs. Logical Uniqueness**: `session_id` validates current connection liveness (contributions from old/stale sessions are rejected). However, worker reconnection or obtaining a new `session_id` does **NOT** grant the right to contribute a second time for the same `(attempt_id, step_id, worker_id)`.

### Negative Rejection Test Matrix
Automated tests must explicitly verify rejection and error reporting for:
- [ ] **Duplicate**: Second contribution from the same logical worker for the active step (even via reconnected session) is rejected.
- [ ] **Stale**: Contribution targeting `model_version < current_model_version` or past `step_id` is rejected.
- [ ] **Future**: Contribution targeting `model_version > current_model_version` or unreached `step_id` is rejected.
- [ ] **Wrong Session / Attempt / Worker**: Mismatched session/attempt/worker IDs are rejected.
- [ ] **Wrong Assignment**: Mismatched legacy shard/batch or Work Unit assignment, batch ordinal, or total sample count is rejected.
- [ ] **Incomplete / Corrupt Tensor**: Truncated payloads, chunk hash mismatches, or malformed metadata are rejected immediately without corrupting PS state.

---

## 4. Parameter Update & Aggregation Invariants

- [ ] **Full Membership N/N Requirement**: UpdateEngine is **NEVER** invoked until all `expected_workers` required by the resolved contract have successfully contributed.
- [ ] **Immutable UpdatePlan**: Aggregator receives an immutable snapshot (`UpdatePlan`) of validated contributions.
- [ ] **Sample-Weighted Aggregation**: Admitted gradient tensors are combined via sample-count weighted mean:
  $$\bar{G} = \frac{\sum_{i=1}^N s_i \cdot G_i}{\sum_{i=1}^N s_i}$$
- [ ] **Single-Writer Rule**: Only `UpdateEngine` and the approved checkpoint restore path write to `CanonicalModel`. Workers never apply optimizer steps to canonical parameters directly.
- [ ] **Single Canonical Update per Plan**: An `UpdatePlan` can never execute more than once.
- [ ] **Atomic Version Increment**: Successful parameter publication produces `model_version = model_version + 1` exactly once.

### Work Unit and DBS correctness

- [ ] Runtime assigns one canonical Work Unit list to every Worker for the step; a Worker may receive more than one Work Unit.
- [ ] Each Worker sends exactly one logical contribution for the step, never one contribution per Work Unit.
- [ ] Worker local gradient and loss combine Work Units by sample count; Runtime global aggregation remains sample-weighted by each contribution's total `sample_count`.
- [ ] Full N/N contribution admission remains unchanged; DBS never shrinks membership, redistributes mid-step, or performs a partial update.
- [ ] With the same dataset, seed, epoch, and step, `equal` and `dbs` process the same global Work Unit set; only the assignment among Workers changes.
- [ ] Work Unit provisioning/cache readiness completes before `RUNNING`. Dataset Manager is not called in the synchronized step.
- [ ] Cache corruption or miss after `RUNNING` fails the Worker/Attempt under fixed membership; Runtime does not silently substitute a replacement Work Unit.
- [ ] Workload statistics are recorded only after the existing Step `COMMITTED` durability gate. Resume follows the approved Equal warm-up/re-measurement rules without Checkpoint V2.

---

## 5. Completion & Durability Gates

- [ ] **Synchronization Complete**: `synchronization_complete` triggers only after `PARAMETER_APPLIED` acknowledgment is received from all $N/N$ participating workers.
- [ ] **Decoupled Durability Gate**: Checkpoint durability is a **SEPARATE** gate managed by `Coordinator`.
- [ ] **Step COMMITTED Criteria**: Under Strict BSP V1 (`after_each_model_update_blocking`), Step is **NOT COMMITTED** and next step does not start until `CheckpointManager` confirms durable write of the checkpoint. Model update alone is insufficient to advance.

---

## 6. Acceptance Oracle & Network Uniformity

- [ ] **Mathematical Oracle Verification**: Given identical initial model weights, identical local batches, and identical learning rate, the distributed updated model $\theta_{\text{distributed}}$ must match the single-process reference model $\theta_{\text{single}}$ (`allclose`) within the tolerance specified by canonical test contracts/fixtures. (If tolerance is not explicitly fixed in canonical documents, agents must NOT invent an arbitrary threshold).
- [ ] **Worker-0 Network Uniformity**: Worker-0 communicates over the real DTP/1 TCP socket path. Zero local shortcuts or in-memory bypasses.

## 7. Managed Worker Admission Verification

Admission tests must prove verification occurs before `WorkerRegistry.register()` and
before any worker slot/rank/session is consumed. Cover:

- [ ] tampered payload or signature;
- [ ] expired token;
- [ ] wrong `attempt_id`;
- [ ] wrong `allocation_id`;
- [ ] wrong `node_id`;
- [ ] missing/partial managed HELLO identity;
- [ ] duplicate Allocation admission, including a second HELLO after disconnect;
- [ ] valid managed admission receives Runtime-owned `session_id`/`worker_id` and then uses the normal DTP/1 path;
- [ ] explicit unmanaged development mode only where approved; it must not become an implicit production fallback.
