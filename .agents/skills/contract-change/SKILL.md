---
name: contract-change
description: >
  Workflow for modifying domain state, resolved contracts, DB schema,
  API schema, dataset schema, or checkpoint schema.
---

# Contract Change

## When to Activate

Use this skill when modifying:
- Domain state machines or enums
- Resolved training contract structure
- PostgreSQL database schema / repository projection / migration
- REST API schemas (Pydantic models)
- Dataset manifest schema
- Parameter manifest schema

## Workflow

### 1. Verify Canonical Owner Approval

Verify the change against the approved canonical document in Google Drive:
```
Canonical Owner Approval
          ↓
Repository Projection Update
          ↓
Implementation Changes
          ↓
Migration / API / Frontend Consequences
          ↓
Tests After Implementation
```

### 2. Update Projections and Consumers

Update affected consumers across process boundaries:
- **DB Schema:** PostgreSQL schema DDL and `psycopg` repository methods.
- **API Schema:** FastAPI Pydantic models in `src/pbl4/management_backend/schemas/`.
- **Frontend:** TypeScript interfaces in `web/src/domain/` or `web/src/api/`.
- **Docs:** `docs/IMPLEMENTATION_CONTRACT.md`.

### 3. Verify

- Run architecture check: `uv run python scripts/check_architecture.py`.
- Run scaffold verifier: `uv run python scripts/verify_scaffold.py`.
- Verify frontend builds: `cd web && npm run typecheck && npm run build`.
- Add unit/contract tests after implementation is written.
