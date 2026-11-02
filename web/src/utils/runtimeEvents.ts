import type { DiagnosticEvent } from '../types';
import type { RuntimeEventItemData } from '../types/api';

export const EVENT_WINDOW = 1024;

export function mergeRuntimeEvents(
  current: RuntimeEventItemData[], incoming: RuntimeEventItemData[],
): RuntimeEventItemData[] {
  const items = new Map(current.map(event => [event.runtime_event_seq, event]));
  for (const event of incoming) items.set(event.runtime_event_seq, event);
  return [...items.values()].sort((a, b) => b.runtime_event_seq - a.runtime_event_seq)
    .slice(0, EVENT_WINDOW);
}

export function toDiagnosticEvent(event: RuntimeEventItemData): DiagnosticEvent {
  const identity = `${event.attempt_id}:${event.runtime_event_seq}`;
  return {
    id: identity, time: event.occurred_at,
    severity: event.severity === 'WARNING' ? 'WARN' : event.severity,
    event: event.event_type, scope: 'ATTEMPT', runtimeSeq: event.runtime_event_seq,
    source: event.source_component, attemptId: event.attempt_id,
    payload: event.details, technicalCorrelationId: identity,
  };
}
