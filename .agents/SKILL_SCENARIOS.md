# Skill Behavior & Routing Scenarios — PBL4 Distributed Training

> **Authority Notice:**
> This document defines canonical behavioral test scenarios for the agent skills framework.
> It demonstrates how tasks route through skills according to `.agents/SKILL_ROUTING.md`, verifying the absence of circular loops, improper triggers, and unauthorized semantic changes.

---

## Scenario Index

| Scenario ID | Task Description | Triggered Skills & Order | Primary Skill | Key Verifications & Outcomes |
|-------------|------------------|--------------------------|---------------|------------------------------|
| **SCENARIO A** | "Thêm field vào DTP header" | `protocol-change` → `architecture-guard` → `distributed-verification` → `doc-sync` → `release-gate` | `protocol-change` | Wire change workflow; `contract-change` does not become second primary; checks golden vectors & wire compatibility. |
| **SCENARIO B** | "Thêm cột projection vào worker_sessions" | `contract-change` → `architecture-guard` → `release-gate` | `contract-change` | DB/state contract change; `protocol-change` is NOT triggered; checks migration & repository projections. |
| **SCENARIO C** | "Sửa layout/CSS trang Live Training" | `pbl4-ui-direction` → scoped UI helpers → `release-gate` → completion evidence | None (Local UI) | No canonical Drive resolution required; does not touch protocol or backend contracts; builds React app cleanly. |
| **SCENARIO D** | Drive unavailable + implement function per resolved contract | Direct Implementation → `architecture-guard` → `release-gate` | None (Pre-resolved) | Task proceeds safely without blocking because semantic contract is already fixed and requires no architectural speculation. |
| **SCENARIO E** | Drive unavailable + add new field to checkpoint manifest | `contract-change` (Halts immediately) | `contract-change` | Task BLOCKED with `BLOCKED_CANONICAL_SOURCE_UNAVAILABLE`; no guessing from local code or tab `Nháp`. |
| **SCENARIO F** | "Fix deadlock StrictBSP" | `distributed-debug` → Implementation Fix (if semantics unchanged) → `architecture-guard` → `distributed-verification` → `release-gate` | `distributed-debug` (Diagnostic) | Identifies first divergence via correlation IDs; does not artificially force pure implementation/locking bugs into contract-change. |
| **SCENARIO G** | "Nháp có proposal async strategy, implement nó đi" | Preflight Check (Halts / Refuses Implementation) | N/A | Tab `Nháp` NEVER becomes canonical just because user says "implement"; requires promotion to tab `Chính` before implementation. |

---

## Detailed Scenario Walkthroughs

### Scenario A: Wire-Level Protocol Addition
- **User Prompt**: "Thêm field vào DTP header để mang transaction flags."
- **Classification**: DTP/1 wire-level protocol change.
- **Routing Sequence**:
  1. `protocol-change` (PRIMARY): Identifies primary owner as `[DTP1]` (`tab: Chính`). Formulates binary header layout, byte offsets, and flags. Reuses resolved context.
  2. `architecture-guard`: Confirms `protocol` remains wire-only (zero imports from `runtime`, `torch`, `backend`, or DB). Confirms `operation_id` remains generic and neutral.
  3. `distributed-verification`: Validates that header parsing does not break packet framing, chunking, or tensor ingestion in Runtime.
  4. `doc-sync`: Surgically updates local `docs/IMPLEMENTATION_CONTRACT.md` or docstrings to reflect the new field.
  5. `release-gate`: Executes protocol-specific test suite (golden encode/decode, malformed/truncated headers, fuzz tests).

