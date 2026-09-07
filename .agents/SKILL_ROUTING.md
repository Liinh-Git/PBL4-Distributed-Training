# Skill Routing & Orchestration — PBL4 Distributed Training

> **Authority Notice:**
> This document defines the execution pipeline, delegation rules, and priority ordering for agent skills within `.agents/`.
> It prevents circular invocation loops, conflicting primary workflows, and redundant canonical re-resolutions.

---

## 1. Core Orchestration Principles

1. **Exactly One Primary Workflow per Semantic Delta**: A single architectural or semantic change must have exactly ONE primary skill driving the resolution. Secondary skills act strictly in supporting or verification roles.
2. **Context Reuse (`resolved canonical source set`)**: When the primary skill resolves the canonical source set and establishes wire/contract invariants, subsequent supporting skills in the same task **MUST REUSE** that context. Supporting skills must **NEVER** restart the primary workflow or re-resolve sources from scratch.
3. **Strict Termination**: Skills must exit cleanly once their specific boundary or verification checks are complete without calling upstream skills.
4. **Diagnostic Separation**: `distributed-debug` is a diagnostic workflow activated solely during defect investigation; it is never triggered automatically during standard development.

---

## 2. Primary Workflow Selection

Before triggering any skill, classify the task. The diagram below applies only to semantic changes; non-semantic implementation and visual work use Section 5:

```
                                  [ Incoming Task / Delta ]
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      │ Wire-level DTP/1 or MCP/1 change?             │
                      │ (framing, header, binary payload, codec)      │
                      └───────────────────────┬───────────────────────┘
                                              │
                              YES ────────────┴──────────── NO
                               │                             │
                               ▼                             ▼
                    [ protocol-change ]             [ contract-change ]
                    PRIMARY WORKFLOW                PRIMARY WORKFLOW
                    (Wire & Protocol)               (Domain, State, DB, API,
                                                     Manifest, Checkpoint)
```

### Rule A: Wire-Level Protocol Changes → `protocol-change` (PRIMARY)
Use `protocol-change` as PRIMARY when modifying:
- DTP/1 binary framing, header layout, flags, tensor wire format
- MCP/1 message framing, control commands, telemetry wire format
- Wire-level correlation fields (`operation_id`, `message_id`, `correlation_id`, `runtime_event_seq`)
- Packet serialization/deserialization codecs in `protocol` or `management_protocol`
*Supporting role*: `contract-change` acts strictly as a supporting skill if high-level projections (e.g. documentation or manifest references) require synchronization.

### Rule B: Domain, API, Schema, & State Changes → `contract-change` (PRIMARY)
Use `contract-change` as PRIMARY when modifying:
- Domain state machines, lifecycle enums (Job, Attempt, Worker Session, Step)
- Public REST API schemas or WebSocket event models (FastAPI / Pydantic)
- PostgreSQL database schemas, migrations, or repository query contracts
- Dataset Manager HTTP REST contracts
- Dataset manifest or Parameter manifest schemas
- Checkpoint storage schemas or recovery/resume contracts
- Resolved Job contracts

---

## 3. The Standard 5-Phase Pipeline

Once the Primary Workflow is established, execution proceeds sequentially through the following pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 1: PRIMARY WORKFLOW                                                   │
│   • protocol-change  (if wire format)                                       │
│   • contract-change  (if domain, state, DB, API, manifest, checkpoint)     │
│   → Resolves canonical owner from SOURCE_REGISTRY.md                        │
│   → Resolves and reads exact normative locator in SOURCE_REGISTRY               │
│   → Defines exact wire/domain invariants & fail-safe if Drive unavailable    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 2: BOUNDARY & INVARIANT GUARD                                         │
│   • architecture-guard                                                      │
│   → Verifies package import boundaries & allowed directions                 │
│   → Enforces 11 core invariants (SynchronizationPolicy seam,                │
│     BarrierManager isolation, operation_id neutrality, etc.)                 │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 3: TRAINING CORRECTNESS VERIFICATION (Conditional)                   │
│   • distributed-verification                                                │
│   → ACTIVATED ONLY IF the change impacts core distributed training:         │
│     (Runtime synchronization, gradient aggregation, parameter broadcast,    │
│      worker admission, checkpoint durability gate)                          │
│   → Evaluates Strict BSP invariants, negative rejection tests, oracle match │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 4: PROJECTION SYNCHRONIZATION                                         │
│   • doc-sync                                                                │
│   → Runs AFTER semantics are fully resolved                                 │
│   → Surgically updates repository projections (docs, docstrings, schemas)   │
│   → NEVER invents semantics or restarts the pipeline                        │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Phase 5: CHANGE-AWARE RELEASE GATE                                          │
│   • release-gate                                                            │
│   → Runs preflight checks (verifies scripts exist before running)           │
│   → Executes change-specific test suites (protocol, runtime, DB, etc.)      │
│   → Verifies static typing, linting, and git hygiene                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Standalone Diagnostic Mode (`distributed-debug`)

