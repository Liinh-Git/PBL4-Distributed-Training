# Implementation Contract — PBL4 Distributed Training

Phase 2 execution update (user-approved scope, 2026-10-13): in the trusted test
environment, `pbl4-agent start` auto-enrolls via `POST /api/v1/nodes/enroll`
without an enrollment code, then persists/reuses Node identity. Periodic hardware
telemetry is disabled; static capabilities, heartbeat and Worker status remain.
This open enrollment endpoint is not a public Internet security model.
`POST /api/v1/jobs/{job_id}/start` additionally accepts optional `node_ids`:
exactly N distinct, ONLINE, available Nodes. Omission preserves deterministic
automatic placement. Node selection is execution data outside the frozen
training contract; idempotency includes the selected set. Managed
`START_WORKER.model_id` is explicit and missing/unsupported values are rejected.
The unmanaged legacy Worker path retains its documented ResNet default.

> **IMPORTANT NOTICE:**  
> This is a repository-local implementation projection.  
> It does not create or override architecture.  
> If this file conflicts with approved canonical docs, **canonical docs win**.

---

## 1. Canonical Document Ownership & Mapping

The canonical design lives in the team's approved design documents (Google Drive):
- **02. Mô hình miền** (Domain model: Attempt lifecycle, Worker session lifecycle, Job, Synchronization, Dataset build lifecycle)
- **03. Mô hình dữ liệu** (Data model: PostgreSQL schema, DTP/1 wire framing & fields, Dataset manifest & shard formats, checkpoint formats)
- **04. Cấu trúc mã nguồn** (Source structure: package layout, module ownership, entrypoints, dependency directions)

Before implementing any module, the responsible engineer or agent must consult the corresponding canonical design document:

