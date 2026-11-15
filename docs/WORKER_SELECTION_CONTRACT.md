# Worker selection and independent dataset shards

User-approved implementation scope, 2026-11-14. The user approved the proposal
and requested implementation while the canonical Drive sources were inaccessible.
This records that decision; it does not claim the Drive documents were updated.
Canonical owner synchronization remains pending for DOMAIN_MODEL, NODE_AGENT,
DATA_MODEL, DBS_WORKLOAD, BACKEND_API and the DTP assignment/readiness semantics.

## First start and frozen Jobs

One Node runs one Worker. First-start automatic placement randomly selects up to
three ONLINE Nodes without an active allocation. Manual placement selects exactly
the supplied one to five distinct Nodes. An empty list is invalid; absent/null
`node_ids` means automatic. Offline, missing or busy manual Nodes are rejected
without substitutions. Zero available Nodes cannot create an attempt.

The first start locks the Job and candidate Nodes, resolves N from actual selected
placements, then freezes the contract and creates the attempt, allocations and
command in one transaction. A pre-dispatch failure rolls back the freeze. Existing
allocation and active-attempt uniqueness constraints remain the final race guards.
Command dispatch stays outside this transaction. Persisted allocations preserve
the random result across request replays; terminal idempotent attempts are never
re-created under the same key.

N stays fixed for the Job. Start, retry and resume require exactly that N, allowing
different physical Nodes. Jobs frozen with four or five Workers require manual
selection on every attempt; automatic placement never exceeds three. Insufficient
capacity fails instead of reducing N. Clone the Job to choose a different N.
Existing READY Jobs and checkpoint hashes are not rewritten or migrated.

## Workload resolution

For StrictBSP equal, effective K is `max(requested K, N)`, defaulting to N when K
is omitted. DBS still requires K and resolves `max(requested K, N + 1)`. Requested
values are preserved; the resolved contract records effective K and is hashed
after adjustment. The verified root manifest snapshot must describe enough full
physical batches for at least one complete step. Missing metadata or insufficient
Work Units fails closed before dispatch. Async retains its independent
units-per-contribution settings; the BSP K rule does not apply to async work.

Validation can preview the current selection and adjusted K without reserving
Nodes or freezing a Job. If automatic placement has no capacity, independent
contract errors are still checked, `resolved_preview` is null and a warning explains
that N is unresolved. Start rechecks capacity, so its authoritative N/K may differ
from a preview. Retry/resume never change frozen K or contract hash.

## Dataset provisioning and DTP/1

Shard count S comes from the READY Dataset Build and pinned manifest, independently
of N. Existing dataset artifacts, hashes and partition defaults are unchanged.
Runtime bootstraps Worker w with `sorted(shard_ids)[w % S]`, sends S as
`expected_shard_count`, and uses existing `cache_scope=all_shards`. Each Worker
downloads and verifies all shards before sending SHARD_READY. Runtime verifies
that acknowledgement against the pinned build, root hash, assigned bootstrap
shard, shard hash, batch count and sample count for the session.
Assignments are emitted once per TCP session after HELLO_ACK; concurrent
registration and provisioning cannot send duplicate assignments or overtake the
registration acknowledgement. Rejoining async sessions receive their pinned
assignment again on the new connection.

Bootstrap shard IDs may repeat between Workers; they do not determine training
ownership. Global Work Unit assignments determine which `(shard_id, batch_id)`
each Worker computes. Each BSP Worker sends one logical sample-weighted
contribution per step. N/N admission and parameter ACK gates, checkpoint gates,
Worker-0 TCP behavior, and DBS recovery warm-up are unchanged. The legacy
assigned-shard Worker path retains its S=N check.

There are no new DTP fields, opcodes, header layouts or versions. Deploy Runtime
and Worker together while no attempt is active, then Backend/WebUI; mixed old/new
Workers are not supported for N different from S. Per Node disk cache is the full
dataset; total cache and first-download traffic can scale approximately with N.

## REST and WebUI

- `POST /jobs/{id}/start`: existing `node_ids`, one to five when supplied.
- `POST /jobs/{id}/validate`: optional body containing `node_ids`; response keeps
  existing requested contract, nullable resolved preview, warnings and errors.
- `POST /jobs/{id}/retry`: optional body containing `node_ids`.
- `POST /jobs/{id}/resume`: `checkpoint_id` plus optional `node_ids`.
- Paths above are relative to `/api/v1`. Execution endpoints retain mandatory
  Idempotency-Key; selected IDs are included in the canonical request hash.
- Node list items expose a derived `has_active_allocation` boolean; no database
  field or migration is added.

The launch wizard and Job detail expose automatic/manual selection. Job detail
retries Jobs with existing attempts. Resume has its own Node selector. Manual empty
selection never silently becomes automatic. UI shows shard count separately from
N and K, explains adjustments, and displays frozen N plus clone guidance.

## Verification and rollout

Tests cover random selection boundaries, exact manual membership, request schemas,
preview, effective K, metadata validation, PostgreSQL rollback/concurrent starts,
five-Worker retry/resume, and idempotent replay. Production Runtime/Worker tests use
real TCP/HTTP with N=1..5 against three shards for equal and DBS. A numerical oracle
checks one to five contributions against the same global six-Work-Unit SGD update.
Async network/rejoin/resume regressions include N=1,2,5 against the same dataset.

Before rollout, inspect the selected allocation IDs, effective N/K and provisioning
state; never log admission credentials. Run one automatic launch and one manual
five-Worker launch in the target environment after coordinated deployment.
