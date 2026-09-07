---
name: release-gate
description: >
  Change-aware verification gates and preflight checklists before tagging releases,
  merging major milestones, or completing cross-cutting tasks.
---

# Release Gate

## 1. When to Activate

Use this skill as **PHASE 5 OF THE STANDARD PIPELINE** before:
- Completing any multi-module or cross-cutting feature task
- Opening PRs or merging architectural changes
- Tagging a repository milestone or release

---

## 2. Canonical Source References

Consult the canonical technical documents registered in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):
- `[TESTING]`: Canonical test taxonomy (unit, integration, distributed, failure, architecture, benchmark)
- `[CODE_STRUCTURE]`: Package layouts and boundary constraints

---

## 3. Preflight Execution Protocol

> [!IMPORTANT]
> **Preflight Verification**: Always check whether a script or test harness exists on disk before attempting to execute it.
> - If the script **EXISTS**: Execute it and report the exit code and output.
> - If the script is **MISSING**: Report `NOT_AVAILABLE (script path missing)`.
> - **DO NOT** fake a `PASS` status.
> - **DO NOT** invent ad-hoc production test runners outside the assigned task scope just to satisfy a gate.

---

## 4. Change-Aware Verification Gates

Execute the gates corresponding to the change classification:

### Gate 1: Change-Aware Baseline
For production-code changes, use the existing environment without dependency sync/install. For governance/documentation-only tasks, inspect diff, source immutability, Markdown links, discovery, provenance and routing; run existing architecture/scaffold/lint checks as relevant. Syntax checks must avoid writing artifacts into production directories (redirect bytecode cache to a temporary directory). Missing tools are NOT_AVAILABLE; unrelated suites are SKIPPED with reason.

```bash
# 1. Code Style & Formatting
uv run ruff format --check src scripts
uv run ruff check src scripts

# 2. Syntax Compilation
uv run python -m compileall src scripts

# 3. Architecture & Scaffold Boundary Checks (Preflight checked)
uv run python scripts/check_architecture.py
uv run python scripts/verify_scaffold.py
```

### Gate 2: Protocol Changes (`protocol`, `transport`, `management_protocol`)
When wire definitions or transport primitives are altered:
- [ ] **Exact-Byte Golden Vectors**: Encode/decode tests match canonical byte sequences.
- [ ] **Framing Robustness**: Malformed magic, invalid length, and corrupted payload tests pass.
- [ ] **Boundary Integrity**: `recv_exact` tests for fragmentation, coalescing, and partial reads.
- [ ] **Wire Compatibility**: Protocol version negotiation and backward-compatibility verified.

### Gate 3: Synchronization & Runtime Changes (`runtime`, `worker`)
When training coordination or synchronization policies are altered:
- [ ] **Membership Invariant**: No parameter update before full $N/N$ workers contribute (no partial $2/N$ updates).
- [ ] **Rejection Semantics**: Automated tests verify duplicate, stale, future, and invalid worker rejections.
- [ ] **Mathematical Oracle**: Distributed $\theta_{\text{next}}$ matches single-process reference within tolerance.
- [ ] **Worker-0 Uniformity**: Verifies Worker-0 communicates over real DTP/TCP path.
- [ ] **Runtime Failure & Membership Invariants**:
  - Worker death/disconnect during local forward/backward compute
  - Disconnect during gradient transfer (aborted tensor streaming)
  - Disconnect while waiting for parameter broadcast
  - Worker timeout triggers clean failure detection
  - Surviving worker cleanup/shutdown coordination
  - Latest valid durable checkpoint preserved upon attempt failure

### Gate 4: Checkpoint & Resume Changes (`checkpoint`, `recovery`)
When persistence, durability, or recovery paths are altered:
- [ ] **Durable Write & Load**: Checkpoint manifest, model weights, recovery cursor and canonical identities serialize cleanly. Serialize/restore optimizer dynamic state only IF the canonical optimizer has mutable state; V1 plain SGD without momentum has none.
- [ ] **Atomic Persistence**: Verification of temporary write, fsync, and atomic rename/replace (no partially written checkpoints).
- [ ] **Metadata & Hash Verification**: Hash mismatch, corrupt chunk, or payload tampering is strictly rejected.
- [ ] **Contract Compatibility**: Rejects checkpoints with mismatched dataset build, model architecture, or parameter manifests.
- [ ] **Resume into NEW Attempt**: Resuming an execution spawns a new Attempt UUID with preserved weights and cursors (attempts are immutable).
- [ ] **Full State Restoration**:
  - Restores canonical model parameters
  - Restores canonical `model_version`
  - Restores optimizer dynamic state IF present in the canonical optimizer; no invented state for V1 plain SGD without momentum
  - Restores contract/dataset/parameter identities and policy identity/version
  - Restores dataset progress cursor (`epoch`, `next_batch_ordinal` or equivalent)
