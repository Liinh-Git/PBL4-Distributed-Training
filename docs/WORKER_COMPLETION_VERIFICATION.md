# Worker completion verification

Branch: `fix/end_worker_early`.

## Behavior covered

- DTP STOP/ATTEMPT_COMPLETED parks the Worker beyond its reconnect budget.
- Completion blocks queued work, late computation results, new gradients and heartbeats.
- FAILED/ABORTED retain existing behavior; unmanaged Runtime admission is rejected.
- Completed allocations retain durable STOPPED intent while Agent is offline.
- Maintenance sends stop commands outside transactions and retries unconfirmed stops.
- Pending stops do not become Worker-start timeout failures.
- Terminal event/snapshot projections select successful-completion cleanup.
- Real SmallCNN sync and async training uses Worker OS processes spawned by Node
  Agent supervisor. After Runtime closes DTP, processes remain RUNNING until the
  Agent STOP_WORKER handler stops them and emits WORKER_STATUS ENDED. Duplicate stop
  is accepted. Async also fences/rejoins the same Agent-owned PID before training.

## Evidence

| Suite | Result |
| --- | --- |
| Unit and Backend gateway/restart tests | 541 passed, 140 subtests passed; one known fixture failure deselected |
| Integration plus coordinator/Worker logic | 77 passed, 54 skipped, 10 subtests passed |
| Updated managed-process/rejoin acceptance | 2 passed on final test revision |
| Distributed correctness | Covered by managed-process, DBS coordination, SGD oracle, checkpoint/resume and async integration tests |
| Failure | Covered by Node Agent fault injection and DBS failure integration tests |
| Architecture | `uv run python scripts/check_architecture.py` passed |
| Benchmark | Skipped: no performance claim or scheduling algorithm change |

Commands:

```powershell
uv run pytest tests/unit src/pbl4/management_backend/tests/test_runtime_gateway.py src/pbl4/management_backend/tests/test_runtime_gateway_restart.py --ignore=tests/unit/test_redis_events.py --ignore=tests/unit/test_cli_pblctl.py -k 'not test_resume_rejects_nested_dataset_mismatch_before_allocation' -q --tb=short
uv run pytest tests/integration tests/test_coordinator.py tests/test_worker_training.py --ignore=tests/integration/test_event_batch_ingestion.py -q --tb=short
uv run pytest tests/integration/test_managed_training_completion.py -q --tb=short
uv run python scripts/check_architecture.py
```

## Limits and existing failures

The environment lacks the optional `redis` package, so Redis unit/event-ingestion
suites were excluded. Integration tests requiring unavailable PostgreSQL/services
skip through their existing guards; full Backend/PostgreSQL/WSS process acceptance
was not executed. The managed-process test uses real DTP/HTTP and Worker processes,
Backend command construction and the real Agent stop handler, with a mock WebSocket.
Stop-intent persistence/retry tests mock repository boundaries.

An initial broad run had 536 passing tests and 12 failures unrelated to this change:
11 in the pre-existing untracked `tests/unit/test_cli_pblctl.py` (missing
`pblctl.build_parser`) and one in `test_local_smoke_contracts.py` (checkpoint fixture
missing `artifact_retired`). These files and their production implementation were
left unchanged.

Ruff passes for touched implementation/test/launcher files with SIM102/SIM105
excluded. Without those exclusions it reports two existing findings in
ParameterServer disconnect handling and AllocationService gateway lookup; both
were reproduced against HEAD. `git diff --check` passes.

Manual-Worker network tests and the direct-process DBS harness were removed.
Use `scripts/e2e_agents.py` for full-cluster acceptance, including workload-recovery;
`scripts/e2e_local.py` now redirects to that CLI.
