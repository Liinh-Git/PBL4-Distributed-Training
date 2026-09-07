---
name: release-gate
description: >
  Pre-release and milestone checklist. Ensures quality gates pass
  before tagging a release or completing a milestone.
---

# Release Gate

## When to Activate

Use this skill before:
- Tagging a repository milestone or release
- Merging major cross-cutting PRs

## Stage-Aware Verification Gates

Run gates appropriate for the current project stage. All applicable gates must pass.

### 1. Code Style & Compilation
```bash
# Code formatting and linting
uv run ruff format --check src scripts
uv run ruff check src scripts

# Python syntax compilation
uv run python -m compileall src scripts
```

### 2. Architecture & Scaffold Constraints
```bash
# Boundary constraint check
uv run python scripts/check_architecture.py

# Repository layout and dependency hygiene
uv run python scripts/verify_scaffold.py
```

### 3. WebUI Integrity
```bash
cd web
npm ci
npm run typecheck
npm run build
cd ..
```

### 4. Automated Tests (When Implemented)
*(Applicable when feature test suites exist for implemented features)*:
```bash
# Run the relevant test suites that exist for the implemented feature/stage
uv run pytest -v
```

### 5. Git & Secret Hygiene
- [ ] No uncommitted or untracked changes
- [ ] No secrets or `.env` files tracked
- [ ] No runtime artifacts (`.var/`, checkpoints, logs) in Git