- [ ] **Uninterrupted Reference Alignment**: Resumed distributed training continues and produces $\theta$ matching uninterrupted execution.
- [ ] **Failure Injection**: Simulated write failure leaves previous durable checkpoint valid and intact.

### Gate 5: Backend & Database Changes (`backend`, `migrations/`)
When DB schemas, repositories, or REST/WebSocket APIs are altered:
- [ ] **Migration Sanity**: Use the repository's canonical numbered migration mechanism/tool/script. Test migration from the previous supported schema; additive/backfill/constraint/destructive behavior; history preservation and compatibility; backup and destructive-change tests; fail-fast on unsupported schema versions. Test downgrade only when the canonical mechanism/project policy supports it.
- [ ] **Repository Isolation**: Repositories operate via transactions using `psycopg`.
- [ ] **API Contract**: FastAPI Pydantic models validate valid requests and return canonical error responses for invalid inputs.

### Gate 6: Dataset Manager Changes (`dataset_manager`)
When dataset ingestion, partitioning, or manifest generation is altered:
- [ ] **Deterministic Partitioning**: Identical canonical inputs produce deterministic logical/artifact results according to the canonical serialization/artifact contract. Require byte-identical results only where canonical serialization/hash rules require exact bytes.
- [ ] **Registration Lifecycle Verification**:
  - Dataset Manager reaches `REGISTERING`
  - Management Backend polls and fetches root manifest
  - Backend verifies manifest hash and schema integrity
  - Backend persists registration/catalog state in PostgreSQL
  - Backend transmits registration ACK to Dataset Manager
  - Dataset Build reaches `READY`
  - Negative/failure cases: invalid manifest hash rejected, registration timeout handled
- [ ] **Provisioning & Readiness Timing**:
  - `SHARD_READY` confirmed before worker training starts
  - Readiness verified before Attempt transitions to `RUNNING`
  - Failure cases: Dataset Manager down before readiness blocks Attempt; Dataset Manager down after all worker shards downloaded does NOT fail training

### Gate 7: WebUI Changes (`web/`)
When frontend views, hooks, or API consumers are altered:
```bash
cd web
npm run typecheck
npm run build
cd ..
```

---

## 5. Git & Repository Hygiene Gate

Verify repository hygiene before PR or release completion:
- [ ] **No Secrets**: Zero `.env`, credentials, private keys, or API tokens tracked.
- [ ] **No Runtime Artifacts**: Zero checkpoints, dataset caches (`.var/`), log files, or downloaded shards committed to Git.
- [ ] **No Build Artifacts**: Zero compiled bytecode (`__pycache__`, `.pyc`), distribution bundles, or frontend `dist/` tracked.
- [ ] **Clean Working Tree**: No untracked scratch files or leftover debug scripts.
- [ ] **`.gitignore` Consistency**: Verified against canonical ignore rules.

---

## 6. Canonical Test Suite Accounting

Canonical test suites are categorized into:
1. `unit`
2. `integration`
3. `distributed`
4. `failure`
5. `architecture`
6. `benchmark`

> [!NOTE]
> Every release gate report must list each canonical suite and explicitly state whether it was **EXECUTED** (with result) or **SKIPPED** (with a documented technical reason, e.g., "Skipped benchmark suite: task scope limited to documentation audit").


## 7. Scoped helper completion

UI work uses pbl4-ui-direction and applicable vendor design/React/audit/browser helpers per SKILL_ROUTING. API implementation may use vendor-fastapi only after semantic resolution. vendor-verification-before-completion checks the fresh evidence from this gate; it never becomes primary or restarts checks on unchanged artifacts. For .agents maintenance, run the existing local skills verifier when present and inspect its limitations alongside the textual scenario audit.
