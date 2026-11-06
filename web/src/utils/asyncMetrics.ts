import type { AttemptDetailData, AttemptSnapshotData, RuntimeEventItemData, StrategyStateStrictBSPData } from '../types/api';

const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;

/** Recover measured progress from the baseline or its replayed history. */
export function selectAsyncProgress(attempt: AttemptDetailData | null, snapshot: AttemptSnapshotData | null, events: RuntimeEventItemData[]): StrategyStateStrictBSPData | null {
  if (!attempt) return null;
  const candidates: { progress: StrategyStateStrictBSPData; seq: number }[] = [];
  if (attempt.strategy_state?.type === 'async_sgd') candidates.push({ progress: attempt.strategy_state, seq: attempt.runtime?.runtime_event_seq ?? -1 });
  if (snapshot?.attempt_id === attempt.attempt_id && snapshot.strategy_state?.type === 'async_sgd') candidates.push({ progress: snapshot.strategy_state, seq: snapshot.runtime_event_seq ?? -1 });
  for (const event of events) {
    if (event.attempt_id !== attempt.attempt_id || event.event_type !== 'async.progress' || finite(event.details?.processed_units) == null) continue;
    candidates.push({ progress: { ...event.details, type: 'async_sgd' }, seq: event.runtime_event_seq });
  }
  // Counters are monotonic within an Attempt, including after a session rejoin.
  return candidates.sort((a, b) => (b.progress.processed_units ?? -1) - (a.progress.processed_units ?? -1) || b.seq - a.seq)[0]?.progress ?? null;
}

export interface AsyncMetricPoint {
  seq: number;
  processedUnits: number;
  processedSamples: number | null;
  appliedUnits: number | null;
  droppedUnits: number | null;
  modelVersion: number | null;
  loss: number | null;
  staleness: number | null;
  samplesPerSecond: number | null;
  timestamp: number;
}

/** Async telemetry is a contribution series, never synthetic BSP Steps. */
export function computeAsyncMetrics(events: RuntimeEventItemData[], attemptId: string): AsyncMetricPoint[] {
  const unique = new Map<number, RuntimeEventItemData>();
  for (const event of events) {
    if (event.attempt_id === attemptId && event.event_type === 'async.progress') unique.set(event.runtime_event_seq, event);
  }
  const points: AsyncMetricPoint[] = [];
  for (const event of [...unique.values()].sort((a, b) => a.runtime_event_seq - b.runtime_event_seq)) {
    const d = event.details;
    const processedUnits = finite(d?.processed_units);
    if (processedUnits == null || processedUnits < 0) continue;
    const samples = finite(d.processed_samples);
    const timestamp = Date.parse(event.occurred_at);
    const previous = points.at(-1);
    const seconds = previous ? (timestamp - previous.timestamp) / 1000 : 0;
    const delta = samples != null && previous?.processedSamples != null ? samples - previous.processedSamples : -1;
    points.push({
      seq: event.runtime_event_seq, processedUnits, processedSamples: samples,
      appliedUnits: finite(d.applied_units), droppedUnits: finite(d.dropped_units),
      modelVersion: finite(d.model_version), loss: finite(d.loss), staleness: finite(d.staleness),
      // Wall-clock rate between measured contributions; no invented initial point.
      samplesPerSecond: seconds > 0 && delta >= 0 ? delta / seconds : null, timestamp,
    });
  }
  return points;
}

export function asyncProgressPercent(progress?: StrategyStateStrictBSPData | null): number | null {
  const processed = finite(progress?.processed_units);
  const target = finite(progress?.target_units);
  return processed != null && processed >= 0 && target != null && target > 0 ? Math.min(100, processed / target * 100) : null;
}
