# Canonical Source Registry — PBL4 Distributed Training

> **Authority Notice:**
> This file is the authoritative source-address registry for technical documentation across the PBL4 project.
> It maps technical domains to canonical specifications hosted on Google Drive.
> This file is a **source-address registry only**, NOT a shadow architecture specification.
> Canonical design documents on Google Drive are authoritative. If any description here diverges from canonical documents, **the canonical document wins**.

---

## 1. Core Source Resolution Principles

1. **Stable Keys Over Document Numbers**: Never identify or resolve canonical sources by leading numbers (e.g., `01`, `02`, `03`, `04`). These numbers repeat across different subsystem folders. Bare titles like `02. MCP-1` or `03. Mô hình dữ liệu` are ambiguous and forbidden as sole identifiers. Always use the **Stable Source Key** (e.g., `[DTP1]`, `[MCP1]`, `[SYNC_STRICT_BSP]`) paired with the exact Drive URL.
2. **Single Primary Owner per Semantic Contract**: Every architectural concept, protocol, and state machine has exactly **one** primary canonical owner. Supporting sources provide context but **MUST NEVER override** the primary owner.
3. **Exact normative locator first**: Resolve and read the exact normative locator declared for each source below: Google Docs use `Chính` where declared, Sheets use exact named sheets, and whole-document sources use the whole document. Do not convert all source types into a `Chính` tab. For Docs with that convention:
   - Tab `Chính` = **Canonical / Normative content**. Implementation, coding, architecture checks, contract audits, bug fixes, and tests MUST derive strictly from `Chính`.
   - Tab `Nháp` = **Non-normative working material**. Tab `Nháp` is **IGNORED** for current implementation semantics. Agents MUST NOT use `Nháp` to override `Chính`, invent missing semantics, speculate on unapproved contracts, or rationalize designs. Tab `Nháp` may only be consulted if the user explicitly requests historical/proposal review, and it must be labeled `NON-NORMATIVE`.
4. **Historical & Obsolete Documents**: Documents under `99. Cũ`, merged drafts (`bản gộp cũ`), or `FINAL_REPORT` files are historical archives only and have **zero normative authority**.
5. **Role of `[START_HERE]`**: `00. BẮT ĐẦU Ở ĐÂY` (`[START_HERE]`) serves exclusively as an entry point and high-level source map. It does **not** own subsystem-specific semantics.
6. **Local Projections Cannot Override Canonical Documents**: Local files (`README.md`, `docs/IMPLEMENTATION_CONTRACT.md`, `AGENTS.md`, docstrings, or existing code) are projections. If a local projection contradicts a canonical Drive document, the canonical document wins and the projection must be updated.

---

## 2. Drive Unavailable Fail-Safe Protocol

The fail-safe rule applies selectively based on the nature of the task:

- **Routine & Resolved Tasks (Proceed Allowed)**: If a task is implementation of an already resolved semantic contract, a refactor preserving semantics, test authoring, code linting/formatting, bug fixing without inventing contracts, or mechanical projection sync with approved decisions within the task, temporary Drive unavailability does **NOT** block the task.
- **Semantic & Architectural Tasks (Strict Blocking)**: If an agent is asked to introduce new domain semantics, modify wire protocols, alter state/lifecycle machines, change checkpoint/resume semantics, adjust API schemas, or resolve architectural ambiguity, and the canonical Drive source is inaccessible (e.g., HTTP 401, network failure, missing permissions):
  - The agent **MUST STOP** immediately.
  - The agent **MUST NOT** guess from local code, `IMPLEMENTATION_CONTRACT.md`, `AGENTS.md`, or tab `Nháp`.
  - The agent **MUST report**:
    ```text
    BLOCKED_CANONICAL_SOURCE_UNAVAILABLE: Cannot access canonical source [<SOURCE_KEY>] (<URL>) to resolve <semantic topic>. Halting semantic changes.
    ```

---

## 3. Verified Canonical Source Index

### Entry Point & Source Map

