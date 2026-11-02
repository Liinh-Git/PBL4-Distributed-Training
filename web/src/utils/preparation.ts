const pretrainingStates = new Set(['CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING']);
const connectedStates = new Set(['PROVISIONING', 'SHARD_READY', 'MODEL_SYNCING', 'READY']);
const dataReadyStates = new Set(['SHARD_READY', 'MODEL_SYNCING', 'READY']);

/** Presentation of existing Runtime states; no inferred download percentage. */
export function getPreparationStatus(state: string | undefined, workers: readonly { state: string }[]) {
  const connected = workers.filter(worker => connectedStates.has(worker.state)).length;
  const dataReady = workers.filter(worker => dataReadyStates.has(worker.state)).length;
  const ready = workers.filter(worker => worker.state === 'READY').length;
  const preparing = pretrainingStates.has(state ?? '');
  const label = state === 'PROVISIONING'
    ? 'Preparing dataset'
    : state === 'INITIALIZING'
      ? 'Initializing model'
      : 'Waiting for workers';
  const description = state === 'PROVISIONING'
    ? 'Workers are downloading dataset artifacts or verifying their local cache. Training starts after every worker confirms data readiness.'
    : state === 'INITIALIZING'
      ? 'Dataset preparation is complete. Workers are synchronizing model parameters before training.'
      : 'Waiting for worker sessions to register with the Runtime. Training has not started.';
  return { preparing, label, description, connected, dataReady, ready };
}