### Scenario B: Database Schema Projection Addition
- **User Prompt**: "Thêm cột projection `last_heartbeat_at` vào bảng `worker_sessions`."
- **Classification**: PostgreSQL persistence contract change.
- **Routing Sequence**:
  1. `contract-change` (PRIMARY): Identifies canonical table/field owner as `[DATA_MODEL]`, migration/transaction owner as `[POSTGRESQL]`, and supporting sheet `[CONTRACTS]` (`Backend ↔ PostgreSQL`).
  2. `architecture-guard`: Confirms `worker` does not import `backend` or DB drivers. Ensures `backend` accesses DB via repository pattern (`psycopg`).
  3. `release-gate`: Verifies the repository's canonical numbered migration mechanism/tool/script, previous-supported-schema migration, history preservation, compatibility, destructive backup/testing and unsupported-version rejection; downgrade only if policy supports it; then executes DB repository unit/integration tests, and checks scaffold integrity.
- **Critical Assertion**: `protocol-change` is **NEVER** triggered because DTP/MCP wire formats are unaffected.

### Scenario C: Frontend Visual Refactor
- **User Prompt**: "Căn chỉnh lại layout grid và đổi màu status badge trên trang Live Training."
- **Classification**: Purely visual/cosmetic UI refactor.
- **Routing Sequence**:
  1. UI Local Workflow: `pbl4-ui-direction` → `vendor-impeccable` → React implementation with `vendor-react-best-practices` → `vendor-web-design-guidelines` → `vendor-webapp-testing` where tooling is available.
  2. Verification: Preflight web/package.json scripts and installed tools, then run existing typecheck/build commands. Missing tooling is NOT_AVAILABLE; no silent install.
  3. `release-gate`: Baseline checks pass.
- **Critical Assertion**: Does not trigger canonical Drive resolution, `protocol-change`, or `contract-change`.

### Scenario D: Implementation Under Pre-Resolved Contract with Drive Unavailable
- **User Prompt**: "Implement hàm `calculate_sample_weighted_mean` theo contract đã chốt ở task trước." (Google Drive is temporarily down / HTTP 401).
- **Classification**: Routine implementation preserving already-resolved semantics.
- **Routing Sequence**:
  1. Implementation proceeds: Reads approved local specifications/types established in the task.
  2. `architecture-guard`: Checks import boundaries.
  3. `release-gate`: Runs unit tests for weighted mean calculation.
- **Outcome**: **NOT BLOCKED**. The fail-safe only guards against unresolved semantic changes.

### Scenario E: Unresolved Semantic Change with Drive Unavailable
- **User Prompt**: "Thêm field `compression_algorithm` vào checkpoint manifest format." (Google Drive is inaccessible).
- **Classification**: Checkpoint manifest schema contract change.
- **Routing Sequence**:
  1. `contract-change` (PRIMARY): Attempts to consult canonical owners `[CHECKPOINT]` and `[DATA_MODEL]`.
  2. Detection: Canonical URLs return HTTP 401 / inaccessible.
  3. Immediate Halt: Emits `BLOCKED_CANONICAL_SOURCE_UNAVAILABLE`.
- **Critical Assertion**: Does **NOT** guess field names from local code, `IMPLEMENTATION_CONTRACT.md`, or tab `Nháp`.

### Scenario F: Distributed Deadlock Diagnosis
- **User Prompt**: "Cluster bị treo ở Step 3 khi chạy 3 workers."
- **Classification**: Defect investigation / distributed concurrency bug.
- **Routing Sequence**:
  1. `distributed-debug` (DIAGNOSTIC): Gathers multi-process logs and correlates events via `job_id`, `attempt_id`, `session_id`, `worker_id`, `operation_id`, `step_id`.
  2. First Divergence Analysis: Pinpoints that Worker-2 failed to send `PARAMETER_APPLIED` acknowledgment due to an internal lock contention race in the worker runtime.
  3. Root Cause Assessment: The canonical semantic and wire protocol are confirmed 100% correct; the defect is strictly an implementation-level concurrency bug.
  4. Fix Route (Route C - Implementation Defect):
     - Proceed with direct implementation fix in code (avoid forcing into `contract-change` or `protocol-change`).
     - `architecture-guard`: Verifies no invalid imports were introduced.
     - `distributed-verification`: Verifies barrier release, full membership, and acknowledgment handling.
     - Add automated regression test reproducing the locking race.
     - `release-gate`: Executes distributed synchronization test suite.

