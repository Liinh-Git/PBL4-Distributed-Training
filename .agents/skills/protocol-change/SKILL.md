---
name: protocol-change
description: >
  Workflow for modifying DTP/1, MCP/1, framing, header, message,
  or tensor representation. Ensures wire compatibility and test coverage.
---

# Protocol Change

## When to Activate

Use this skill when modifying:
- DTP/1 or MCP/1 protocol definitions
- Framing format
- Header structure or codec
- Message definitions
- Tensor wire representation
- Constants in `protocol/constants.py` or `management_protocol/constants.py`

## Workflow

### 1. Read Canonical Specification

Review the canonical specification:
- Canonical document: `03. Mô hình dữ liệu`
- `docs/IMPLEMENTATION_CONTRACT.md` → Module-to-Canonical-Document mapping
- `src/pbl4/protocol/AGENTS.md`

### 2. Determine Approval Status

Determine whether the requested change is already approved in canonical docs:
- If the change alters wire semantics and canonical docs do NOT approve it: **STOP** and raise an issue in `docs/OPEN_ISSUES.md`.
- Protocol version bumps are architectural decisions requiring team approval, not autonomous choices.

### 3. Update Projection and Types

Update the schema/constants projection in `src/pbl4/protocol/` or `src/pbl4/management_protocol/` to reflect approved wire definitions.

### 4. Implement Codecs

Implement codecs only when explicitly assigned to the task.
Do NOT invent fields to pad byte sizes.

### 5. Add Wire & Malformed Tests Post-Implementation

AFTER the codec is implemented and before merge:
- Add exact-byte golden tests derived strictly from canonical spec byte vectors.
- Add tests for malformed, truncated, and corrupted frames.

### 6. Update Callers

After protocol implementation and tests pass, integrate into Runtime and Worker callers.