`distributed-debug` operates outside the standard feature development pipeline:
- **Trigger**: Invoked **ONLY** when actively investigating bugs, hangs, deadlocks, discrepancies, or test failures in distributed execution.
- **Principle**: Finds the *first divergence* using structured correlation IDs. Never fixes defects by inserting arbitrary sleeps or increasing timeouts.
- **Three-Way Handoff After Diagnosis**:
  Once the first divergence is isolated and root cause classified:
  1. **Route A: Protocol Wire / Framing Defect**:
     - If the defect originates from invalid header codecs, frame desync, or wire-level errors → hand off to `protocol-change` (PRIMARY).
  2. **Route B: Canonical Semantic / State / Contract Defect**:
     - If the defect originates from invalid domain state transitions, DB schema mismatch, or checkpoint contract discrepancies → hand off to `contract-change` (PRIMARY).
  3. **Route C: Implementation Defect (Canonical Semantics Unchanged)**:
     - If canonical semantics and wire contracts are already correct, and the defect is purely a local concurrency, locking, race condition, or logic bug in code:
       ```
       distributed-debug (isolates divergence & reproduces failure)
              ↓
       Confirm canonical semantics unchanged
              ↓
       Direct implementation bug fix (preserves contracts)
              ↓
       architecture-guard (if package boundaries/imports touched)
              ↓
       distributed-verification (if distributed training correctness affected)
              ↓
       Add automated regression test
              ↓
       release-gate (change-aware verification)
       ```
       *(Do NOT artificially force pure runtime implementation bugs into `contract-change` or `protocol-change`).*

---

## 5. Non-Semantic / Local Implementation Workflows

Third-party helpers operate only after any required semantic resolution. Read the exact normative locator declared in SOURCE_REGISTRY, not a universal tab name. Reuse the resolved source set. Supporting skills return to the current workflow; no circular re-entry or second primary. Canonical source → exact normative locator → internal semantic/governance skills → approved local projections → third-party helpers → current code. PBL4 instructions win conflicts outright.

### Backend implementation

- Semantics unchanged: architecture context → vendor-fastapi when applicable → relevant tests → release-gate → vendor-verification-before-completion.
- API semantics changed: contract-change PRIMARY → architecture-guard as relevant → vendor-fastapi → tests → doc-sync → release-gate → vendor-verification-before-completion.
- Persisted table/field/identity/data-shape constraints resolve to DATA_MODEL; repository/Unit of Work/transaction/migration operations resolve to POSTGRESQL. Supporting Contracts sheets cannot override either owner.
- Preflight actual package paths. The historical scaffold may differ from canonical backend naming; do not rename it or create a second package as a helper side effect.

### WebUI design and implementation

Visual-only flow:

```text
pbl4-ui-direction
  → vendor-impeccable
  → React implementation with vendor-react-best-practices
  → vendor-web-design-guidelines (post-implementation audit)
  → vendor-webapp-testing (browser acceptance)
  → release-gate
  → vendor-verification-before-completion
```

Pure CSS/layout requires no canonical Drive semantic resolution. If UI maps changed/new state or API meaning, contract-change PRIMARY runs first, followed by conditional architecture/correctness checks and doc-sync. WebUI talks only to Management Backend. UI quality is never grounds for inventing states or changing contracts.

For a narrow React implementation/performance task without design changes, use vendor-react-best-practices directly after architecture context; skip design helpers with an explicit not-applicable reason. Browser/rendered checks follow impact and tool availability. Preflight package scripts and installed tooling before frontend build/typecheck; missing tools mean NOT_AVAILABLE, never an implicit install.

### Other implementation and bug fixes

Semantics-preserving refactor → architecture-guard when relevant → implementation/regression tests → release-gate → vendor-verification-before-completion. Distributed bugs begin with distributed-debug, then Route A protocol-change, Route B contract-change or Route C direct implementation fix as described above. Helpers may support that route without replacing diagnosis or semantic ownership.

### Security / milestone / large blast-radius diffs

A scoped differential review may be useful after implementation and before release-gate. vendor-differential-review and vendor-requesting-code-review are NOT installed in this setup; see THIRD_PARTY_AUDIT. Do not invoke missing wrappers or fetch them. Use an explicitly requested local review with existing tools; reconsider vendoring only in a future authorized .agents maintenance task with fresh audit. No review helper auto-runs on tiny changes.

### Governance-only changes

For explicitly authorized .agents maintenance, preserve existing corrections; inspect the internal semantic invariants, local links, discovery boundary, provenance, routing scenarios and supply-chain findings. Use architecture-guard and release-gate proportionally. Production suites unrelated to instruction changes may be SKIPPED with reason. Vendor tools cannot independently edit source ownership or routing.

## 6. Installed helper entrypoints

- [pbl4-ui-direction](skills/pbl4-ui-direction/SKILL.md): PBL4 visual implementation direction.
- [vendor-impeccable](skills/vendor-impeccable/SKILL.md): scoped design craft.
- [vendor-react-best-practices](skills/vendor-react-best-practices/SKILL.md): React+TS+Vite implementation.
- [vendor-web-design-guidelines](skills/vendor-web-design-guidelines/SKILL.md): local guideline audit.
- [vendor-webapp-testing](skills/vendor-webapp-testing/SKILL.md): local browser behavior tests.
- [vendor-fastapi](skills/vendor-fastapi/SKILL.md): resolved FastAPI contract implementation.
- [vendor-verification-before-completion](skills/vendor-verification-before-completion/SKILL.md): evidence discipline after release-gate.

Only intended skills/*/SKILL.md entrypoints are active. vendor snapshots are reference-only, renamed and immutable by policy. Missing or conflicting upstream instructions never authorize runtime fetch/install, semantic invention or a new primary workflow.