#### `[START_HERE]`
- **Title**: `00. BẮT ĐẦU Ở ĐÂY`
- **URL**: `https://docs.google.com/document/d/1YXGniXjdrJYPpQy1b9-ANU4Tl8bSe9374VPsD4ogtlI/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**: Entry point, document catalog, and global cross-reference map only.
- **When to Read**: At project onboarding or when navigating between document clusters.
- **Supporting Sources**: None (does not own specific technical semantics).
- **Rule**: `[START_HERE]` delegates technical ownership to the specific subsystem documents below.

---

### Core Architecture & System Foundation

#### `[ARCH_SYSTEM]`
- **Title**: `01. Kiến trúc hệ thống`
- **URL**: `https://docs.google.com/document/d/1g_s9cc0nnoIx_p7NgU10IBqx17bJlPKqutJ-Rhsv4hM/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Global system topology and process boundaries (`pbl4-runtime`, `pbl4-worker`, `pbl4-dataset-manager`, `pbl4-backend`, `pblctl`, `WebUI`)
  - The Three Communication Paths (Path 1: Training Correctness / DTP, Path 2: Dataset Provisioning, Path 3: Management & Telemetry / MCP)
  - Critical path invariants (Management Backend down ≠ training down, DB down ≠ training down, Dataset Manager down post-provisioning ≠ training down)
  - Physical vs. logical network boundaries
- **When to Read**: When defining service boundaries, evaluating cross-process communication, or validating dependency directions.
- **Supporting Sources**: `[COMMUNICATION_MAP]`, `[CODE_STRUCTURE]`. Supporting sources cannot override `[ARCH_SYSTEM]`.

#### `[DOMAIN_MODEL]`
- **Title**: `02. Mô hình miền`
- **URL**: `https://docs.google.com/document/d/1jtAQhZQ3_KOUzdwhzs2GHfBnrvet8E2kMD4lm85N9vQ/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Core domain entities: Job, Attempt, Worker Session, Step, Dataset Build
  - Canonical lifecycle state machines and valid state transitions
  - Resolved Job contract semantics
  - Failure classification (terminal vs. retryable, attempt-level vs. job-level)
- **When to Read**: When adding or altering lifecycle states, domain entities, Attempt/Session lifecycle transitions, or resolved contract structures.
- **Supporting Sources**: `[DATA_MODEL]`, `[TRAINING_RUNTIME]`. Supporting sources cannot override `[DOMAIN_MODEL]`.

#### `[DATA_MODEL]`
- **Title**: `03. Mô hình dữ liệu`
- **URL**: `https://docs.google.com/document/d/1ciIO5Cr1mL-oLBWd2v5STaf8T6ofsL2t7UcjNgQ1ppo/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Persisted entity/table shape and table list; canonical fields, types and nullability
  - Identity relationships, FK/unique/data-shape constraints, and persisted projection structure
  - Canonical data representations, hashes, identities, and artifact schemas
  - Parameter manifest identity & hashing rules
  - Dataset manifest identity & partition schemas
  - Checkpoint storage format & artifact layouts
- **When to Read**: When modifying persisted table/field schemas, relationships, constraints, artifact schemas, manifest structures, hash algorithms, or canonical data representations.
- **Supporting Sources**: `[POSTGRESQL]`, `[CHECKPOINT]`, `[DATASET_MANAGER]`. Supporting sources cannot override `[DATA_MODEL]`.
- **Notice**: Does **NOT** own DTP/1 or MCP/1 wire framing or message protocols.

#### `[CODE_STRUCTURE]`
- **Title**: `04. Cấu trúc mã nguồn`
- **URL**: `https://docs.google.com/document/d/1QJb_qveoKklvJ3vzWhpp9Dg9Wu9QLiSdkckwB3SqkzA/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Python package layout, module ownership, entrypoints
  - Dependency directions and import boundaries
  - Package naming (Python package `backend` for `Management Backend`)
  - Anti-dumping rules for `common/`
- **When to Read**: When adding packages, moving files, modifying module dependencies, or restructuring code.
- **Supporting Sources**: `[ARCH_SYSTEM]`. Supporting sources cannot override `[CODE_STRUCTURE]`.

---

### Training Runtime & Synchronization

#### `[TRAINING_RUNTIME]`
- **Title**: `02. Runtime huấn luyện`
- **URL**: `https://docs.google.com/document/d/1b_A6suHcAZe5Y2ffO6h61x6NxM9Z7lAokulWkn5zRm4/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Parameter Server core responsibilities and single-writer rule on `CanonicalModel`
  - Coordinator orchestration (composing Synchronization Gate + Durability Gate)
  - Worker session management and registration handshake
  - Generic runtime event flow and `runtime_event_seq`
- **When to Read**: When modifying Parameter Server internals, runtime coordination, session lifecycle, or event streaming.
- **Supporting Sources**: `[SYNC_STRICT_BSP]`, `[CHECKPOINT]`, `[ARCH_SYSTEM]`. Supporting sources cannot override `[TRAINING_RUNTIME]`.

