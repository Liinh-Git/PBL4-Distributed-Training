# Implementation Contract — PBL4 Distributed Training

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
| `src/pbl4/dataset_manager/*` | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `src/pbl4/management_backend/*` | **02. Mô hình miền**, **03. Mô hình dữ liệu**, **04. Cấu trúc mã nguồn** |
| `web/*` | **02. Mô hình miền**, **04. Cấu trúc mã nguồn** |

---

## 2. Process Boundaries

| Process | Role | Protocols |
|---|---|---|
| `pbl4-runtime` | Parameter Server, training coordinator, DTP/1 server | DTP/1 (server), MCP/1 (endpoint) |
| `pbl4-worker` | Training worker (forward/backward/gradient export) | DTP/1 (client), HTTP (shard download) |
| `pbl4-dataset-manager` | Dataset ingestion, partitioning, shard serving | HTTP (server) |
| `pbl4-backend` | Management Backend (REST API, PostgreSQL persistence, MCP/1 gateway) | HTTP/REST, WebSocket, MCP/1 (client) |
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
Management Backend ↔ HTTP / WebSocket ↔ CLI / WebUI
```

---

## 5. Concurrency Ownership

Runtime concurrency is organized by single-responsibility ownership rather than a single global lock:

| Subsystem / Entity | Single Responsibility Owner | Notes |
|---|---|---|
| Attempt lifecycle transitions | `Coordinator` | Coordinates phase transitions per canonical Domain/Data Model state machine (CREATED, WAITING_WORKERS, PROVISIONING, INITIALIZING, RUNNING, COMPLETING, COMPLETED, FAILED, ABORTED) |
| Worker session state | `WorkerRegistry` | Thread-safe session tracking and logical rank assignment |
| Synchronization decisions | `SynchronizationPolicy` | Evaluates contribution admission and update readiness |
| Canonical Model mutation | `UpdateEngine` & restore path | CanonicalModel mutation is restricted to the UpdateEngine update path and the approved restore path; no other component may mutate canonical parameters |
| Checkpoint cadence | `CheckpointPolicy` | Evaluates when a checkpoint must be triggered (StrictBSP V1: after_each_model_update_blocking; step progression requires checkpoint COMPLETE) |
| Checkpoint durability | `CheckpointManager` | Serializes/deserializes model weights to/from disk |
| Event buffering | `EventEmitter` | Non-blocking bounded queue delivering events to MCP/1 endpoint |

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
