---
name: implementation-planner
description: >
  Build a codebase-grounded Execution Blueprint from an approved design and
  implementation plan, especially when the plan audited an older repository HEAD.
  This skill plans and orchestrates implementation; it never owns new semantics.
---

# Implementation Planner

Use this skill before coding when an approved implementation plan governs a large
feature, the work needs dependency-aware phases and checklists, or the plan was
written against an older commit. It is an orchestration workflow, not a semantic
primary. `contract-change` and `protocol-change` remain the only primary workflows
for unresolved semantic deltas.

## Authority and decision rule

Resolve sources through [SOURCE_REGISTRY](../../SOURCE_REGISTRY.md). Approved Design
owns semantics for its scope; an approved Implementation Plan is implementation
guidance below Design; supporting comparison/history explains migration only. Current
code is authoritative for implemented paths, symbols, ownership, tests, and mechanics,
but cannot override approved semantics.

Do not ask the user for an implementation choice when the answer can be derived from
the approved plan, canonical architecture, existing contracts, current code ownership,
tests, repository conventions, dependency direction, or the smallest compatible change.
Choose implementation mechanics yourself, including phase order, task dependencies,
reuse points, helper placement, tests, stale-path adaptation, task sizing, and preservation
of existing interfaces.

Block and ask only when either:

1. canonical owners genuinely conflict; or
2. a missing semantic fact permits multiple implementations that differ in public
   behavior, state transition, wire contract, persisted schema, failure semantics, or
   correctness.

Never reopen a decision already fixed by Design. Never invent a state, enum, protocol
version, persisted field, failure rule, or architecture improvement for convenience.

## Required workflow

### 1. Source Snapshot

Record:

- approved plan title, URL/source key, revision when available;
- governing canonical Design source(s) and exact normative locator;
- repository branch and current HEAD;
- plan audit branch/commit when stated;
- whether the audit anchor is reachable and the scoped diff from that anchor to HEAD;
- unavailable sources or tools as `NOT_AVAILABLE`, never as a pass.

Read repository `AGENTS.md`, applicable nested rules, the plan, its Design owner, current
source modules, tests, migrations/configuration, architecture checker, and relevant
governance skills before producing conclusions. Do not plan from document paths alone.

### 2. Frozen Decisions

Extract and preserve, at minimum:

- architecture and process ownership;
- dependency and communication boundaries;
- state machines and identity ownership;
- protocol/version and compatibility constraints;
- failure, disconnect, retry, and idempotency semantics;
- checkpoint/resume semantics;
- `KEEP UNCHANGED` items and explicit exclusions.

Give every frozen decision a source locator. A supporting comparison document cannot
override Design.

### 3. Codebase Drift Analysis

Compare the plan audit anchor with current HEAD for the plan's affected paths and
symbols. Classify every material difference as:

- `COMPATIBLE` — plan still maps directly;
- `RENAMED_OR_MOVED` — adapt to the verified current owner/path;
- `IMPLEMENTATION_CHANGED_SEMANTICS_SAME` — redesign tasks around current mechanics;
- `PLAN_PATH_STALE` — replace the stale path/symbol in the blueprint, preserving intent;
- `SEMANTIC_CONFLICT` — stop only the affected planning branch and route to the proper
  semantic primary.

Do not apply an old file list blindly. When an anchor is unavailable, inspect current
history and code, label exact diff unavailable, and continue only where semantics are
already resolved.

### 4. Impact Map

Inspect actual definitions and callers, then map:

```text
subsystem
  -> file/module
  -> symbol/class/function
  -> producer and consumer
  -> contract/protocol/persistence effect
  -> tests and verifier
```

Account for `ADD`, `MODIFY`, and `KEEP UNCHANGED`. Prefer existing abstractions and the
smallest compatible change; reject speculative redesign and opportunistic refactors.

### 5. Phase DAG

Convert the plan into dependency-aware phases. Audit any existing Phase 0..N ordering;
preserve it when still valid, and split or merge implementation tasks only when current
code dependencies require it. Do not change plan semantics.

Each phase must contain:

- objective;
- prerequisites;
- exact affected files and symbols;
- ordered tasks;
- tests and verification commands;
- exit criteria;
- incoming and outgoing phase dependencies.

Represent dependencies as a DAG, not merely a copied heading list.

### 6. Task Checklist

Every task entry must include all fields:

```text
TASK
WHY
SOURCE
FILES/SYMBOLS
DEPENDS ON
EXPECTED CHANGE
TEST
DONE WHEN
```

Tests must cover observable invariants and negative paths, not only happy-path wording.

### 7. Derived Implementation Decisions

This section is mandatory. Derive details from approved sources and current code instead
of asking the user. For every decision record:

```text
Decision
Evidence
Why this is implementation detail rather than new architecture
Alternatives rejected (when useful)
```

Examples include reusing an existing repository/service, adapting a stale plan path to
the current package, locating a pure helper at the lowest allowed dependency layer, or
preserving a compatibility field while extending an optional payload.

### 8. Risk and Conflict Check

Explicitly check for:

- stale path or symbol;
- duplicate contract sources;
- hidden cross-process or package coupling;
- accidental new state or identity owner;
- protocol-version or checkpoint-schema creep;
- unsupported backward-compatibility assumptions;
- Management Backend/DB/Dataset Manager entering the training critical path;
- omitted negative, recovery, integration, or architecture tests;
- task work that violates a frozen decision.

For Node Agent scope, preserve Worker -> Runtime DTP/1 and keep Agent outside the
training data plane. For DBS scope, keep `training_strategy = strict_bsp`; DBS is a
workload policy and does not create `dbs_bsp`, DTP/2, or Checkpoint V2.

## Semantic handoff and return

If drift exposes an unresolved semantic delta:

1. mark only the affected tasks `BLOCKED_SEMANTIC_RESOLUTION`;
2. route wire semantics to `protocol-change` or domain/API/DB/checkpoint semantics to
   `contract-change` as the single primary;
3. provide the conflict evidence, affected source owners, and blueprint nodes;
4. after resolution, return to this planner and update all dependent phases, tasks,
   derived decisions, tests, and exit criteria.

The planner never runs both primaries for the same delta and never becomes a second
semantic owner.

## Execution Blueprint output

Before implementation, produce one self-contained blueprint with these sections:

1. Source Snapshot
2. Frozen Decisions
3. Drift Analysis
4. Impact Map
5. Phase DAG
6. Task Checklists
7. Derived Implementation Decisions
8. Risks, Conflicts, and Explicit Non-Goals
9. Verification Matrix
10. Completion Accounting

Before coding, Completion Accounting may mark executable nodes `PLANNED` and semantic
conflicts `BLOCKED`; it must still account for every phase, task,
`ADD`/`MODIFY`/`KEEP UNCHANGED` item, exit criterion, and planned test. During
implementation, update the same blueprint rather than creating a disconnected status
list. Before claiming completion, no `PLANNED` node may remain: every node must be
`DONE`, `SKIPPED` with a technical reason, or `BLOCKED`. Reconcile drift discovered
during implementation before the blueprint is complete. Hand implementation to the
appropriate coding workflow, followed by `architecture-guard`, conditional
`distributed-verification`, conditional `doc-sync`, and `release-gate`.