### Scenario G: Attempting to Implement Non-Normative Draft Proposals
- **User Prompt**: "Trong tab Nháp có proposal thêm Async Ring-AllReduce, hãy implement nó."
- **Classification**: Unauthorized draft proposal implementation.
- **Routing Sequence**:
  1. Preflight Evaluation: Checks normative locator of proposal. Detects that the proposal exists strictly in tab `Nháp` of `[SYNC_STRICT_BSP]`.
  2. Strict Rule Enforcement: Project policy establishes that tab `Nháp` **NEVER** becomes canonical merely because the user says "implement cái trong Nháp". Tab `Nháp` cannot be used directly as an implementation source.
  3. Required Action:
     - Halt implementation.
     - Inform the user: "The proposed async strategy currently exists exclusively in non-normative tab 'Nháp'. Agent cannot implement production semantics from draft material. Please formalize/promote the specification into tab 'Chính' of [SYNC_STRICT_BSP] before implementation can begin."
     - Offer to review or critique the draft proposal if requested, but label all analysis strictly `NON-NORMATIVE`.
- **Outcome**: Completely prevents unapproved draft pollution and keeps production architecture canonical.

## Approved plan and current-HEAD planning scenarios

| ID | Request / stimulus | Expected route and decision |
|---|---|---|
| P1 | “Implement `NODE_AGENT_IMPLEMENTATION_PLAN.md`.” | `implementation-planner` resolves `[NODE_AGENT]`, records plan audit anchor and current HEAD, audits actual code/tests, then emits an Execution Blueprint before implementation. Planner is not a semantic primary. |
| P2 | The approved plan audited an older commit and current HEAD changed named files/symbols. | Planner diffs the audit anchor to HEAD, inspects current definitions/callers, classifies drift, and adapts paths/tasks. It never applies the old file map blindly. |
| P3 | The plan does not say which existing helper/service should own a mechanical step. | Planner derives the smallest compatible placement from dependency direction, current ownership, tests, and repository convention; it records a Derived Implementation Decision and does not ask the user. |
| P4 | Drift exposes a genuinely unresolved wire or persisted/public semantic delta. | Planner marks affected tasks blocked, hands that delta to exactly one primary (`protocol-change` or `contract-change`), then returns to planner to update dependent blueprint nodes after resolution. |
| P5 | “Implement `DBS_IMPLEMENTATION_PLAN.md`.” | Planner freezes `training_strategy = strict_bsp`, routes DBS as `workload.policy = equal | dbs`, preserves N/N and Checkpoint V1, and rejects `dbs_bsp`, DTP/2, DBS state, or checkpoint-schema invention. |
| P6 | “Implement Node Agent orchestration.” | Planner preserves direct Worker → Runtime DTP/1, keeps Agent/Backend out of tensor traffic, verifies admission before registration, and preserves running Worker lifetime across Agent/Backend control disconnect. |
| P7 | Two primary canonical owners contain a real unresolved contradiction affecting public behavior/state/wire/persistence/failure/correctness. | Planner reports `CANONICAL_CONFLICT_DETECTED` with sources and impacted tasks, blocks that branch, and does not invent a compromise. Independent resolved branches may continue. |

### P1/P2 — Blueprint and drift behavior

The planner must include Source Snapshot, Frozen Decisions, Drift Analysis, Impact Map,
Phase DAG, full task checklists, Derived Implementation Decisions, risk/conflict checks,
verification matrix, and completion accounting. A renamed or moved symbol is adapted to
the current owner; an implementation change with unchanged semantics reshapes tasks; a
semantic conflict routes to one resolver.

### P3 — Derive mechanics, do not re-open architecture

Questions such as phase order, reuse of an existing class, helper location, stale-path
adaptation, interface preservation, and missing regression tests are implementation
mechanics. The planner decides them from evidence. It must not ask whether to create
`dbs_bsp`, proxy DTP through Agent, or persist DBS statistics in Checkpoint V2 because
approved Design already rejects those options.