| Module / Package | Primary Canonical Reference Documents |
|---|---|
| `src/pbl4/protocol/*` | **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/transport/*` | **04. Cấu trúc mã nguồn** |
| `src/pbl4/management_protocol/*` | **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/runtime/synchronization/*` | **02. Mô hình miền**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/runtime/*` | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/worker/*` | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/adapter/*` | **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| Dataset Manager (external repo) | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/management_backend/*` | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `web/*` | **02. Mô hình miền**, **04. Cấu trúc mã nguồn** |

---

## 2. Process Boundaries

User-approved transport exception (2026-10-29): when `REDIS_URL` is configured on
both processes, Runtime events use Redis Streams exclusively. MCP/1 retains
Commands, Command Results, State Snapshots and existing catalog lookup. Event
payload/schema and `(attempt_id, runtime_event_seq)` identity are unchanged.
Redis is management-only buffering; PostgreSQL remains official event history.
This explicitly scoped decision supersedes earlier Redis prohibitions for this
transport only. Canonical ownership remains with `[ARCH_SYSTEM]` for Path 3,
`[MCP1]` for event/reconnect semantics, `[TRAINING_RUNTIME]` for event delivery,
`[BACKEND]` for ingest, `[POSTGRESQL]` for transaction/replay cursors,
`[COMMUNICATION_MAP]` for topology, and `[CODE_STRUCTURE]` for module boundaries.
The sources are linked in [.agents/SOURCE_REGISTRY.md](../.agents/SOURCE_REGISTRY.md).
The user-confirmed sole tabs `Tab 1` (Backend/PostgreSQL) and `Thẻ 1`
(Communication Map) are the current source locations for those documents.

| Process | Role | Protocols |
|---|---|---|
| `pbl4-runtime` | Parameter Server, training coordinator, DTP/1 server | DTP/1 (server), MCP/1 (endpoint), Redis Streams (events publisher when configured) |
| `pbl4-worker` | Training worker (forward/backward/gradient export) | DTP/1 (client), HTTP (shard download) |
| Dataset Manager (external) | Standalone dataset ingestion, partitioning, shard serving | HTTP (server) |
| `pbl4-backend` | Management Backend (REST API, PostgreSQL persistence, MCP/1 gateway) | HTTP/REST, WebSocket, MCP/1 (client), Redis Streams (event consumer when configured) |
| `pblctl` | CLI tool | HTTP/REST (to Management Backend) |
| WebUI | React SPA | HTTP/REST, WebSocket (to Management Backend) |

Processes communicate strictly through network protocols. No shared memory or cross-process direct calls.

---

## 3. Dependency Direction

```
runtime             → protocol, transport, management_protocol, common
worker              → protocol, transport, adapter, common
management_backend  → management_protocol, common
dataset_manager     → common
all packages        → common
```

**Forbidden Directions:**
- `protocol` must not import `runtime`, `worker`, `management_backend`, `dataset_manager`, `torch`, or database libraries.
- `transport` must not import `runtime.synchronization`, domain training semantics, or `protocol`.
- `worker` must not import `management_backend` or database libraries.
- `management_backend` must not import `runtime` training implementation internals.
- `dataset_manager` must not import `runtime` training implementation.
- `runtime.synchronization` must not import `checkpoint`, `transport`, database, or HTTP.

---

## 4. The Three Communication Paths

### Path 1: Training Correctness (Critical Path)
```
Worker ↔ DTP/1 (TCP) ↔ Runtime (Parameter Server)
```
- Raw gradient tensors and canonical parameter updates travel exclusively over DTP/1.
- Neither Management Backend, PostgreSQL, nor Dataset Manager is on this path.
- Redis is never on this path; Redis down ≠ training down.
- Invariants:
  - Management Backend down ≠ training down.
  - Database down ≠ training down.
  - Dataset Manager down (after `SHARD_READY`) ≠ training down.

### Path 2: Dataset Provisioning
```
Before Attempt.RUNNING:
  Management Backend → control/catalog → Dataset Manager
  Dataset Manager: materialization → verification → manifest publication → registration
  Management Backend → verification/persistence → registration ack → READY
  Runtime → read root manifest / verify hash → Dataset Manager
  Workers → HTTP download shard artifacts → Dataset Manager
After SHARD_READY:
  Workers read local shard cache. Dataset Manager is not contacted during steps.
```

### Path 3: Management & Telemetry
```
Runtime ↔ MCP/1 (TCP) ↔ Management Backend ↔ PostgreSQL (psycopg)
Runtime → Redis Streams (management events only, when configured) → Management Backend
Management Backend ↔ HTTP / WebSocket ↔ CLI / WebUI
```

---

## 5. Concurrency Ownership

Runtime concurrency is organized by single-responsibility ownership rather than a single global lock:

| Subsystem / Entity | Single Responsibility Owner | Notes |
|---|---|---|
| Attempt lifecycle transitions | `Coordinator` | Coordinates phase transitions per canonical Domain/Data Model state machine (CREATED, WAITING_WORKERS, PROVISIONING, INITIALIZING, RUNNING, COMPLETED, FAILED, ABORTED) |
| Worker session state | `WorkerRegistry` | Thread-safe session tracking and logical rank assignment |
| Synchronization decisions | `SynchronizationPolicy` | Evaluates contribution admission and update readiness |
| Canonical Model mutation | `UpdateEngine` & restore path | CanonicalModel mutation is restricted to the UpdateEngine update path and the approved restore path; no other component may mutate canonical parameters |
| Checkpoint cadence | `CheckpointPolicy` | Evaluates when a checkpoint must be triggered (StrictBSP V1: after_each_model_update_blocking; step progression requires checkpoint COMPLETE) |
| Checkpoint durability | `CheckpointManager` | Serializes/deserializes model weights to/from disk |
| Event buffering | `EventEmitter` | Non-blocking bounded queue; background publisher ACKs queue entries after Redis XADD confirmation when configured, otherwise MCP/1 delivery |

Redis consumption uses one stable consumer/group with blocking reads and pending
replay before new entries. DB/projection errors retain pending entries and retry
with backoff. The existing `runtime_metadata.highest_contiguous_seq` is persisted
with each event projection, independently of the live snapshot cursor. Snapshot
reconciliation preserves the durable event cursor. Gap recovery skips only
through the encountered gap event after a committed authoritative snapshot,
so later buffered projections still run. No schema migration or
new domain state/protocol version is introduced. See [Redis deployment](REDIS_EVENTS.md).

---

## 6. Persistence Architecture (Management Backend)

- Persistence stack: **PostgreSQL + psycopg** (with connection pooling).
- All queries are explicit SQL encapsulated in the repository layer.
- SQLAlchemy ORM and asyncpg are prohibited.
- Migration tooling is not selected/implemented by the scaffold. Any migration result must faithfully project the canonical PostgreSQL Data Model.

---

## 7. Version Domains

| Domain | Specification Authority | Notes |
|---|---|---|
| `PACKAGE_VERSION` | `src/pbl4/__init__.py` | Python package release version |
| DTP Protocol Version | Wire specification | Representation (integer vs string) defined by canonical DTP/1 wire spec |
| MCP Protocol Version | Management wire specification | Representation defined by canonical MCP/1 specification |
| Parameter Manifest Schema | Canonical data model | Schema version representation defined by canonical spec |
| Dataset Manifest Schema | Canonical data model | Schema version representation defined by canonical spec |
| Checkpoint Schema | Runtime durability | Owned by Runtime durability |

---

## 8. Definition of Done for Implemented Features

When feature implementation begins, a feature is done when:
1. Implementation adheres to the corresponding canonical specification.
2. Architecture constraints pass (`uv run python scripts/check_architecture.py`).
3. Appropriate tests (unit, golden, integration) are added with/after code and pass before merge.
4. Code passes formatting and lint checks (`uv run ruff format --check` and `uv run ruff check`).
5. No unrelated code refactoring is included.


Redis event processing optimization (2026-10-29, user-authorized): one shared
bounded Runtime outbox and publisher across Attempts; unchanged per-Attempt event
identity and priority eviction; compact JSON. Backend reads up to 100 entries and
ACK/deletes only the committed prefix. Ordered history + projection + cursor use
one SQL transaction; duplicate comparison and failed-commit replay remain intact.
WebSocket live/replay frames follow the Contracts wrappers. Event types, training behavior,
checkpoint policy and DTP/1 are unchanged by this optimization.

Event micro-batching (user-approved 2026-10-31): the Runtime outbox defaults to
8192 entries and its background publisher pipelines up to 64 XADDs. Backend
collects up to 100 entries with at most one 25 ms collection wait and splits SQL
batches at 256 KiB (oversized single events are processed alone), sequence gaps
and snapshot-requiring lifecycle events. History/projections and each Attempt's
final cursor commit together before WebSocket publication or Redis ACK; failed
batches remain pending. Snapshot requests stay outside SQL transactions.
`model.updated` V1 stops exporting optional per-contribution diagnostic copies
of tensor_id, parameter_manifest_hash, batch_ordinal and correct_count. Core
fields, loss history, legacy readers, Runtime/DTP validation and epoch metrics
are preserved. There is one Redis Stream and no additional environment settings.