#### `[SYNC_STRICT_BSP]`
- **Title**: `03. Đồng bộ tham số`
- **URL**: `https://docs.google.com/document/d/1_2rUYoc_y-xpbV1Uuh-87cvV-xzCL-JBYZdM-vgDUQ0/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - `SynchronizationPolicy` abstraction interface
  - Strict BSP V1 policy implementation rules:
    - Contribution admission criteria (membership N/N)
    - Rejection rules: duplicate, stale, future, invalid session/attempt/worker
    - Aggregator input: immutable UpdatePlan
    - Sample-weighted gradient mean
    - `PARAMETER_APPLIED` acknowledgment requirements
  - Internal isolation of `BarrierManager` as an implementation detail of Strict BSP V1
- **When to Read**: When modifying synchronization policies, gradient aggregation logic, barrier handling, or step progression criteria.
- **Supporting Sources**: `[TRAINING_RUNTIME]`, `[DTP1]`. Supporting sources cannot override `[SYNC_STRICT_BSP]`.

#### `[CHECKPOINT]`
- **Title**: `04. Checkpoint`
- **URL**: `https://docs.google.com/document/d/1w9uJ8OeEB53jXx7miBd4rEz50R9Dm4TQJ1LyxXYZClY/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - `CheckpointPolicy` (durability cadence and blocking requirements)
  - `CheckpointManager` (atomic writing, artifact serialization, manifest generation)
  - Checkpoint verification and integrity hashes
  - Independence of checkpoint mechanics from synchronization admission
- **When to Read**: When modifying checkpoint triggers, serialization, durability verification, or Step `COMMITTED` gate.
- **Supporting Sources**: `[RECOVERY]`, `[DATA_MODEL]`. Supporting sources cannot override `[CHECKPOINT]`.

---

### Network Protocols & Communication

#### `[COMMUNICATION_MAP]`
- **Title**: `00. Bản đồ giao tiếp`
- **URL**: `https://docs.google.com/document/d/1iB3K2vvTmMc4RaJfU0CL46b7Iv2Kt_GEvi1N_lVSV6c/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Overview of protocol allocations across boundaries (DTP/1, MCP/1, REST, WebSocket, HTTP)
  - Connection initiators, ports, and topologies
- **When to Read**: When planning new cross-process communication channels.
- **Supporting Sources**: `[ARCH_SYSTEM]`, `[DTP1]`, `[MCP1]`. Supporting sources cannot override specific protocol owners.

#### `[DTP1]`
- **Title**: `01. DTP-1`
- **URL**: `https://docs.google.com/document/d/1s4x5HmuHpB4gDn3mwWpncuiPAUfdRCM0qyEUNUcHiu8/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - DTP/1 binary wire framing, exact header layout (magic, length, flags, etc.)
  - Message type identifiers and binary payload layouts
  - Tensor chunking, streaming, and wire encoding rules
  - Neutrality of `operation_id` at the generic protocol layer (`operation_id` is not universally semantically equivalent to `step_id`; generic code MUST NOT assume equality; StrictBSP V1 maps them 1:1 at the strategy layer; generic schema/protocol must preserve future strategy freedom)
- **When to Read**: When modifying `src/pbl4/protocol/` or DTP wire-level codecs, headers, or message definitions.
- **Supporting Sources**: `[CONTRACTS]` (tab `Runtime Protocol (DTP-MCP)`), `[ARCH_SYSTEM]`, `[DATA_MODEL]`, `[SYNC_STRICT_BSP]`. Supporting sources cannot override `[DTP1]`.
- **Notice**: DTP wire format ownership != Synchronization policy ownership.

#### `[MCP1]`
- **Title**: `02. MCP-1`
- **URL**: `https://docs.google.com/document/d/16o9O3sidAzT6yFJlhUNajK3-WYDcjmERwx6bsdu8tSE/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - MCP/1 protocol specification (Runtime ↔ Management Backend)
  - Control commands and telemetry event framing
  - Correlation identifier distinctions (`message_id`, `correlation_id`, `command_id`, `runtime_event_seq`)
  - Strict rule: MCP/1 **NEVER** transports raw gradient or parameter tensors
- **When to Read**: When modifying `src/pbl4/management_protocol/`, runtime control messages, or telemetry streams.
- **Supporting Sources**: `[CONTRACTS]` (tab `Runtime Protocol (DTP-MCP)`), `[BACKEND]`, `[TRAINING_RUNTIME]`. Supporting sources cannot override `[MCP1]`.

---

### Management Backend, APIs, & Persistence

#### `[BACKEND]`
- **Title**: `02. Backend`
- **URL**: `https://docs.google.com/document/d/1FKzlY9OZ2s6J-XvUFxSg0y9mZOVrWjPFSFdKADyM5dk/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Management Backend architecture and internal service layering
  - Job orchestration, attempt scheduling, worker registration tracking
  - MCP client gateway and event ingestion pipeline
  - Separation from training data plane (Backend failure ≠ training failure)