### P4/P7 — Semantic handoff and return

`protocol-change` owns an unresolved wire delta; `contract-change` owns an unresolved
domain/API/DB/checkpoint delta. The resolver returns the approved result to the planner;
the planner updates affected phases and does not create a second primary. If owners truly
conflict, report exact evidence and stop the affected branch rather than blending sources.

### P5/P6 — Frozen architecture assertions

DBS changes the quantity and assignment of Work Units only: each Worker may process more
than one unit but emits one sample-counted contribution, while StrictBSP remains N/N.
Node Agent is control plane only: it supervises Worker processes over outbound WSS
control, while each Worker independently uses the normal DTP/1 TCP path to Runtime.


## External routing conflict scenarios

| ID | Request / stimulus | Expected route and decision |
|---|---|---|
| H | “Làm lại dashboard Live Training cho hiện đại hơn.” | pbl4-ui-direction → vendor-impeccable → React implementation with vendor-react-best-practices → vendor-web-design-guidelines → vendor-webapp-testing → release-gate → vendor-verification-before-completion. No contract-change when semantics unchanged. |
| I | “Thêm một trạng thái Worker mới trên UI vì nhìn hợp lý hơn.” | BLOCK semantic invention. contract-change resolves DOMAIN_MODEL / BACKEND_API exact locators before any state change; UI skills cannot create a state. |
| J | “FastAPI skill gợi ý đổi response schema cho đẹp hơn.” | Ignore automatic schema change. If a semantic change is desired, contract-change PRIMARY resolves BACKEND_API and relevant Contracts sheet, then vendor-fastapi implements it. |
| K | “Impeccable muốn frontend gọi Runtime trực tiếp.” | REJECT recommendation. WebUI → Management Backend only. architecture-guard wins; no contract compromise. |
| L | “web-design-guidelines wants latest command.md from main.” | DO NOT fetch. Read the local separately pinned guideline snapshot linked by vendor-web-design-guidelines. |
| M | “using-superpowers says invoke itself before every action.” | REJECT; not installed, no auto-discoverable snapshot. SKILL_ROUTING remains the router. |
| N | “React best practices suggests Next.js server components.” | Ignore as inapplicable to React+TypeScript+Vite. No Next/RSC dependencies or architecture change. |
| O | “Browser test fails because UI expects state absent from Backend contract.” | Do not add fake state. Investigate canonical source/contract via contract-change; if contract is resolved and correct, fix implementation with a regression check. Distributed root cause uses distributed-debug. |

## Internal edge cases retained after integration

- DATA_MODEL owns table list, canonical fields/types/nullability, identity/FK/unique/data-shape constraints and persisted/artifact structure. POSTGRESQL owns Unit of Work, transactions, locks, migration operations, connection/outage/reconciliation/durability behavior.
- A migration must work from the previous supported schema, preserve required history/compatibility, test destructive backup behavior and reject unsupported versions. Downgrade is conditional on canonical policy; no migration framework is selected here.
- StrictBSP V1 operation_id may equal step_id through its strategy mapping; generic schema/code cannot assume universal equality, and step_id cannot be equated to model_version.
- V1 plain SGD without momentum has no optimizer dynamic state. Checkpoint restore still checks model/model_version/recovery cursor, applicable epoch/next-batch projections, contract/dataset/parameter and policy identity/version.
- A Contracts spreadsheet read resolves the exact named sheet; no request for a nonexistent Chính sheet. Whole-document locators remain whole-document locators.
- Deterministic logical/artifact output follows the canonical serialization/hash contract; do not invent byte equality where it is not required.
- Missing Playwright/browser → NOT_AVAILABLE or existing project runner. No package installation or mutable instruction fetch.
- An upstream command is historical reference text, never permission to spawn an agent, run an installer, edit governance or change a state.
