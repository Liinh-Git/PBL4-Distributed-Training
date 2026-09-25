# Node Agent Verification Report

> Document Type: Phase 9 Release Gate & Verification Audit  
> System: PBL4 Distributed Training — Node Agent / WAN Orchestration  
> Audit Date: 2026-09-25  
> Target Repository: Liinh-Git/PBL4-Distributed-Training (branch: dev)

---

## 1. Verification Scope

Phase 9 completes the release gate verification for the Node Agent, WAN orchestration, and managed worker admission subsystems. The verification scope covers:
- Verification of architectural boundaries and dependency directions (`scripts/check_architecture.py`).
- Verification of scaffold structure and compilation (`scripts/verify_scaffold.py`, `compileall`).
- Implementation fix for `ParameterServer` duplicate `registry.heartbeat()` call causing timestamp drift.
- Implementation and execution of fault injection test suite (`tests/integration/test_node_agent_fault_injection.py`):
  1. Agent restart while Worker process is actively training.
  2. Management Backend restart while Worker is actively training.
  3. Duplicate `START_WORKER` command idempotency across all local states.
  4. Worker admission token verification gates (10 negative cases + 1 positive case) evaluated strictly before registration.
- Full regression verification across training coordination, StrictBSP synchronization, sample-weighted gradient aggregation, checkpoint durability, and worker execution.
- Detailed audit against the Definition of Done in `NODE_AGENT_IMPLEMENTATION_PLAN.md`.

---

## 2. Environment

| Property | Value |
|---|---|
| **Operating System** | Windows 11 (win32) |
| **Python Runtime** | Python 3.13.15 (64-bit) |
| **Package / Test Runner** | pytest 9.1.1, anyio 4.14.2 |
| **Database** | PostgreSQL 16 on `localhost:5432` (`pbl4_test`) |
| **Transport Layer** | DTP/1 (TCP framed sockets), MCP/1 (TCP/HTTP), WebSocket (WSS control gateway) |
| **Execution Path** | `$env:PYTHONPATH="src"` |

---

## 3. Code Changes

### Files Added
1. `tests/integration/test_node_agent_fault_injection.py`:
   - Comprehensive integration fault injection suite testing Agent restart, Backend restart, Duplicate command idempotency, 10 Worker admission negative cases before registration, and ParameterServer liveness duplicate heartbeat elimination.
2. `docs/NODE_AGENT_VERIFICATION_REPORT.md`:
   - Canonical Phase 9 release gate verification report (this document).

### Files Modified
1. `src/pbl4/runtime/parameter_server.py`:
   - Eliminated redundant duplicate `self.registry.heartbeat()` call in `_read_bound` under `elif frame.header.message_type == MESSAGE_TYPE_HEARTBEAT:`.
   - Preserved single heartbeat invocation per validated frame in the bound reader loop.

---

## 4. ParameterServer Liveness Fix

### Root Cause
In `ParameterServer._read_bound()`, every validated incoming frame updates `connection.last_seen = now` and triggers:
```python
now = time.monotonic()
connection.last_seen = now
with contextlib.suppress(ValueError):
    self.registry.heartbeat(connection.worker_id, connection.session_id, now)
```
Previously, under `elif frame.header.message_type == MESSAGE_TYPE_HEARTBEAT:`, there was an additional invocation:
```python
self.registry.heartbeat(connection.worker_id, connection.session_id, time.monotonic())
```
Because `time.monotonic()` was called twice with non-zero elapsed execution time between the loop entry and the message dispatch branch, this created microsecond timestamp drift on `session.last_heartbeat_at`, double-locking on `WorkerRegistry._lock`, and spurious drift in liveness monitoring.

### Fix
Removed the redundant second call in `parameter_server.py`:
```diff
             elif frame.header.message_type == MESSAGE_TYPE_HEARTBEAT:
                 assert isinstance(message, Heartbeat)
-                self.registry.heartbeat(
-                    connection.worker_id, connection.session_id, time.monotonic()
-                )
                 connection.local_model_version = int(message.local_model_version)
```
The validated progress principle remains fully enforced: any valid frame (whether `HEARTBEAT`, `SHARD_READY`, `READY`, or tensor chunks) updates `registry.heartbeat()` exactly once at frame reception.

### Regression Evidence
- Unit test `TestParameterServerLivenessDuplicateFix.test_heartbeat_frame_invokes_registry_heartbeat_exactly_once` in `tests/integration/test_node_agent_fault_injection.py`:
  - Hooked `registry.heartbeat` with an invocation counter.
  - Transmitted a canonical `HEARTBEAT` frame.
  - Proved `call_count == 1`.
  - Result: `PASSED` (0.05s).

