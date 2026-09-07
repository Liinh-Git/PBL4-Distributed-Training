---
name: architecture-guard
description: >
  Validates canonical architectural constraints, import directions, and
  structural invariants across all PBL4 distributed training subsystems.
---

# Architecture Guard

## 1. When to Activate

Use this skill whenever:
- Adding a new package, module, or service boundary
- Moving files between packages or reorganizing imports
- Refactoring dependency directions or shared abstractions
- Introducing interfaces between Runtime, Worker, Backend, and Dataset Manager
- Adding or modifying third-party dependencies

---

## 2. Canonical Source References

Consult the canonical technical documents registered in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):
- `[ARCH_SYSTEM]`: Overall process boundaries and critical communication paths
- `[CODE_STRUCTURE]`: Package layouts, module ownership, and import boundaries
- `[TRAINING_RUNTIME]`: Parameter Server responsibilities and single-writer rule
- `[SYNC_STRICT_BSP]`: SynchronizationPolicy abstraction and barrier isolation
- `[CHECKPOINT]`: Separation of durability from synchronization

> [!WARNING]
> **Drive Unavailable Fail-safe**: If an architectural boundary or invariant decision is unresolved and the canonical Drive source is inaccessible, **STOP** and report `BLOCKED_CANONICAL_SOURCE_UNAVAILABLE`. Do not guess from local code or tab `Nháp`.

---

## 3. Allowed Dependency Directions

Verify that imports strictly adhere to the canonical dependency graph:

```
runtime             → protocol, transport, management_protocol, common
worker              → protocol, transport, adapter, common
backend             → management_protocol, common
dataset_manager     → common
all packages        → common
```

*(Note: The architectural component is `Management Backend`; the canonical Python package path is strictly `backend` [occurrences of `management_backend` are only acceptable if explicitly labeled historical, legacy examples, or anti-examples]).*

### Forbidden Dependency Directions
- `protocol` → `runtime`, `worker`, `backend`, `dataset_manager`, `torch`, database libraries
- `transport` → `runtime`, `synchronization`, training semantics, `protocol`
- `worker` → `backend`, `PostgreSQL`, `dataset_manager` implementation
- `backend` → `runtime` training implementation internals
- `dataset_manager` → `runtime` training implementation, `backend`
- `runtime.synchronization` → `checkpoint`, `transport`, database, HTTP
- `runtime` → `backend`, web frameworks (`fastapi`), database drivers (`psycopg`, `asyncpg`, `sqlalchemy`)

---

## 4. Core Architectural Invariants

Every change must rigorously maintain the following 11 canonical invariants:

1. **Strict BSP Behind `SynchronizationPolicy`**: Strict BSP must remain an implementation behind the abstract `SynchronizationPolicy` interface. Generic runtime layers must not couple directly to Strict BSP semantics.
2. **No Hard-Coded Generic Worker Count / Membership**: Do not hard-code worker count or membership semantics (`expected_workers == 3`) in generic layers:
   - Generic protocol, transport, generic synchronization abstractions, aggregator, UpdateEngine, generic DB logic, Backend business logic outside V1 admission, and WebUI generic state logic must remain agnostic of worker counts.
   - The number `3` may validly appear in: V1 resolved-contract validation, Strict BSP V1-specific policy, tests for the official V1 topology, documentation/examples, and unrelated numeric logic. Do NOT use raw text search of literal "3" as an architectural rule.
3. **`BarrierManager` Isolation**: `BarrierManager` is strictly an internal primitive of Strict BSP V1. `ParameterServer`, `GradientAggregator`, `TensorCodec`, and generic Runtime components must **NEVER** depend directly on `BarrierManager` for progression or updates.
4. **`operation_id` Neutrality**: `operation_id` is not universally semantically equivalent to `step_id`. Generic DTP/runtime/schema code MUST NOT assume equality. StrictBSP V1 maps them 1:1 at its strategy layer; future strategies remain free of that equality.
5. **Separation of `step_id` and `model_version`**: `step_id` (strategy iteration) and `model_version` (canonical parameter publication counter) are distinct concepts. Never assume `step_id == model_version`.
6. **Decoupled Synchronization & Checkpoint Ownership**:
   - `SynchronizationPolicy` owns contribution admission, update readiness, and `PARAMETER_APPLIED` acknowledgment.
   - `CheckpointPolicy` owns durability cadence and blocking requirements.
   - `CheckpointManager` owns checkpoint serialization and verification mechanics.
   - `Coordinator` composes the Synchronization Gate and Durability Gate. SynchronizationPolicy must never decide checkpoint mechanics.
7. **Runtime Critical Path Independence**: Training correctness and Parameter Server execution must **NEVER** depend on FastAPI, PostgreSQL, or WebUI availability.
8. **Worker Data Plane Isolation**: Workers communicate exclusively with Runtime via DTP/1 for training and with Dataset Manager via HTTP for shards. Workers must **NEVER** query Backend repositories or PostgreSQL.
9. **Worker-0 Network Uniformity**: Whichever worker is assigned `worker_id=0` connects via the exact same DTP/1 TCP socket path. No in-process memory shortcuts or bypasses are permitted.
10. **`common/` Anti-Dumping Rule**: `common/` is strictly for foundation and value helpers:
    - IDs and value types
    - Cryptographic and hash helpers
    - Shared error types and error value objects
    - Time and clock helpers
    - **Prohibited in `common/`**: Domain models (`Job`, `Attempt`, `Worker`, `Step`, `DatasetBuild`), repositories, domain state machines, and Runtime metrics (`runtime/metrics.py` belongs strictly in `runtime`). They must not be moved into `common/` merely because multiple packages consume them.
11. **Strict Cross-Process Boundaries**: Direct object calls across process boundaries are prohibited. Processes (`runtime`, `worker`, `backend`, `dataset_manager`, `cli`, `web`) communicate exclusively over defined network protocols (DTP/1, MCP/1, REST, WebSocket, HTTP). Within the same process or package composition, standard in-memory object calls remain valid provided they respect allowed dependency directions.

---

## 5. Verification Workflow

1. **Preflight Script Check**:
   Before running architecture verification, check if the script exists on disk:
   - If `scripts/check_architecture.py` exists:
     ```bash
     uv run python scripts/check_architecture.py
     ```
     Must exit with code 0 and zero boundary violations.
   - If missing, report `NOT_AVAILABLE`. Do not fake PASS or invent scripts.
2. **Invariant Impact Report**:
   Document in PR / task output:
   - Affected process boundaries
   - Any modifications to generic interfaces vs. strategy implementations
   - Confirmation that all 11 core architectural invariants remain intact
