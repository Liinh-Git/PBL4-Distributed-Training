# Runtime Package — AGENTS.md

> Rules specific to `src/pbl4/runtime/`.

## Ownership

| Component | Owns |
|-----------|------|
| `Coordinator` | Attempt lifecycle transitions |
| `WorkerRegistry` | Worker membership / session state |
| `UpdateEngine` | CanonicalModel writes (+ restore path) |
| `SynchronizationPolicy` | Admission and update-ready synchronization decisions |
| `CheckpointPolicy` | Checkpoint cadence and timing decisions |
| `CheckpointManager` | Durability mechanism (saving/restoring checkpoints) |
| `EventEmitter` | Bounded outbound event buffering; background Redis Streams delivery when configured, otherwise MCP/1 |

## Invariants

1. **CanonicalModel is single-writer** — Only `UpdateEngine` and the checkpoint restore path may write to `CanonicalModel`. Workers never call `optimizer.step()` on canonical state.

2. **SynchronizationPolicy ≠ CheckpointPolicy** — Sync policy owns admission and aggregation-ready decisions only. Checkpoint timing is owned by `CheckpointPolicy`.

3. **No blocking external I/O under internal state locks** — Runtime state operations must not block on external database queries, HTTP calls, or slow network consumers.

Redis Streams is limited to management events in the background publisher. Redis I/O must never run in the training loop or under state locks. Redis failure must not stop training; the existing bounded eviction policy applies. Commands, results and state snapshots stay on MCP/1; events use exactly one configured transport.

4. **expected_workers from StrategyContext** — Never hard-code worker count. `expected_workers` is supplied via `StrategyContext` from the resolved contract.

5. **Worker-0 uses identical TCP path** — All workers connect over DTP/1 via TCP. No special in-process shortcut exists for Worker-0.

## Synchronization Subpackage

`runtime/synchronization/` must NOT import:
- Checkpoint mechanisms or policies
- Database or HTTP modules
- Transport-level connection details