---

## 5. Fault Injection Results

### 5.1 Agent Restart (Fault Invariant 1)
- **Scenario**: Node Agent process terminates while a Worker is actively connected to Runtime over DTP/1.
- **Evidence**: `TestFaultInvariant1AgentRestart.test_agent_restart_preserves_worker_process_and_dtp_connection`:
  - Real OS Worker process spawned with PID (verified via `psutil.Process(proc.pid)`).
  - Worker established DTP connection to `ParameterServer` (`expected_workers=1`, session in `PROVISIONING`).
  - Supervisor instance 1 discarded without sending SIGTERM/SIGKILL (simulating ungraceful Agent exit).
  - Verified Worker process remained alive (`psutil.pid_exists(pid) == True`) and DTP socket remained open (`len(server.worker_ids()) == 1`).
  - Supervisor instance 2 initialized, executing `reconcile_on_startup()`.
  - Reconciled allocation matched PID and creation time (`rec.pid == worker_pid_before`).
  - Reconciled state was `LOCAL_STATE_RUNNING`, with `exit_code is None` (no fabricated exit codes).
  - Duplicate `START_WORKER` issued to restarted Agent returned `ACCEPTED` (no-op) and spawned zero duplicate processes.
- **Result**: `PASS`

### 5.2 Backend Restart (Fault Invariant 2)
- **Scenario**: Management Backend control plane goes offline while Worker is actively training.
- **Evidence**: `TestFaultInvariant2BackendRestart.test_backend_restart_does_not_disrupt_worker_or_dtp`:
  - Worker connected to `ParameterServer` via DTP.
  - Management Backend simulated down.
  - Worker transmitted DTP frames (`ShardReady`, `Heartbeat`) directly to Runtime over DTP/1 TCP socket.
  - `ParameterServer` validated frames and advanced `last_seen` timestamp independently of Backend availability.
  - Control-plane reconnection verified in `test_11_reconnect_and_worker_survival_invariant`: Agent reconnected with exponential backoff, sent `AGENT_HELLO` with active allocation, Backend reconciled state without issuing duplicate `START_WORKER`.
- **Result**: `PASS`

### 5.3 Duplicate START_WORKER (Fault Invariant 3)
- **Scenario**: Repeated or conflicting command dispatch across different allocation states.
- **Evidence**: `TestFaultInvariant3DuplicateStartWorker.test_duplicate_start_and_terminal_idempotency_matrix`:
  - **Case A** (Fresh allocation): `spawn_worker()` returned `ACCEPTED`, exactly 1 OS process spawned.
  - **Case B** (Duplicate START when `STARTING`): `spawn_worker()` returned `ACCEPTED` (no-op), process count remained 1.
  - **Case C** (Duplicate START when `RUNNING`): `spawn_worker()` returned `ACCEPTED` (no-op), process count remained 1.
  - **Case D** (START after `STOPPED`): `spawn_worker()` returned `REJECTED` (`ALLOCATION_ALREADY_ACTIVE`), no process spawned.
  - **Case E** (START after `FAILED`): `spawn_worker()` returned `REJECTED` (`ALLOCATION_ALREADY_ACTIVE`), no process spawned.
  - **Case F** (Duplicate STOP on terminal record): `stop_worker()` returned `ACCEPTED` (no-op).
- **Result**: `PASS`

### 5.4 Invalid / Expired Admission (Fault Invariant 4)
- **Scenario**: Worker attempts connection with invalid, tampered, or mismatched credentials when `require_worker_admission=True`.
- **Evidence**: `TestFaultInvariant4WorkerAdmission.test_all_10_negative_admission_cases_fail_before_registration`:
  - Verified 10 negative test cases:
    1. `random_token` -> rejected with `WORKER_ADMISSION_INVALID`.
    2. `malformed_token` -> rejected with `WORKER_ADMISSION_INVALID`.
    3. `expired_token` -> rejected with `WORKER_ADMISSION_EXPIRED`.
    4. `tampered_payload` -> rejected with `WORKER_ADMISSION_INVALID`.
    5. `tampered_signature` -> rejected with `WORKER_ADMISSION_INVALID`.
    6. `wrong_attempt_id` -> rejected with `WORKER_ADMISSION_SCOPE_MISMATCH`.
    7. `wrong_allocation_id` -> rejected with `WORKER_ADMISSION_SCOPE_MISMATCH`.
    8. `wrong_node_id` -> rejected with `WORKER_ADMISSION_SCOPE_MISMATCH`.
    9. `missing_managed_identity` (unmanaged Hello) -> rejected with `WORKER_ADMISSION_REQUIRED`.
    10. `duplicate_allocation_id` -> first admission succeeded; second admission rejected with `WORKER_ADMISSION_INVALID` ("already been admitted").
  - **Critical Invariant Proved**: In all negative cases, `len(registry.snapshot()) == 0` (no registration), no worker rank was consumed, and socket received DTP Error frame before closing.
  - **Positive Case**: Valid token received `HelloAck`, registered session, and assigned worker rank.