- **When to Read**: When modifying backend business services, orchestration logic, or MCP gateway.
- **Supporting Sources**: `[BACKEND_API]`, `[POSTGRESQL]`, `[ARCH_SYSTEM]`. Supporting sources cannot override `[BACKEND]`.

#### `[BACKEND_API]`
- **Title**: `04. API Backend`
- **URL**: `https://docs.google.com/document/d/12c3-9x9S2wTSko49EKrkJ-poSfudLJrRGIDDWAxyGPo/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Public REST API endpoint definitions, request/response JSON schemas, error codes
  - WebSocket protocol for real-time telemetry streaming to CLI and WebUI
- **When to Read**: When modifying FastAPI routers, Pydantic schemas in `src/pbl4/backend/schemas/`, or WebSocket events.
- **Supporting Sources**: `[CONTRACTS]` (tab `Backend REST & WebSocket`), `[BACKEND]`. Supporting sources cannot override `[BACKEND_API]`.

#### `[POSTGRESQL]`
- **Title**: `01. PostgreSQL`
- **URL**: `https://docs.google.com/document/d/1J_b0NcCZibQSPJRCCz7r685FoDf32aPGbruGGRv05y0/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Repository boundary, Unit of Work, transaction ownership, locking and concurrency protection
  - Migration policy/mechanics, connection management, outage behavior, reconciliation and operational durability
  - Canonical table/field shape, identities and FK/unique/data-shape constraints belong to `[DATA_MODEL]`; persistence implementation cannot override that owner.
- **When to Read**: When modifying SQL migrations (`migrations/`), database models, or repository persistence code.
- **Supporting Sources**: `[CONTRACTS]` (tab `Backend ↔ PostgreSQL`), `[DOMAIN_MODEL]`. Supporting sources cannot override `[POSTGRESQL]`.

---

### Dataset Manager

#### `[DATASET_MANAGER]`
- **Title**: `01. Dataset Manager`
- **URL**: `https://docs.google.com/document/d/1IgUsy9kEaEQYKVpf7203n8H9tp8_R_yA62T6T3ltI20/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Dataset ingestion, partitioning, validation, and deterministic build process
  - Manifest generation and artifact materialization
  - Shard caching and worker HTTP serving mechanics
- **When to Read**: When modifying `src/pbl4/dataset_manager/` internals, partitioning algorithms, or artifact storage.
- **Supporting Sources**: `[DATASET_MANAGER_API]`, `[DATA_MODEL]`. Supporting sources cannot override `[DATASET_MANAGER]`.

#### `[DATASET_MANAGER_API]`
- **Title**: `03. API Dataset Manager`
- **URL**: `https://docs.google.com/document/d/1e50zebKoraR8JQBNOGwY5MsT-Ds1oH2AbOosDArazLQ/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Dataset Manager HTTP REST endpoints (build triggers, status polling, manifest fetch)
  - Shard artifact download protocol for workers
- **When to Read**: When modifying API routes in Dataset Manager or client fetch calls in Worker/Backend.
- **Supporting Sources**: `[CONTRACTS]` (tab `Dataset Manager API`), `[DATASET_MANAGER]`. Supporting sources cannot override `[DATASET_MANAGER_API]`.

---

### User Interfaces & Operations

#### `[CLI]`
- **Title**: `03. CLI`
- **URL**: `https://docs.google.com/document/d/1f--vbJfAVxptVf-ds0Kh62KWjjx6kYZyJqA0J5WMeUY/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**: `pblctl` command structure, arguments, output formatting, and REST API interactions.
- **When to Read**: When modifying `src/pbl4/cli/`.
- **Supporting Sources**: `[BACKEND_API]`. Supporting sources cannot override `[CLI]`.

#### `[WEBUI]`
- **Title**: `04. WebUI`
- **URL**: `https://docs.google.com/document/d/1U2aukpUsMBo6hwR0FLDz44fewhYjgc72pwCgFJz7kf0/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Web frontend architecture (React, Vite, TanStack Query)
  - UI state management, view hierarchy, and Backend REST/WebSocket consumption
  - Strict rule: WebUI talks **exclusively** to Management Backend; never directly to Runtime, Dataset Manager, or PostgreSQL
- **When to Read**: When modifying frontend code under `web/`.
- **Supporting Sources**: `[BACKEND_API]`. Supporting sources cannot override `[WEBUI]`.

