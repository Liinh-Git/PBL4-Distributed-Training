---
name: architecture-guard
description: >
  Validates architectural constraints when adding packages, moving files,
  refactoring dependencies, or creating new services/gateways.
---

# Architecture Guard

## When to Activate

Use this skill when:
- Adding a new package or module
- Moving files between packages
- Refactoring import dependencies
- Creating a new service, gateway, or client
- Adding a new third-party dependency

## Workflow

### 1. Read Architecture Contract

Before making changes, read:
- `docs/IMPLEMENTATION_CONTRACT.md` § Dependency Direction
- `AGENTS.md` rules #2, #3, #4, #5, #6
- The relevant nested `AGENTS.md` for affected packages

### 2. Check Allowed Dependency Direction

Verify the change respects allowed import directions:
```
runtime              → protocol, transport, management_protocol, common
worker               → protocol, transport, adapter, common
management_backend   → management_protocol, common
dataset_manager      → common
all packages         → common
```

Forbidden directions:
- `protocol` → runtime, worker, management_backend, dataset_manager, torch, db
- `transport` → runtime, synchronization, training semantics, protocol
- `worker` → management_backend, PostgreSQL, dataset_manager impl
- `management_backend` → runtime training implementation
- `dataset_manager` → runtime training implementation, management_backend
- `runtime.synchronization` → checkpoint, transport, db, http
- `runtime` → management_backend, web frameworks, DB drivers

### 3. Run Standalone Architecture Check

```bash
uv run python scripts/check_architecture.py
```

Must exit 0 with zero boundary violations.

### 4. Report Boundary Impact

Document:
- Which process boundaries are affected
- Whether the change introduces a new cross-boundary dependency
- Whether any invariant from `AGENTS.md` is affected