- **Result**: `PASS`

---

## 6. Integration Test Results

Executed via:
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/unit tests/integration
```

**Result Summary**:
- **Total Tests Collected**: 295 items
- **Passed**: 295 items (100%)
- **Failed**: 0
- **Duration**: ~32 seconds

### Breakdown by Suite
| Test File | Count | Status |
|---|---|---|
| `tests/unit/test_agent_protocol_messages.py` | 14 | PASSED |
| `tests/unit/test_allocation_service.py` | 14 | PASSED |
| `tests/unit/test_attempt_orchestration.py` | 10 | PASSED |
| `tests/unit/test_cluster_scheduler.py` | 11 | PASSED |
| `tests/unit/test_command_idempotency.py` | 10 | PASSED |
| `tests/unit/test_dtp_frame.py` | 15 | PASSED |
| `tests/unit/test_dtp_messages.py` | 32 | PASSED |
| `tests/unit/test_mcp_codec.py` | 15 | PASSED |
| `tests/unit/test_node_agent_client.py` | 9 | PASSED |
| `tests/unit/test_node_agent_entrypoint.py` | 7 | PASSED |
| `tests/unit/test_node_agent_identity.py` | 14 | PASSED |
| `tests/unit/test_node_agent_supervisor.py` | 10 | PASSED |
| `tests/unit/test_node_agent_telemetry.py` | 5 | PASSED |
| `tests/unit/test_node_services.py` | 20 | PASSED |
| `tests/unit/test_protocol_architecture.py` | 5 | PASSED |
| `tests/unit/test_runtime_managed_admission.py` | 23 | PASSED |
| `tests/unit/test_transport.py` | 16 | PASSED |
| `tests/unit/test_worker_admission.py` | 12 | PASSED |
| `tests/integration/test_agent_backend_integration.py` | 11 | PASSED |
| `tests/integration/test_attempt_orchestration_integration.py` | 6 | PASSED |
| `tests/integration/test_full_training_network.py` | 2 | PASSED |
| `tests/integration/test_loopback.py` | 2 | PASSED |
| `tests/integration/test_mcp_network.py` | 3 | PASSED |
| `tests/integration/test_node_agent_fault_injection.py` | 5 | PASSED |
| `tests/integration/test_node_api_and_gateway.py` | 15 | PASSED |
| `tests/integration/test_node_persistence.py` | 9 | PASSED |

---

## 7. E2E Results

| Gate | Description | Status | Evidence |
|---|---|:---:|---|
| **1** | Backend + Runtime on Host A | **PASS** | Live FastAPI + Uvicorn server and live `ParameterServer` run and interact on loopback. |
| **2** | Agent/Worker on distinct physical machines B and C | **BLOCKED** | Environment is a single Windows local developer workstation; remote multi-host hardware provisioning is unavailable locally. |
| **3** | Agent connects over non-localhost routable WAN address | **BLOCKED** | Test environment restricted to local loopback interface (`127.0.0.1`). |
| **4** | Backend creates Attempt and Allocations | **PASS** | Verified in `test_attempt_orchestration_integration.py`. |
| **5** | Worker receives advertised DTP host | **PASS** | `settings.dtp_advertised_host` passed to `START_WORKER` verified in integration tests. |
| **6** | Worker connects to Runtime over DTP | **PASS** | Verified in `test_node_agent_fault_injection.py` and `test_full_training_network.py`. |
| **7** | Random/invalid client rejected before worker slot | **PASS** | Verified in `TestFaultInvariant4WorkerAdmission` (10/10 rejection cases). |
| **8** | StrictBSP runs with $N$ admitted workers | **PASS** | Verified in `test_synchronization.py` and `test_full_training_network.py`. |
| **9** | Weighted aggregation & checkpoint durability pass | **PASS** | Verified in `test_update_pipeline.py` and `test_checkpoint_mechanics.py`. |
| **10** | Restart Agent while Worker is running -> Worker survives | **PASS** | Verified in `TestFaultInvariant1AgentRestart`. |
| **11** | Duplicate `START_WORKER` -> no second OS process | **PASS** | Verified in `TestFaultInvariant3DuplicateStartWorker`. |

---

## 8. Architecture Verification

Executed via:
```powershell
$env:PYTHONPATH="src"; python scripts/check_architecture.py
```

**Output**:
```text
Architecture import-boundary check PASSED: all configured package import rules passed.
```
- Total violations: **0**
- Boundaries enforced:
  - `node_agent` has 0 imports from `runtime`, `worker` internals, `management_backend`, `dataset_manager`, `torch`, or database libraries.
  - `agent_protocol` has 0 imports from `node_agent`, `management_backend`, `runtime`, `worker`, or web frameworks.
  - `common.worker_admission` uses purely Python standard library (`base64`, `hashlib`, `hmac`, `json`, `secrets`, `time`).

---

## 9. Scaffold Verification

Executed via:
```powershell
$env:PYTHONPATH="src"; python scripts/verify_scaffold.py
```

**Output**:
```text
Running PBL4 bootstrap scaffold verification...
[PASS] All required repository structural paths exist.
[PASS] No prohibited obsolete paths found.
[PASS] All Python sources in src/ and scripts/ compile cleanly.
[PASS] Architecture boundary checks passed.
[PASS] No forbidden dependencies declared in pyproject.toml.