#### `[DEPLOYMENT]`
- **Title**: `01. Triển khai`
- **URL**: `https://docs.google.com/document/d/1oJeJeMideC2mZVHT2qstFfc4q-xiUdt2SYlloslQEdQ/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**: Multi-process clustering, environment configs, local cluster launcher (`scripts/run_local_cluster.py`), deployment topologies.
- **When to Read**: When modifying cluster scripts, environment variables, or container configurations.
- **Supporting Sources**: `[ARCH_SYSTEM]`. Supporting sources cannot override `[DEPLOYMENT]`.

#### `[RECOVERY]`
- **Title**: `02. Phục hồi`
- **URL**: `https://docs.google.com/document/d/10cxyVaicpt7MlFi-_RxCd_6uDMRHfAeLLlIl7uL05wk/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**:
  - Fault tolerance, failure recovery flows, retry mechanics
  - Checkpoint restoration into **NEW Attempt** (attempts are immutable)
  - Re-hydration of model weights and dataset cursors
- **When to Read**: When modifying recovery logic, resume orchestration, or failure handling.
- **Supporting Sources**: `[CHECKPOINT]`, `[DOMAIN_MODEL]`. Supporting sources cannot override `[RECOVERY]`.

#### `[TESTING]`
- **Title**: `04. Kiểm thử`
- **URL**: `https://docs.google.com/document/d/12xfEWkUUgRmdHRzUaxE_zkAkZx8nR3g8ryr3BRZMFhI/edit`
- **Normative Locator**: Tab `Chính`
- **Semantic Ownership**: Test taxonomy (unit, integration, distributed, failure, architecture, benchmark), verification criteria, and test coverage standards.
- **When to Read**: When designing test strategies, CI pipelines, or release gates.
- **Supporting Sources**: `[ARCH_SYSTEM]`. Supporting sources cannot override `[TESTING]`.

---

### Contract Spreadsheets

#### `[CONTRACTS]`
- **Title**: `Contracts`
- **URL**: `https://docs.google.com/spreadsheets/d/1efvwTO9co7BSdOs7ftpdXKXpgs7mU-KrnDAJspPOHTo/edit`
- **Normative Locator**: Specific named sheets (tabs)
- **Sheet Mappings**:
  - `Quy ước chung`: Cross-system field naming conventions, global status codes, wire data types.
  - `Backend REST & WebSocket`: Detailed schema specifications for REST endpoints and WebSocket events (supports `[BACKEND_API]`).
  - `Runtime Protocol (DTP-MCP)`: Field-by-field wire tables for DTP/1 and MCP/1 (supports `[DTP1]` and `[MCP1]`).
  - `Dataset Manager API`: Endpoint definitions and schema tables for Dataset Manager (supports `[DATASET_MANAGER_API]`).
  - `Backend ↔ PostgreSQL`: Table definitions, columns and data-shape constraints support `[DATA_MODEL]`; repository/transaction and operational mappings support `[POSTGRESQL]`.
- **When to Read**: When implementing concrete wire codecs, API schemas, or DB migrations requiring exact field-level definitions.
- **Rule**: Spreadsheets specify concrete tabular projections. If a sheet contradicts the primary document owner, the primary document owner wins.

#### `[COORDINATION_MATRIX]`
- **Title**: `06. Ma trận điều phối`
- **URL**: `https://docs.google.com/spreadsheets/d/1zR-L6L4PAoVgW75VKji03i895ghu4M2OVovX38WFN6Q/edit`
- **Normative Locator**: Named sheets:
  - `Móc nối - Thành phần`
  - `Móc nối - Giao tiếp`
  - `Móc nối - Dữ liệu`
  - `Móc nối - Trạng thái`
  - `Móc nối - Quy tắc`
  - `Móc nối - Lỗi`
  - `Móc nối - Mã nguồn`
  - `Quy tắc chuẩn`
  - `Trạng thái chuẩn`
  - `Sự kiện chuẩn`
  - `Bao phủ`
  - `Móc nối - Kiểm thử`
- **Semantic Role**:
  - Supporting traceability and cross-reference matrix.
  - Links: `requirement/rule → canonical owner → component → communication → state → source code → test`.
  - **Non-Overriding Rule**: `[COORDINATION_MATRIX]` does **NOT** override subsystem owners (`[DTP1]`, `[MCP1]`, `[TRAINING_RUNTIME]`, `[SYNC_STRICT_BSP]`, `[DOMAIN_MODEL]`, `[CHECKPOINT]`, etc.). If a matrix sheet contradicts a primary document owner, the primary document owner wins and the conflict must be reported.
- **When to Read**: When cross-referencing requirements to tests, verifying coverage, or tracing cross-cutting state and event mappings across components.
- **Supporting Sources**: Subsystem primary documents govern all underlying semantics.
