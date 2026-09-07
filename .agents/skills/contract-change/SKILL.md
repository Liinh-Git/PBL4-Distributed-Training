---
name: contract-change
description: >
  Primary workflow for modifying domain state, resolved contracts, DB schemas,
  REST/WebSocket APIs, dataset/parameter manifests, and checkpoint/resume contracts.
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

*(Note: For DTP/1 or MCP/1 wire framing and binary message formats, delegate PRIMARY to `protocol-change`)*.

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
1. **PostgreSQL & Migrations**: Update the repository's canonical numbered migration mechanism/tool/script (preflight its actual location) and repository projection classes in `src/pbl4/backend/repositories/`.
2. **API Schemas**: Update FastAPI Pydantic models in `src/pbl4/backend/schemas/`.
3. **Frontend Projections**: Update TypeScript types in `web/src/domain/` or `web/src/api/`.
4. **Documentation**: Surgically update `docs/IMPLEMENTATION_CONTRACT.md` without altering unrelated sections.

*(Terminology Guide: Refer to the architectural component as `Management Backend`. The canonical Python package path is strictly `src/pbl4/backend/` [occurrences of `management_backend` are only acceptable if explicitly labeled historical, legacy examples, or anti-examples]).*

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