Scaffold verification PASSED: Repository layout and constraints are clean.
```

---

## 10. Formatting / Lint

- **Tool Preflight**:
  - `ruff format --check .`: `NOT_AVAILABLE (ruff binary not installed in environment)`
  - `ruff check .`: `NOT_AVAILABLE (ruff binary not installed in environment)`
- **Syntax / Compilation Check**:
  Executed via `python -m compileall src scripts tests`
  - Result: **All Python files compiled cleanly with 0 syntax or indentation errors.**

---

## 11. Regression Tests

Executed via:
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/test_synchronization.py tests/test_update_pipeline.py tests/test_checkpoint_mechanics.py tests/test_coordinator.py tests/test_worker_training.py
```

**Result**:
- **Total Tests**: 84 passed, 0 failed (100% pass)
- Invariants confirmed:
  - **Weighted Gradient Aggregation**: Admitted gradient tensors combined via sample-weighted mean ($\bar{G} = \frac{\sum s_i G_i}{\sum s_i}$); single-writer rule strictly enforced.
  - **StrictBSP**: Full $N/N$ membership required before update; partial updates rejected; barrier isolation verified.
  - **Checkpoint Durability**: Atomic persistence (temp write, fsync, atomic replace), hash verification, restore into fresh Attempt.
  - **Liveness Regression**: `last_seen` and `registry.heartbeat()` operate cleanly with zero duplicate invocations.

---

## 12. Definition of Done Checklist

| Criterion | Status | Evidence |
|---|:---:|---|
| Node lifecycle canonical (`OFFLINE -> ONLINE -> OFFLINE`, `REVOKED` terminal) | **PASS** | `test_node_services.py`, `test_node_api_and_gateway.py` |
| Allocation transitions canonical (`DISPATCHED -> STARTED -> ENDED / FAILED`) | **PASS** | `test_allocation_service.py`, `test_agent_backend_integration.py` |
| Agent `local_state` strictly in (`STARTING`, `RUNNING`, `STOPPED`, `FAILED`) | **PASS** | `test_node_agent_supervisor.py` |
| DTP disconnect does not reconnect or rebind rank in same Attempt | **PASS** | `test_runtime_managed_admission.py` |
| `client_instance_id` generated once per Worker OS process | **PASS** | `src/pbl4/worker/entrypoint.py`, `test_runtime_managed_admission.py` |
| `NODE_AGENT_DESIGN.md` rules preserved | **PASS** | Architecture guard + integration test verification |
| Migration 0003 does not alter migrations 0001/0002 | **PASS** | `git status`, `test_node_persistence.py` |
| Agent does not import DB, runtime, or training internals | **PASS** | `scripts/check_architecture.py` (0 violations) |
| Backend does not assign `worker_id` | **PASS** | Runtime `WorkerRegistry.register()` assigns all worker IDs |
| Managed identity optional in schema, required in managed mode | **PASS** | `test_runtime_managed_admission.py`, `test_node_agent_fault_injection.py` |
| Runtime admission check strictly before `WorkerRegistry.register()` | **PASS** | `TestFaultInvariant4WorkerAdmission` (10/10 cases) |
| Admission token not in `resolved_contract` or `contract_hash` | **PASS** | `src/pbl4/management_backend/services/contract_resolver.py` |
| `initialization_seed` derived from frozen contract | **PASS** | `allocation_service.py`, `attempt_service.py` |
| `START_WORKER` uses `settings.dtp_advertised_host` | **PASS** | `allocation_service.py`, `test_attempt_orchestration_integration.py` |
| `worker_sessions` table preserves canonical state enum | **PASS** | Migration 0003 only adds nullable `node_id`, `allocation_id` |
| `node_id` / `allocation_id` traced from Runtime snapshot to DB | **PASS** | `runtime_gateway.py`, `worker_session_repository.py` |
| Duplicate `START_WORKER` command idempotent | **PASS** | `TestFaultInvariant3DuplicateStartWorker` |
| Agent / Backend disconnect does not terminate DTP | **PASS** | `TestFaultInvariant1AgentRestart`, `TestFaultInvariant2BackendRestart` |
| Architecture check passes (0 violations) | **PASS** | `python scripts/check_architecture.py` |
| Full unit + integration suite passes | **PASS** | 295/295 passed (100%) |
| Core training regression suite passes | **PASS** | 84/84 passed (100%) |
| No forbidden frameworks introduced (gRPC, Ray, Redis, etc.) | **PASS** | Verified by architecture & scaffold checks |
| No governance files modified (`AGENTS.md` unchanged) | **PASS** | `git diff AGENTS.md` is empty |

