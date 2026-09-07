---
name: distributed-debug
description: >
  Systematic debugging workflow for distributed training issues.
  Focuses on correlation context, semantic event tracing, and
  root cause classification.
---

# Distributed Debug

## When to Activate

Use this skill when investigating distributed issues:
- Worker connection or handshake failures
- Premature or hanging synchronization barriers
- Gradient aggregation discrepancies
- Parameter broadcast stall
- Disconnection / failure detection anomalies

## Workflow

### 1. Stage-Aware Reproduction

When core components are implemented:
- Reproduce using multi-process launcher or dedicated scenario script.
- Do not randomly alter timeouts or inject arbitrary sleeps to "make it work".

### 2. Capture Correlation Context

Collect logs from all participating processes and align events using canonical correlation fields:
- `attempt_id`: Specific execution attempt
- `session_id`: Worker connection session (uint64)
- `worker_id`: Assigned logical worker rank
- `operation_id`: DTP/1 generic 8-byte correlation identifier
- `model_version`: Parameter version counter
- `step_id`: Step iteration index (StrictBSP projection)
- `runtime_event_seq`: Monotonic runtime event sequence

### 3. Identify First Divergence

Trace sequence of semantic events across processes:
- Which process failed to progress or emitted an unexpected event?
- Was an arrival missed at the synchronization barrier?
- Did a socket timeout or frame corruption occur?

### 4. Classify and Fix Root Cause

Classify root cause into:
- **Transport:** Socket closure, partial write/read, framing error.
- **Protocol:** Magic mismatch, malformed header, unsupported version.
- **Policy:** Incorrect admission or update-ready barrier condition.
- **Concurrency:** Deadlock, race condition, state transition violation.

Fix the minimum root cause cleanly.

### 5. Regression Test Before Merge

Once the root cause is fixed, add an automated regression test reproducing the failure condition before opening a PR.
