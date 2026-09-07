# Dataset Manager Package — AGENTS.md

> Rules specific to `src/pbl4/dataset_manager/`.

## Role

The Dataset Manager handles dataset ingestion, preprocessing, partitioning into worker shards, and serving shards to workers via HTTP.

## Invariants

1. **No barrier knowledge** — Dataset Manager does not know about synchronization barriers or training steps. It builds artifacts before training begins.

2. **No gradient knowledge** — Dataset Manager does not handle, reference, or import gradient-related code.

3. **No canonical model knowledge** — Dataset Manager does not know about `CanonicalModel`, model versions, or parameter updates.

4. **Build artifacts before training** — All dataset processing (import, preprocess, partition) happens before the training attempt enters `RUNNING` state.

5. **READY requires registration acknowledgement** — The dataset build becomes READY only after artifact materialization and integrity verification are complete AND management registration has been successfully acknowledged by Management Backend. Publish/verify alone is NOT sufficient.

6. **Not in the training hot path** — After all assigned worker shards are ready (`SHARD_READY`), workers read from local shard cache. Dataset Manager is not contacted during per-step training.

## Dataset Path

```
Management Backend → control/catalog → Dataset Manager
Runtime → read root manifest / verify identity → Dataset Manager
Workers → HTTP artifact provisioning → Dataset Manager
```