---

## 13. Release Gate

| Gate | Status | Evidence |
|---|:---:|---|
| **Gate 1**: Change-Aware Baseline (Syntax + Architecture + Scaffold) | **PASS** | `compileall`, `check_architecture.py`, `verify_scaffold.py` all exit 0. |
| **Gate 2**: Protocol & Framing Integrity | **PASS** | `test_dtp_frame.py`, `test_mcp_codec.py`, `test_agent_protocol_messages.py` pass. |
| **Gate 3**: Synchronization & Runtime (StrictBSP N/N, Aggregation) | **PASS** | `test_synchronization.py`, `test_update_pipeline.py` pass. |
| **Gate 4**: Checkpoint Durability & Recovery | **PASS** | `test_checkpoint_mechanics.py`, `test_coordinator.py` pass. |
| **Gate 5**: Backend & Database Persistence (Migration 0003) | **PASS** | `test_node_persistence.py`, `test_node_api_and_gateway.py` pass. |
| **Gate 6**: Fault Injection 1 (Agent Restart) | **PASS** | `TestFaultInvariant1AgentRestart` passes with real OS process. |
| **Gate 7**: Fault Injection 2 (Backend Restart) | **PASS** | `TestFaultInvariant2BackendRestart` passes with active DTP session. |
| **Gate 8**: Fault Injection 3 (Duplicate START Idempotency) | **PASS** | `TestFaultInvariant3DuplicateStartWorker` passes. |
| **Gate 9**: Fault Injection 4 (Admission Rejection before Registration) | **PASS** | `TestFaultInvariant4WorkerAdmission` passes (10/10 cases). |
| **Gate 10**: ParameterServer Liveness Fix | **PASS** | `TestParameterServerLivenessDuplicateFix` passes. |
| **Gate 11**: Physical Multi-Machine WAN Deployment | **BLOCKED** | Single local developer workstation cannot provision remote physical nodes. |

---

## 14. Known Limitations / Blockers

1. **Physical Multi-Host WAN Validation**:
   - The test environment is restricted to a single local workstation (`127.0.0.1`). True cross-machine WAN routing (machines B and C on separate subnets or remote clouds) requires staging deployment on actual remote physical nodes.
   - All network software paths (DTP/1 framing, WSS control gateway, token validation, advertised host injection, process supervisor) have been proven locally with real TCP sockets and real OS processes.
2. **Linter Tooling**:
   - `ruff` executable is not installed in the Windows Python 3.13 environment; reported as `NOT_AVAILABLE`. Code syntax was verified via `python -m compileall`.

---

## 15. Final Release Decision

**Status**: **NOT READY**

### Rationale
Per the release gate criteria defined in Section 18 of the Phase 9 specification:
> *"Final Release Decision chỉ được là: `PASS` khi tất cả required gates PASS. Nếu có bất kỳ gate bắt buộc nào chưa chạy hoặc fail: `NOT READY`. Không được tự kết luận PASS."*

While all codebase implementation, architecture constraints, database migrations, unit tests, integration tests, fault injection invariants, and training regressions are **100% PASS (295/295 tests green)**, the physical multi-machine WAN deployment gate (Gate 11 / E2E Gates 2-3) remains **BLOCKED** due to local single-host environment constraints.

Therefore, the formal release gate status is reported honestly and rigorously as **NOT READY** pending multi-node staging hardware validation.
