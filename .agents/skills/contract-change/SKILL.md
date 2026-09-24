---
name: contract-change
description: >
  Primary workflow for modifying domain state, resolved/workload contracts, Node and
  WorkerAllocation contracts, DB schemas, REST/WebSocket APIs, manifests, and recovery.
---

# Contract Change

## 1. When to Activate

Use this skill as the **PRIMARY WORKFLOW** when modifying:
- Domain state machines, lifecycle enums, or entity transitions (Job, Attempt, Worker Session, Step)
- Resolved Job or Attempt training contracts
- PostgreSQL database schemas, the repository's canonical numbered migration mechanism/tool/script, or repository query contracts
- REST API schemas (FastAPI Pydantic models) or WebSocket event models
- Dataset manifest schemas or partition descriptors
- Parameter manifest schemas or weight distribution descriptors
- Checkpoint storage schemas, metadata structures, or recovery/resume contracts
- Node identity/lifecycle, enrollment, WorkerAllocation, managed-admission projections, resource snapshots, or Node control APIs
- Workload contract fields such as `workload_policy`, `work_units_per_step`, and resolved Work Unit projections

*(Note: For DTP/1, MCP/1, or Backend ↔ Node Agent control-wire schemas and message formats, delegate PRIMARY to `protocol-change`)*.

---

## 2. Step 1: Classify Contract Kind & Resolve Canonical Owner

Map the proposed change to its specific canonical owner from [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):

| Contract Kind | Primary Canonical Owner | Supporting References |
|---|---|---|
| **1. Domain / Lifecycle / State** | `[DOMAIN_MODEL]` (`tab: Chính`) | `[DATA_MODEL]`, `[TRAINING_RUNTIME]` |
| **2. Resolved Job / Attempt Contract** | `[DOMAIN_MODEL]` (`tab: Chính`) | `[TRAINING_RUNTIME]`, `[CONTRACTS]` |
| **3. DTP Wire Contract** | *Delegate PRIMARY to `protocol-change`* | `[DTP1]`, `[CONTRACTS]` (`Runtime Protocol (DTP-MCP)`) |
| **4. MCP Wire Contract** | *Delegate PRIMARY to `protocol-change`* | `[MCP1]`, `[CONTRACTS]` (`Runtime Protocol (DTP-MCP)`) |
| **5. Backend REST & WebSocket** | `[BACKEND_API]` (`tab: Chính`) | `[CONTRACTS]` (`Backend REST & WebSocket`), `[BACKEND]` |
| **6. Dataset Manager HTTP API** | `[DATASET_MANAGER_API]` (`tab: Chính`) | `[CONTRACTS]` (`Dataset Manager API`), `[DATASET_MANAGER]` |
| **7a. Persisted tables / fields / data-shape constraints** | `[DATA_MODEL]` (`tab: Chính`) | `[POSTGRESQL]`, `[CONTRACTS]` (`Backend ↔ PostgreSQL`) |
| **7b. Repository / transaction / migration mechanics** | `[POSTGRESQL]` (`tab: Chính`) | `[DATA_MODEL]`, `[CONTRACTS]` (`Backend ↔ PostgreSQL`) |
| **8. Dataset Manifest Schema** | `[DATA_MODEL]` (`tab: Chính`) | `[DATASET_MANAGER]` |
| **9. Parameter Manifest Schema** | `[DATA_MODEL]` (`tab: Chính`) | `[TRAINING_RUNTIME]` |
| **10a. Checkpoint artifact schema** | `[DATA_MODEL]` (`tab: Chính`) | `[CHECKPOINT]`, `[RECOVERY]` |
| **10b. Checkpoint cadence / durability mechanics** | `[CHECKPOINT]` (`tab: Chính`) | `[DATA_MODEL]`, `[RECOVERY]` |
| **10c. Resume flow / recovery compatibility** | `[RECOVERY]` (`tab: Chính`) | `[CHECKPOINT]`, `[DATA_MODEL]` |
| **11. Node / WorkerAllocation / enrollment contract** | `[NODE_AGENT]` (whole document) | `[DOMAIN_MODEL]`, `[DATA_MODEL]`, `[BACKEND_API]`, `[POSTGRESQL]` |
| **12. DBS / Work Unit workload contract** | `[DBS_WORKLOAD]` (whole document) | `[DOMAIN_MODEL]`, `[TRAINING_RUNTIME]`, `[SYNC_STRICT_BSP]`, `[DTP1]` |

---

## 3. Drive Unavailable Fail-Safe

> [!WARNING]
> If modifying or resolving contract specifications and the primary canonical source on Google Drive is inaccessible:
> - **STOP** semantic changes immediately.
> - **DO NOT** extrapolate contracts from local code, `docs/IMPLEMENTATION_CONTRACT.md`, or tab `Nháp`.
> - **Report**:
>   ```text
>   BLOCKED_CANONICAL_SOURCE_UNAVAILABLE: Cannot access canonical source [<SOURCE_KEY>] (<URL>) to resolve <contract kind>. Halting contract change.
>   ```

---

## 4. Multi-Boundary Projection Synchronization

When a contract changes, update all affected consumers across process boundaries:
1. **PostgreSQL & Migrations**: Update the repository's canonical numbered migration mechanism/tool/script (preflight its actual location) and repository projection classes in `src/pbl4/management_backend/repositories/`.
2. **API Schemas**: Update FastAPI Pydantic models in `src/pbl4/management_backend/schemas/`.
3. **Frontend Projections**: Update TypeScript types in current owners under `web/src/types/` and API consumers under `web/src/api/`.
4. **Documentation**: Surgically update `docs/IMPLEMENTATION_CONTRACT.md` without altering unrelated sections.

The architectural component is `Management Backend`; the current repository package is
`src/pbl4/management_backend/`. Do not create a second backend package or rename it as a
side effect of a feature task.

### Node contract guards

- Keep Node identity/lifecycle, one-time enrollment, `WorkerAllocation`, resource
  persistence, and Backend API/schema changes under `[NODE_AGENT]` plus the appropriate
  data/API owner.
- Keep admission credentials out of `resolved_contract` and `contract_hash`; Runtime
  still assigns Worker session/rank after verification.
- Do not make Node Agent, Management Backend, or PostgreSQL part of the gradient/update
  critical path.

### DBS contract guards

- `training_strategy` remains `strict_bsp`; do not introduce `dbs_bsp` or a DBS-specific
  synchronization class.
- Workload contract is limited to approved fields such as `policy: equal | dbs` and
  `work_units_per_step`; derive Work Unit size/global sample count from existing dataset
  and contract values instead of duplicating them.
- Do not create DBS-specific Attempt, WorkerSession, or Step states.
- Do not create Checkpoint V2 or persist runtime-only WorkloadPlan/statistics solely for
  DBS; preserve the approved resume warm-up behavior.

---

## 5. Standard Pipeline Integration

Following `.agents/SKILL_ROUTING.md`:
1. `contract-change` operates as the **PRIMARY WORKFLOW** (reusing the `resolved canonical source set`).
2. Passes to `architecture-guard` if boundary dependencies, shared structures, or package imports are modified.
3. **Conditional Correctness Phase**: Passes to `distributed-verification` if the contract change affects:
   - Strict BSP correctness or contribution identity
   - Parameter aggregation or `PARAMETER_APPLIED` semantics
   - Checkpoint durability gates or Step `COMMITTED` progression
   - Worker registration, session lifecycle, or resume mechanics
4. Passes to `doc-sync` after semantics and interfaces are resolved.
5. Passes to `release-gate` for schema, migration, and contract verification.
