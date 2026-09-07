---
name: doc-sync
description: >
  Workflow for keeping documentation in sync with code changes.
  Identifies canonical owners and affected projections to prevent
  bulk doc rewrites.
---

# Doc Sync

## Authority & Principles

1. **Canonical Authority**: Canonical design documents in Google Drive are the sole architectural owners.
2. **Projections**: Repository documents (`docs/IMPLEMENTATION_CONTRACT.md`, `README.md`, `AGENTS.md`) are projections and must never invent or override canonical semantics.
3. **No Bulk Rewrites**: Make surgical updates to affected sections only.

## Workflow

### 1. Canonical Approval First

Before modifying repository architecture projections:
```
Approved Canonical Document (Google Drive)
              ↓
docs/IMPLEMENTATION_CONTRACT.md Update
              ↓
AGENTS.md / SKILL.md / Code Docstrings Update
```

If an architecture change is proposed, it must be approved in Google Drive before updating the repository projection.

### 2. Identify Affected Projections

When code or contracts change:
- `docs/IMPLEMENTATION_CONTRACT.md` — mapping or process boundary changes.
- `AGENTS.md` / nested `AGENTS.md` — package-level invariant changes.
- `README.md` — developer-facing setup or process topology changes.
- `docs/OPEN_ISSUES.md` — resolve or update tracking when an open question is settled.

### 3. Verify Document Integrity

Confirm doc changes only reflect approved canonical facts without creating secondary architectures.
