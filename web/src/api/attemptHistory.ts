import { attemptsService } from './attempts';
import { workersService } from './workers';
import { stepsService } from './steps';
import { SharedReads } from './sharedReads';
import { EVENT_WINDOW, mergeRuntimeEvents } from '../utils/runtimeEvents';
import type { RuntimeEventItemData } from '../types/api';

export const historyReads = new SharedReads(24);
export const HISTORY_CACHE_MS = 60_000;
export const isTerminalAttempt = (state?: string | null) => ['COMPLETED', 'FAILED', 'ABORTED'].includes(state ?? '');

/** A bounded baseline. Older step pages follow in the background after rendering. */
export function loadAttemptBaseline(attemptId: string, signal: AbortSignal) {
  return historyReads.read(`baseline:${attemptId}`, async sharedSignal => {
    const options = { signal: sharedSignal };
    return Promise.allSettled([
      attemptsService.getAttempt(attemptId, options), attemptsService.getSnapshot(attemptId, options),
      workersService.listWorkers(attemptId, options),
      stepsService.listSteps(attemptId, { limit: 200 }, options),
    ] as const);
  }, signal, results => {
    const [attempt, snapshot] = results;
    return results.every(result => result.status === 'fulfilled')
      && attempt.status === 'fulfilled' && isTerminalAttempt(attempt.value.data.state)
      && snapshot.status === 'fulfilled' && !snapshot.value.data.stale
      && snapshot.value.data.state === attempt.value.data.state ? HISTORY_CACHE_MS : 0;
  });
}

/** Recent diagnostic events must not delay the overview or full epoch metrics. */
export function loadRecentHistory(attemptId: string, throughSeq: number, signal: AbortSignal, terminal: boolean) {
  return historyReads.read(`recent:${attemptId}:${throughSeq}`, async sharedSignal => {
    let cursor = Math.max(0, throughSeq - EVENT_WINDOW);
    let rows: RuntimeEventItemData[] = [];
    while (!sharedSignal.aborted) {
      const page = await attemptsService.getCatchUpEvents(attemptId, { after_seq: cursor, limit: 200 }, { signal: sharedSignal });
      rows = mergeRuntimeEvents(rows, page.data);
      const next = page.data.at(-1)?.runtime_event_seq;
      if (next == null || next <= cursor || page.meta.complete || page.data.length < 200) break;
      cursor = next;
      if (cursor >= throughSeq) break;
    }
    return rows;
  }, signal, terminal ? HISTORY_CACHE_MS : 0);
}

export function loadEpochHistory(attemptId: string, afterSeq: number, signal: AbortSignal, terminal: boolean) {
  return historyReads.read(`epochs:${attemptId}:${afterSeq}`, async sharedSignal => {
    const events: RuntimeEventItemData[] = [];
    let cursor = afterSeq;
    while (!sharedSignal.aborted) {
      const page = await attemptsService.getCatchUpEvents(attemptId, {
        event_type: 'epoch.metrics.finalized', after_seq: cursor, limit: 100,
      }, { signal: sharedSignal });
      const items = page.data;
      if (!items.length) break;
      const next = items.at(-1)!.runtime_event_seq;
      if (next <= cursor) throw new Error('Epoch history cursor did not advance');
      events.push(...items);
      cursor = next;
      if (items.length < 100) break;
    }
    return { events, cursor };
  }, signal, terminal ? HISTORY_CACHE_MS : 0);
}
