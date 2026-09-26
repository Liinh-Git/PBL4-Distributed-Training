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
  const rawEventName = String(event.event_type || event.event || '').trim();
  const severity = String(event.severity || 'INFO').toUpperCase();
  const payload = event.details || event.payload || {};
  const workerId = payload.worker_id ?? payload.workerId;
  const stepId = payload.step_id ?? payload.stepId ?? payload.operation_id ?? payload.operationId;
  const batchId = payload.batch_id ?? payload.batchId ?? (payload.batch_ordinal ? `batch-${payload.batch_ordinal}` : undefined);
  const modelVer = payload.model_version ?? payload.model_version_out ?? payload.modelVersion ?? payload.output_model_version;

  const normalized = rawEventName.toLowerCase().replace(/[\._\-]/g, '');

  // 1. Severity Warnings & Errors
  if (
    severity === 'CRITICAL' ||
    severity === 'ERROR' ||
    normalized.includes('failed') ||
    normalized.includes('error') ||
    normalized.includes('abort')
  ) {
    if (normalized.includes('attemptfailed') || normalized.includes('attemptabort')) {
      return {
        humanText: payload.reason || 'Training stopped or attempt failed',
        category: 'warnings',
        iconType: 'error',
      };
    }
    if (
      normalized.includes('workerdisconnected') ||
      normalized.includes('workerlost') ||
      normalized.includes('workerfailed')
    ) {
      return {
        humanText:
          workerId !== undefined
            ? `Worker ${workerId} disconnected`
            : 'Worker disconnected from cluster',
        category: 'warnings',
        iconType: 'error',
      };
    }
    return {
      humanText: payload.error || payload.message || cleanEventTitle(rawEventName),
      category: 'warnings',
      iconType: 'error',
    };
  }

  if (
    severity === 'WARN' ||
    normalized.includes('warning') ||
    normalized.includes('timeout') ||
    normalized.includes('delayed')
  ) {
    if (normalized.includes('heartbeat')) {
      return {
        humanText:
          workerId !== undefined
            ? `Heartbeat delayed for Worker ${workerId}`
            : 'Worker heartbeat delayed',
        category: 'warnings',
        iconType: 'warning',
      };
    }
    if (normalized.includes('barrier')) {
      return {
        humanText: 'Barrier threshold approaching wait limit',
        category: 'warnings',
        iconType: 'warning',
      };
    }
    return {
      humanText: payload.message || cleanEventTitle(rawEventName),
      category: 'warnings',
      iconType: 'warning',
    };
  }

  // 2. Checkpoints
  if (normalized.includes('checkpoint')) {
    if (normalized.includes('saved') || normalized.includes('complete')) {
      const cpId = payload.checkpoint_id || payload.id;
      return {
        humanText: cpId
          ? `Checkpoint ${String(cpId).slice(0, 16)} saved`
          : 'Checkpoint saved successfully',
        category: 'checkpoints',
        iconType: 'success',
        secondaryInfo: cpId,
      };
    }
    if (normalized.includes('started') || normalized.includes('saving')) {
      return {
        humanText: 'Saving checkpoint to durable store',
        category: 'checkpoints',
        iconType: 'normal',
      };
    }
    return {
      humanText: cleanEventTitle(rawEventName),
      category: 'checkpoints',
      iconType: 'normal',
    };
  }

  // 3. Workers & Parameters (Worker actions, parameter transfers, gradients)
  if (
    normalized.includes('worker') ||
    normalized.includes('parameter') ||
    normalized.includes('gradient') ||
    normalized.includes('contribution')
  ) {
    if (
      normalized.includes('gradientcontribution') ||
      normalized.includes('contributionaccepted')
    ) {
      return {
        humanText:
          workerId !== undefined
            ? `Worker ${workerId} gradient contribution received`
            : 'Worker contribution received',
        category: 'workers',
        iconType: 'normal',
        secondaryInfo: batchId,
      };
    }
    if (normalized.includes('waitingforworker')) {
      const target = payload.waiting_for ?? payload.worker_id ?? 2;
      return {
        humanText: `Waiting for Worker ${target}`,
        category: 'workers',
        iconType: 'warning',
      };
    }
    if (
      normalized.includes('workercompute') ||
      normalized.includes('computestarted')
    ) {
      return {
        humanText:
          workerId !== undefined
            ? `Worker ${workerId} started batch computation`
            : 'Worker compute started',
        category: 'workers',
        iconType: 'normal',
        secondaryInfo: batchId,
      };
    }
    if (
      normalized.includes('parametersappliedall') ||
      normalized.includes('parametersappliedallworkers')
    ) {
      const count = payload.worker_count || 3;
      return {
        humanText: `Parameters applied by ${count}/${count} workers`,
        category: 'workers',
        iconType: 'success',
      };
    }
    if (
      normalized.includes('parameterapplied') ||
      normalized.includes('parametersapplied')
    ) {
      return {
        humanText:
          workerId !== undefined
            ? `Parameters applied by Worker ${workerId}`
            : 'Parameters applied by worker',
        category: 'workers',
        iconType: 'normal',
      };
    }
    if (
      normalized.includes('connected') ||
      normalized.includes('attached') ||
      normalized.includes('registered') ||
      normalized.includes('joined')
    ) {
      return {
        humanText:
          workerId !== undefined
            ? `Worker ${workerId} connected and verified`
            : 'Worker session connected',
        category: 'workers',
        iconType: 'success',
      };
    }
    return {
      humanText: cleanEventTitle(rawEventName),
      category: 'workers',
      iconType: 'normal',
    };
  }

  // 4. Training (Steps, Models, Contract)
  if (normalized.includes('step')) {
    if (normalized.includes('committed') || normalized.includes('completed')) {
      return {
        humanText: stepId ? `Step #${stepId} committed` : 'Training step completed',
        category: 'training',
        iconType: 'success',
        secondaryInfo: modelVer ? `Model v${modelVer}` : undefined,
      };
    }
    if (normalized.includes('started')) {
      return {
        humanText: stepId ? `Step #${stepId} started` : 'Starting next training step',
        category: 'training',
        iconType: 'normal',
      };
    }
  }

  if (normalized.includes('model')) {
    if (normalized.includes('updated') || normalized.includes('ready')) {
      return {
        humanText: modelVer
          ? `Global model updated to v${modelVer}`
          : 'Global model parameters updated',
        category: 'training',
        iconType: 'success',
      };
    }
    if (normalized.includes('broadcast') || normalized.includes('sync')) {
      return {
        humanText: 'Broadcasting updated parameters to cluster',
        category: 'training',
        iconType: 'normal',
      };
    }
  }

  if (normalized.includes('contract')) {
    return {
      humanText: 'Strict BSP contract resolved and locked',
      category: 'training',
      iconType: 'normal',
    };
  }

  // General clean title fallback
  return {
    humanText: cleanEventTitle(rawEventName),
    category: 'training',
    iconType: 'normal',
  };
}

function cleanEventTitle(raw: string): string {
  if (!raw) return 'Event';
  let text = raw
    .replace(/[\._\-]/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .replace(/\s+/g, ' ')
    .trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
