# AGENTS.md — PBL4 Distributed Training

> This file defines normative rules for all agents (human and AI) working in this repository.
> These rules are enforced by architecture static checks and CI. Violations must be caught in review.

## Authority Order

```
Canonical approved design documents
  ↓
docs/IMPLEMENTATION_CONTRACT.md
  ↓
AGENTS.md (this file)
  ↓
nested AGENTS.md files
  ↓
.agents/skills/ SKILL.md files
  ↓
implementation assumptions
```

If a lower layer contradicts a higher layer, **the higher layer wins**.

---

## Rules

### 1. Canonical docs win over assumptions
When implementation conflicts with approved design documents, the canonical document is authoritative. Do not guess — open an issue in `docs/OPEN_ISSUES.md` only if genuinely unresolved.

### 2. No cross-process object calls
Processes (`pbl4-runtime`, `pbl4-worker`, `pbl4-dataset-manager`, `pbl4-backend`, `pblctl`, WebUI) communicate ONLY through defined network protocols (DTP/1, MCP/1, HTTP, WebSocket). No shared memory, no direct function calls across process boundaries.

### 3. Gradient/parameter traffic uses DTP/1 only
Raw gradient tensors and canonical parameter tensors travel exclusively over DTP/1 persistent TCP connections between Worker ↔ Runtime. They MUST NOT traverse Management Backend, PostgreSQL, REST, WebSocket, or Dataset Manager.

### 4. Management Backend/PostgreSQL/Dataset Manager are NOT in the training critical path
These invariants MUST hold:
- Management Backend down ≠ training down
- Database down ≠ training down
- Dataset Manager down (after SHARD_READY) ≠ training down

### 5. `protocol` package has zero runtime/management_backend/worker/torch/db imports
`src/pbl4/protocol/` must not import from `runtime`, `management_backend`, `worker`, `dataset_manager`, `torch`, `psycopg`, `asyncpg`, `sqlalchemy`, or any database library. It is a pure wire-format package.

### 6. `transport` knows nothing about training semantics
`src/pbl4/transport/` must not import or reference Step, barrier, worker count, synchronization policy, or any training-domain concept. It is a generic TCP/socket exact-byte transport primitives layer.

### 7. No hard-coded `expected_workers == 3` in generic layers
The literal `3` must not leak into protocol, transport, aggregator, base synchronization abstractions, database schemas, or UI assumptions. `expected_workers` comes from the resolved contract via `StrategyContext`.

### 8. CanonicalModel has controlled single-writer ownership
Only `UpdateEngine` and the checkpoint restore path may write to `CanonicalModel`. Workers receive read-only parameter copies. Workers do NOT call `optimizer.step()` on the canonical distributed model.

### 9. Worker-0 uses the same DTP TCP path as all other workers
No special in-process shortcut for Worker-0. All workers connect via DTP/1 over TCP, including whichever session is assigned worker_id=0.

### 10. SynchronizationPolicy does NOT decide checkpoint cadence
`SynchronizationPolicy` owns admission and update-ready decisions only. Checkpoint timing is owned by `CheckpointPolicy`, and checkpoint durability is owned by `CheckpointManager`.

### 11. Do not invent new domain state, enums, or protocol semantics
State machines, enums, and domain types are defined in canonical design documents. Do not create new ones without explicit approval and documentation.

### 12. Forbidden distributed frameworks and infrastructure
Do not introduce: gRPC, Ray, Horovod, DeepSpeed, PyTorch DDP/FSDP, Redis, Kafka, RabbitMQ, or any distributed framework that replaces the custom DTP/1 protocol or Parameter Server architecture.

### 13. Tests accompany implemented features before merge
Tests are created together with or after feature implementation. Do NOT pre-create empty test hierarchies or unverified fixtures. Any implemented protocol, state machine, DB schema, or API change must include corresponding tests before merge.

### 14. Do not refactor unrelated code in feature PRs
Feature PRs must be scoped to the feature. Refactoring unrelated subsystems must be a separate PR.

### 15. Feature tasks must not modify governance files
Feature implementation tasks must not modify `AGENTS.md`, nested `AGENTS.md` files, or `.agents/skills/` content. Governance changes require explicit approval.

---

## Process Boundaries

```
pbl4-runtime         — Parameter Server, training coordinator
pbl4-worker          — Training worker (forward/backward/gradient export)
pbl4-dataset-manager — Dataset ingestion/partitioning/serving
pbl4-backend         — Management Backend (REST API, PostgreSQL, MCP/1 gateway)
pblctl               — CLI tool (talks to Management Backend)
WebUI                — React frontend (talks to Management Backend only)
```

## Dependency Direction (Allowed Imports)

```
runtime             → protocol, transport, management_protocol, common
worker              → protocol, transport, adapter, common
management_backend  → management_protocol, common
dataset_manager     → common
all packages        → common
```

Explicitly Forbidden Directions:
- `protocol` → runtime, worker, management_backend, dataset_manager, torch, db
- `transport` → runtime, synchronization, training semantics
- `worker` → management_backend, database libraries
- `management_backend` → runtime training implementation
- `dataset_manager` → runtime training implementation
- `runtime.synchronization` → checkpoint, transport, db, http
- `runtime` → web frameworks (FastAPI), database drivers

Enforced statically by `scripts/check_architecture.py`.
