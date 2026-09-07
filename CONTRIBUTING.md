# Contributing to PBL4 Distributed Training

## Principles

1. **Canonical Docs First**: Architecture and wire formats are defined in the canonical Google Drive documents. Do not invent wire semantics, database ORMs, or state machines.
2. **Implementation with Tests**: Tests are created together with or after the corresponding implementation, not ahead of time. Implemented changes require passing tests before merge.
3. **Repository Architecture**:
   - DTP/1 is a custom protocol over persistent TCP.
   - Persistence uses PostgreSQL via `psycopg` with explicit SQL in repositories.
   - Training path correctness must not depend on Management Backend or Database availability.

---

## Local Setup

```bash
# Sync Python dependencies
uv sync

# Verify repository scaffold
uv run python scripts/verify_scaffold.py

# Format and lint check
uv run ruff format --check src scripts
uv run ruff check src scripts

# WebUI typecheck & build
cd web
npm ci
npm run typecheck
npm run build
cd ..
```

---

## Pull Request Workflow

1. Check `docs/IMPLEMENTATION_CONTRACT.md` for the canonical document governing the module you are modifying.
2. Implement scoped changes. Do not refactor unrelated subsystems.
3. Write corresponding tests covering the implemented behavior.
4. Run `uv run python scripts/check_architecture.py` and ensure zero boundary violations.
5. Submit PR with the PR template checklist completed.
