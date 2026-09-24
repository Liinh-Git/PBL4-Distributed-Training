import { DiagnosticEvent } from '../types';

export type EventCategory = 'all' | 'training' | 'workers' | 'checkpoints' | 'warnings';
export type EventIconType = 'normal' | 'success' | 'warning' | 'error';

export interface FormattedEventMessage {
  humanText: string;
  category: 'training' | 'workers' | 'checkpoints' | 'warnings';
  iconType: EventIconType;
  secondaryInfo?: string;
}

export function formatDiagnosticEvent(event: any): FormattedEventMessage {
  const eventName = event.event_type || event.event || '';
  const severity = event.severity || 'INFO';
  const payload = event.details || event.payload || {};
  const workerId = payload.worker_id ?? payload.workerId;
  const stepId = payload.step_id ?? payload.stepId ?? payload.operation_id ?? payload.operationId;
  const batchId = payload.batch_id ?? payload.batchId ?? (payload.batch_ordinal ? `batch-${payload.batch_ordinal}` : undefined);
  const modelVer = payload.model_version ?? payload.model_version_out ?? payload.modelVersion ?? payload.output_model_version;


  // Check severity for error/warning first
  if (severity === 'CRITICAL' || severity === 'ERROR') {
    if (eventName === 'AttemptFailed' || eventName === 'ATTEMPT_FAILED') {
      return {
        humanText: payload.reason || 'Training stopped because a worker was lost',
        category: 'warnings',
        iconType: 'error',
      };
    }
    if (eventName === 'WorkerDisconnected' || eventName === 'WORKER_DISCONNECTED') {
      return {
        humanText: workerId !== undefined ? `Worker ${workerId} disconnected` : 'Worker disconnected from cluster',
        category: 'warnings',
        iconType: 'error',
      };
    }
    return {
      humanText: payload.error || payload.message || `System alert: ${eventName}`,
      category: 'warnings',
      iconType: 'error',
    };
  }

  if (severity === 'WARN') {
    if (eventName === 'WorkerHeartbeatWarning' || eventName === 'HeartbeatDelayed') {
      return {
        humanText: workerId !== undefined ? `Telemetry heartbeat delayed for Worker ${workerId}` : 'Worker heartbeat delayed',
        category: 'warnings',
        iconType: 'warning',
      };
    }
    if (eventName === 'BarrierTimeoutWarning') {
      return {
        humanText: 'Barrier threshold approaching wait limit',
        category: 'warnings',
        iconType: 'warning',
      };
    }
    return {
      humanText: payload.message || `Warning: ${eventName}`,
      category: 'warnings',
      iconType: 'warning',
    };
  }

  // Checkpoints
  if (
    eventName === 'CheckpointComplete' ||
    eventName === 'CHECKPOINT_COMPLETE' ||
    eventName === 'CheckpointSaved'
  ) {
    return {
      humanText: 'Checkpoint saved successfully',
      category: 'checkpoints',
      iconType: 'success',
      secondaryInfo: payload.checkpoint_id || payload.id,
    };
  }

  if (
    eventName === 'CheckpointStarted' ||
    eventName === 'CHECKPOINT_STARTED' ||
    eventName === 'SavingCheckpoint'
  ) {
    return {
      humanText: 'Saving checkpoint to durable store',
      category: 'checkpoints',
      iconType: 'normal',
    };
  }

  // Worker contributions & synchronization
  if (
    eventName === 'GradientContributionAccepted' ||
    eventName === 'GRADIENT_CONTRIBUTION_ACCEPTED'
  ) {
    const text = workerId !== undefined
      ? `Worker ${workerId} contribution received`
      : 'Worker contribution received';
    return {
      humanText: text,
      category: 'workers',
      iconType: 'normal',
      secondaryInfo: batchId,
    };
  }

  if (
    eventName === 'WaitingForWorker' ||
    eventName === 'WAITING_FOR_WORKER'
  ) {
    const target = payload.waiting_for ?? payload.worker_id ?? 2;
    return {
      humanText: `Waiting for Worker ${target}`,
      category: 'workers',
      iconType: 'warning',
    };
  }

  if (
    eventName === 'WorkerComputeStarted' ||
    eventName === 'WORKER_COMPUTE_STARTED'
  ) {
    const text = workerId !== undefined
      ? `Worker ${workerId} started batch computation`
      : 'Worker compute started';
    return {
      humanText: text,
      category: 'workers',
      iconType: 'normal',
      secondaryInfo: batchId,
    };
  }

  if (
    eventName === 'ParametersAppliedAllWorkers' ||
    eventName === 'PARAMETERS_APPLIED_ALL_WORKERS'
  ) {
    const count = payload.worker_count || 3;
    return {
      humanText: `Parameters applied by ${count}/${count} workers`,
      category: 'training',
      iconType: 'success',
    };
  }

  if (
    eventName === 'ParameterApplied' ||
    eventName === 'PARAMETER_APPLIED'
  ) {
    return {
      humanText: workerId !== undefined ? `Parameters applied by Worker ${workerId}` : 'Parameters applied by worker',
      category: 'workers',
      iconType: 'normal',
    };
  }

  if (
    eventName === 'UpdatingGlobalModel' ||
    eventName === 'UPDATING_GLOBAL_MODEL' ||
    eventName === 'GradientAggregation'
  ) {
    return {
      humanText: 'Updating global model',
      category: 'training',
      iconType: 'normal',
    };
  }

  if (
    eventName === 'ModelVersionReady' ||
    eventName === 'MODEL_VERSION_READY'
  ) {
    return {
      humanText: modelVer ? `Model version ${modelVer} ready` : 'New model version ready',
      category: 'training',
      iconType: 'success',
    };
  }

  if (
    eventName === 'StepCommitted' ||
    eventName === 'STEP_COMMITTED'
  ) {
    return {
      humanText: stepId ? `Step ${stepId} completed` : 'Training step completed',
      category: 'training',
      iconType: 'success',
      secondaryInfo: modelVer ? `Version ${modelVer}` : undefined,
    };
  }

  if (
    eventName === 'CollectingGradients' ||
    eventName === 'StepStarted' ||
    eventName === 'STEP_STARTED'
  ) {
    return {
      humanText: 'Starting next training step',
      category: 'training',
      iconType: 'normal',
    };
  }

  if (eventName === 'WorkerSessionAttached' || eventName === 'WorkerConnected') {
    return {
      humanText: workerId !== undefined ? `Worker ${workerId} connected and verified` : 'Worker session connected',
      category: 'workers',
      iconType: 'success',
    };
  }

  if (eventName === 'ModelTensorsBroadcast') {
    return {
      humanText: 'Broadcasting updated parameters to cluster',
      category: 'training',
      iconType: 'normal',
    };
  }

  if (eventName === 'ContractResolved') {
    return {
      humanText: 'Strict BSP contract resolved and locked',
      category: 'training',
      iconType: 'normal',
    };
  }

  // Fallback: Convert PascalCase/camelCase/snake_case to clean human sentence
  let cleaned = eventName
    .replace(/([A-Z])/g, ' $1')
    .replace(/_/g, ' ')
    .trim();
  cleaned = cleaned.charAt(0).toUpperCase() + cleaned.slice(1).toLowerCase();

  return {
    humanText: cleaned,
    category: 'training',
    iconType: 'normal',
  };
}
