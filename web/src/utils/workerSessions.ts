import type { WorkerSessionItemData } from '../types/api';

export function applyWorkerDisconnect(
  workers: WorkerSessionItemData[], workerId: unknown, sessionId: unknown, occurredAt: string,
): WorkerSessionItemData[] {
  if (typeof workerId !== 'number' || typeof sessionId !== 'string') return workers;
  return workers.map(worker => worker.worker_id === workerId && worker.session_id === sessionId
    && worker.state !== 'FAILED' && worker.state !== 'DISCONNECTED'
    ? { ...worker, state: 'DISCONNECTED', disconnected_at: occurredAt }
    : worker);
}

export function mergeWorkerSessions(
  previous: WorkerSessionItemData[], incoming: WorkerSessionItemData[], fromSnapshot = false,
): WorkerSessionItemData[] {
  // Only an accepted snapshot can replace the observed session for an existing worker.
  const rows = fromSnapshot ? incoming : incoming.filter(worker =>
    previous.some(item => item.worker_id === worker.worker_id && item.session_id === worker.session_id)
    || !previous.some(item => item.worker_id === worker.worker_id));
  const merged = rows.map(worker => {
    const known = previous.find(item => item.worker_id === worker.worker_id && item.session_id === worker.session_id);
    if (!known) return worker;
    // A disconnected session cannot become active again; rejoin gets a new session ID.
    const keepTerminal = known.state === 'FAILED'
      || ((known.state === 'DISCONNECTED' || known.disconnected_at != null)
        && worker.state !== 'FAILED');
    return {
      ...worker,
      ...(keepTerminal ? {
        state: known.state, disconnected_at: known.disconnected_at,
        failure_code: known.failure_code ?? worker.failure_code,
      } : {}),
      ...(known.local_model_version == null ? {} : {
        local_model_version: Math.max(worker.local_model_version ?? 0, known.local_model_version),
      }),
    };
  });
  for (const known of previous) {
    if (rows.some(worker => worker.worker_id === known.worker_id && worker.session_id === known.session_id)) continue;
    if (!fromSnapshot || known.state === 'DISCONNECTED' || known.state === 'FAILED' || known.disconnected_at != null) {
      merged.push(known);
    }
  }
  return merged;
}
