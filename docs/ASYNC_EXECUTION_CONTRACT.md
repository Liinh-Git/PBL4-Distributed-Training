# Async execution contract

Implementation of the user-approved Sync + Async + Rejoin plan (2026-11-04).
This extension leaves StrictBSP contracts, hashes, framing and checkpoint V1 intact.
Owners remain those recorded in SOURCE_REGISTRY; no new process or lifecycle enum.

## Resolved configuration

`synchronization.training_strategy` selects `strict_bsp` or `async_sgd` once per Job.
Async uses an `async_training` group: `units_per_contribution=1` (1..4096),
`staleness_threshold=6` (0..1000000), `reconnect_grace_seconds=60` (1..3600),
`assignment_timeout_seconds=1800` (1..86400). Integers are strict (no bool/float).
Sync rejects this group. Async rejects DBS and work_units_per_step overrides;
the legacy workload group retains its meaning and is unused by async dispatch.
Expected_workers is the startup gate and rank capacity; running async needs one
execution-ready Worker. Startup retains the current bounded readiness waits.

## Dispatch and update

One assignment per active session, identified by Attempt and Runtime-issued unique
operation_id; source model version is the exact immutable snapshot delivered with it.
Each assignment belongs to one epoch and may contain fewer units at its tail.
Epoch rollover does not wait for outstanding assignments in previous epochs.
Physical units and sample ordering retain the existing deterministic hash order.
Gradient means across local units remain sample weighted.

Under the Coordinator decision lock: verify session/assignment/source version,
deduplicate, compute tau=current-base, apply with eta/max(1,tau) if tau<=R or
drop otherwise, then record the outcome and progress. Future versions and malformed
gradients are errors, never stale drops. Applied and dropped both count as processed;
dropped gradients do not change weights/model_version. Reclaim uses the same lock.
No socket, management or filesystem I/O is executed under this lock.

Async errors fail the offending session and reclaim unprocessed work; an internal
failure after canonical publication fails the Attempt rather than replaying the work.
Assignment timeout fences the session even if its heartbeat still arrives.
Terminal state closes admission; late results, ACKs and reconnects cannot revive it.

## DTP/1 extension

Fixed 48-byte header and existing opcodes remain unchanged. Worker advertises
`async_sgd`; Runtime rejects unsupported capabilities before registration.
HELLO_ACK optionally reports `model_initialized` for async bootstrap/rejoin.
PARAMETER_META retains `transfer_purpose=model_update` and `model_version_out`.
An async scheduling response additionally has `training_strategy=async_sgd`,
`epoch`, `work_units` (0..4096 WorkUnitRef objects) and optional `gradient_result`
containing operation_id, applied, staleness. Empty units mean wait for server dispatch.
`source_step_id` is required only for sync; async uses the header operation_id.
The new assignment is bound to that operation and snapshot version. A result's
operation_id refers to the preceding completed assignment and is distinct.

PARAMETER_APPLIED stays Worker -> Runtime, apply_ok=true, after complete model load;
async omits source_step_id. It gates only that Worker's next compute, not other Workers.
Runtime validates the exact offered operation/version/session even for idle responses.
Initial parameter broadcast has no assignment; Worker sends READY. Runtime then sends
assignments individually without a global STEP_START. Idle Workers are awakened on reclaim.
Snapshot bytes and advertised version always belong to the same immutable revision.

## Rejoin credentials and failure

Initial managed admission still verifies signature, scope and expiry before register.
Only async may reuse an already-admitted allocation: Runtime remembers a SHA-256
digest of its exact admission token and client_instance_id, node_id and assigned rank.
Possession of the same token with all bindings matching permits reconnect after its
initial-admission expiry, solely to this still-running Runtime/Attempt. It never admits
a new allocation with an expired token. No token refresh or Backend round trip.
This record is execution state, is not checkpointed, and disappears with the Attempt.
An active session must close or be fenced by timeout before the slot is reused;
repeated HELLO cannot evict a live session. Lost HELLO_ACK retries the same identity.
Unmanaged reconnect similarly binds the original client_instance_id to its rank;
it remains the existing trusted local development mode, not managed authentication.

Worker keeps its process/cache, discards old-session pending computation and tensors,
repeats verified provisioning/manifest/model readiness, and loads the current snapshot.
Compute/model operations have one owner; an old task cannot send using a new client.
The connection supervisor interrupts stalled frame writes using the negotiated
heartbeat timeout, without waiting on the sender/model lock. HELLO waits are bounded.
Connection retries use bounded exponential backoff, ending on terminal/fatal outcome
or reconnect budget expiry. Grace uses monotonic time and is cancelled only by READY.
Process replacement/initializer promotion remain outside this milestone.

## Recovery

Async checkpoints use schema_version=2; sync remains byte-compatible V1. V2 reuses
the existing model metadata/files and adds async_progress with deterministic catalog
hash, issued position, outstanding occurrence indices and applied/dropped unit/sample
counters. The outstanding set includes both assigned and reclaimed unprocessed work;
no session, credential, socket or uncommitted gradient is persisted.
This bounds progress storage by outstanding work, not by every completed unit.
Recovery validates catalog/seed/epochs, indices, counters and sample totals.
New Attempt restores the model and progress together; all outstanding work is pending.
Later work beyond the checkpoint may run again after crash, as normal checkpoint rollback.
No cross-strategy restore or silent fresh fallback.

CheckpointPolicy retains periodic/manual/final cadence. Async checks crossing periodic
boundaries in the contiguous completed-epoch frontier, including jumps over boundaries.
Progress counters identify a recovery revision even when every result was dropped.
Capture under the decision lock, write outside it, publish in order; terminal state
wins late completion. Existing warning behavior on periodic/final write failure stays.
Management events/snapshots expose processed/applied/dropped units and samples, frontier,
version, staleness and active sessions without creating fake global Steps.

## Epoch telemetry and terminal display

Complete the approved occurrence-based epoch metrics from the Sync + Async review plan.
Async reuses Sync's sample-weighted loss/accuracy helpers and the unchanged
`epoch.metrics.finalized` payload (`epoch_index`, `sample_count`, `training_loss`,
`training_accuracy`). Every processed contribution, applied or stale-dropped, counts
once toward its assignment's original epoch. Finalization occurs when that epoch's
occurrences are complete, even if an older epoch still has pending work; it never
blocks dispatch or introduces a barrier. Completed accumulator storage is released.

`strategy_state.epoch_progress` is optional observational metadata for the oldest
incomplete epoch: the same metric fields plus `processed_units` and `target_units`.
Loss/accuracy here are provisional; the final event freezes their full-epoch values.
The terminal follows the Sync Training Output layout, and epoch charts use the
existing independently paged PostgreSQL event history rather than the recent-event
window. Older Runtime versions remain readable and show unavailable epoch detail.

No checkpoint shape changes: restored work counters can reconstruct sample coverage,
but historical measurement sums are not restored. An epoch partly processed before
the source checkpoint has unavailable loss/accuracy in the resumed Attempt, rather
than reporting a partial average as a full-epoch measurement. Later epochs measured
entirely in the new Attempt have normal metrics; prior Attempt events remain history.
