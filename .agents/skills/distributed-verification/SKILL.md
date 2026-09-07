---
name: distributed-verification
description: >
  Verification checklist for changes to the core training path.
  Ensures BSP invariants, aggregation correctness, and rejection semantics.
---

# Distributed Verification

## When to Activate

Use this checklist when modifying:
- Runtime synchronization (`runtime/synchronization/`)
- Gradient aggregation (`Aggregator`, `UpdateEngine`)
- Parameter broadcast mechanics
- Worker registration and connection handling
- Checkpoint coordination

## Semantic Checklist

### StrictBSP V1 Invariants
- [ ] **For StrictBSP V1: no update before full membership**: UpdateEngine is not triggered until all `expected_workers` required by strategy have contributed.
- [ ] **For StrictBSP V1: exactly one contribution per worker per step**: Each worker session submits at most one contribution per step/operation identity.
- [ ] **For StrictBSP V1: duplicate contribution rejected**: Submitting a duplicate contribution for the current step is rejected per canonical error semantics.
- [ ] **For StrictBSP V1: stale contribution rejected**: Contributions targeting outdated model versions are rejected.
- [ ] **For StrictBSP V1: future contribution rejected**: Contributions targeting future model versions are rejected.

*Note: `step_id`, `model_version`, and `operation_id` are distinct concepts (in StrictBSP V1, `operation_id` maps 1:1 to `step_id`, but they remain separate architectural abstractions).*

### Aggregation Correctness
- [ ] **Sample-weighted aggregation**: Admitted gradient tensors are combined via sample-count weighted aggregation.
- [ ] **PARAMETER_APPLIED acknowledgment**: Participating worker acknowledges that the specified canonical parameter/model version has been applied locally.

### Checkpoint Cadence (StrictBSP V1)
- [ ] **StrictBSP V1 Durability Gate**: Checkpoint policy is `after_each_model_update_blocking`. Checkpoint `COMPLETE` is durable before Step `COMMITTED` / progression to next step. Synchronization/model update alone is not sufficient to progress.

### Network Path Uniformity
- [ ] **Worker-0 TCP path**: Whichever worker receives logical worker_id=0 communicates over the identical DTP/1 TCP socket path. No in-process shortcut.
