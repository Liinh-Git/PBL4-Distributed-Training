/**
 * Attempt Realtime Stream Hook & State Controller
 *
 * API implementation reference: docs/API.md
 */

import { useState, useEffect, useRef, useCallback, useContext } from 'react';
import { AppContext } from '../context/AppContext';
import { config } from '../config';
import { EVENT_WINDOW, mergeRuntimeEvents } from '../utils/runtimeEvents';
import { loadAttemptBaseline, loadRecentHistory, historyReads, HISTORY_CACHE_MS, isTerminalAttempt } from '../api/attemptHistory';
import {
  attemptsService,
  workersService,
  stepsService,
} from '../api';
import {
  AttemptDetailData,
  AttemptSnapshotData,
  AttemptState,
  RuntimeEventItemData,
  StepListItemData,
  StepDetailData,
  WorkerSessionItemData,
  WorkerStepData,
  WsFrameData,
} from '../types/api';

export type StreamConnectionState =
  | 'IDLE'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'DISCONNECTED'
  | 'DEGRADED';

// Live events enrich the REST step summary with the same measured detail fields.
type LiveStep = StepListItemData & Partial<Pick<StepDetailData, 'timing' | 'worker_steps'>>;

export interface UseAttemptStreamResult {
  connectionState: StreamConnectionState;
  attempt: AttemptDetailData | null;
  snapshot: AttemptSnapshotData | null;
  workers: WorkerSessionItemData[];
  steps: LiveStep[];
  events: RuntimeEventItemData[];
  lastReceivedSeq: number;
  isStale: boolean;
  gapDetected: boolean;
  loading: boolean;
  error: string | null;
  hasMoreSteps: boolean;
  loadingMoreSteps: boolean;
  stepsError: string | null;
  loadMoreSteps: () => Promise<void>;
  refreshSnapshot: () => Promise<void>;
  requestCheckpoint: (reason?: string) => Promise<void>;
  abortAttempt: (reason?: string) => Promise<void>;
}

export function useAttemptStream(attemptId: string | null): UseAttemptStreamResult {
  const appContext = useContext(AppContext);
  const setRuntimeStale = appContext?.setIsRuntimeStale;
  const setHistoryGap = appContext?.setHasEventHistoryGap;
  const [connectionState, setConnectionState] = useState<StreamConnectionState>('IDLE');
  const [attempt, setAttempt] = useState<AttemptDetailData | null>(null);
  const [snapshot, setSnapshot] = useState<AttemptSnapshotData | null>(null);
  const [workers, setWorkers] = useState<WorkerSessionItemData[]>([]);
  const [steps, setSteps] = useState<LiveStep[]>([]);
  const [events, setEvents] = useState<RuntimeEventItemData[]>([]);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [gapDetected, setGapDetected] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [nextStepsCursor, setNextStepsCursor] = useState<string | null>(null);
  const hasMoreSteps = nextStepsCursor != null;
  const [loadingMoreSteps, setLoadingMoreSteps] = useState(false);
  const [stepsError, setStepsError] = useState<string | null>(null);
  const loadingMoreRef = useRef(false);
  const stepPageCursorsRef = useRef(new Set<string>());
  const lifecycleRef = useRef<AbortController | null>(null);
  const attemptRef = useRef(attempt);
  attemptRef.current = attempt;

  // Sync live stale/gap indicators into AppContext
  useEffect(() => {
    setRuntimeStale?.(isStale);
  }, [isStale, setRuntimeStale]);

  useEffect(() => {
    setHistoryGap?.(gapDetected);
  }, [gapDetected, setHistoryGap]);

  // References for connection management
  const wsRef = useRef<WebSocket | null>(null);
  const snapshotRevisionRef = useRef(0);
  const lastSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<any>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const currentAttemptRef = useRef(attemptId);
  currentAttemptRef.current = attemptId;
  const stepsRef = useRef(steps);
  stepsRef.current = steps;
  const refreshInFlightRef = useRef<Promise<void> | null>(null);
  const pendingEventsRef = useRef<RuntimeEventItemData[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [lastReceivedSeq, setLastReceivedSeq] = useState<number>(0);

  const updateSeq = (newSeq: number) => {
    if (newSeq > lastSeqRef.current) {
      lastSeqRef.current = newSeq;
      if (!flushTimerRef.current) flushTimerRef.current = setTimeout(() => {
        flushTimerRef.current = null;
        if (!isMountedRef.current || currentAttemptRef.current !== attemptId) return;
        const batch = pendingEventsRef.current;
        pendingEventsRef.current = [];
        if (batch.length) setEvents(prev => mergeRuntimeEvents(prev, batch));
        setLastReceivedSeq(lastSeqRef.current);
      }, 50);
    }
  };

  /**
   * Fetch full fresh snapshot and reconcile local live state
   */
  const refreshSnapshot = useCallback(async () => {
    if (!attemptId) return;
    if (refreshInFlightRef.current) return refreshInFlightRef.current;
    const signal = lifecycleRef.current?.signal;
    const newestKnownStep = stepsRef.current[0]?.step_id ?? 0;
    historyReads.invalidate(`baseline:${attemptId}`);
    const requestedAtSeq = lastSeqRef.current;
    const requestedAtSnapshot = snapshotRevisionRef.current;
    const request = (async () => {
      try {
        const [snapRes, workersRes, stepsRes] = await Promise.allSettled([
          attemptsService.getSnapshot(attemptId, { signal }),
          workersService.listWorkers(attemptId, { signal }),
          stepsService.listStepUpdates(attemptId, newestKnownStep, { signal }),
        ]);
        if (signal?.aborted || !isMountedRef.current || currentAttemptRef.current !== attemptId) return;

        if (snapRes.status === 'fulfilled' && requestedAtSnapshot === snapshotRevisionRef.current) {
          const snap = snapRes.value.data;
          setIsStale(snap.stale ?? false);
          if (snap.runtime_event_seq != null && snap.runtime_event_seq >= lastSeqRef.current) {
            setSnapshot(snap);
            setAttempt(prev => {
              if (!prev) return prev;
              return {
                ...prev,
                ...(snap.state ? { state: snap.state } : {}),
                ...(snap.model_version !== null && snap.model_version !== undefined ? { model_version: snap.model_version } : {}),
                ...(snap.epoch !== null && snap.epoch !== undefined ? { epoch: snap.epoch } : {}),
                ...(snap.strategy_state ? { strategy_state: snap.strategy_state } : {}),
              };
            });
          }
        } else if (snapRes.status === 'rejected' && requestedAtSnapshot === snapshotRevisionRef.current) {
          setIsStale(true);
        }

        if (workersRes.status === 'fulfilled' && requestedAtSnapshot === snapshotRevisionRef.current) {
          setWorkers(previous => (workersRes.value.data || []).map(worker => {
            const known = previous.find(item => item.session_id === worker.session_id);
            return known?.local_model_version == null ? worker : {
              ...worker, local_model_version: Math.max(worker.local_model_version ?? 0, known.local_model_version),
            };
          }));
        }

        if (stepsRes.status === 'fulfilled') {
          setStepsError(null);
          if (!newestKnownStep) {
            setNextStepsCursor(stepsRes.value.page?.next_cursor ?? null);
          }
          setSteps(prev => {
            const merged = new Map<number, LiveStep>(prev.map(step => [step.step_id, step]));
            for (const step of stepsRes.value.data || []) {
              const known = merged.get(step.step_id);
              // A slower REST response must not overwrite a newer live transition.
              if (known && lastSeqRef.current > requestedAtSeq) continue;
              merged.set(step.step_id, { ...known, ...step, metrics: step.metrics ?? known?.metrics });
            }
            return [...merged.values()].sort((a, b) => b.step_id - a.step_id);
          });
        } else setStepsError('Không thể tải các step mới. Hãy thử làm mới.');
      } catch (err: any) {
        // Degraded state notification
        if (isMountedRef.current && currentAttemptRef.current === attemptId) setIsStale(true);
      }
    })();
    refreshInFlightRef.current = request;
    try { await request; } finally {
      if (refreshInFlightRef.current === request) refreshInFlightRef.current = null;
    }
  }, [attemptId]);

  const loadMoreSteps = useCallback(async () => {
    if (!attemptId || loadingMoreRef.current) return;
    const cursor = nextStepsCursor;
    if (!cursor) return;
    const signal = lifecycleRef.current?.signal;
    const requestedAtSeq = lastSeqRef.current;
    loadingMoreRef.current = true;
    setLoadingMoreSteps(true);
    setStepsError(null);
    try {
      const page = await historyReads.read(`steps:${attemptId}:${cursor}`,
        sharedSignal => stepsService.listSteps(attemptId, { limit: 200, cursor }, { signal: sharedSignal }),
        signal, isTerminalAttempt(attemptRef.current?.state) ? HISTORY_CACHE_MS : 0);
      if (signal?.aborted || !isMountedRef.current || currentAttemptRef.current !== attemptId) return;
      if (page.page?.next_cursor === cursor || (page.page?.next_cursor && stepPageCursorsRef.current.has(page.page.next_cursor))) {
        throw new Error('Repeated steps pagination cursor');
      }
      setSteps(previous => {
        const merged = new Map<number, LiveStep>(previous.map(step => [step.step_id, step]));
        for (const step of page.data) {
          const known = merged.get(step.step_id);
          if (!known || lastSeqRef.current <= requestedAtSeq) merged.set(step.step_id, { ...known, ...step });
        }
        return [...merged.values()].sort((a, b) => b.step_id - a.step_id);
      });
      stepPageCursorsRef.current.add(cursor);
      setNextStepsCursor(page.page?.next_cursor ?? null);
    } catch {
      if (!signal?.aborted && currentAttemptRef.current === attemptId) setStepsError('Không thể tải đầy đủ lịch sử. Hãy thử lại.');
    } finally {
      if (!signal?.aborted && currentAttemptRef.current === attemptId) {
        loadingMoreRef.current = false;
        setLoadingMoreSteps(false);
      }
    }
  }, [attemptId, nextStepsCursor]);

  // Show the baseline first, then read older pages one at a time in the background.
  useEffect(() => {
    if (!attemptId || loading || loadingMoreSteps || stepsError || !nextStepsCursor) return;
    const timer = setTimeout(() => { void loadMoreSteps(); }, 150);
    return () => clearTimeout(timer);
  }, [attemptId, loading, loadingMoreSteps, stepsError, nextStepsCursor, loadMoreSteps]);

  // Keep fresh ref to avoid stale closures in WebSocket event callbacks
  const refreshSnapshotRef = useRef(refreshSnapshot);
  useEffect(() => {
    refreshSnapshotRef.current = refreshSnapshot;
  }, [refreshSnapshot]);

  // Bounded coalesced refresh to avoid request storms on rapid runtime event batches
  const coalescedRefreshTimerRef = useRef<any>(null);
  const triggerCoalescedRefresh = useCallback(() => {
    if (coalescedRefreshTimerRef.current) return;
    coalescedRefreshTimerRef.current = setTimeout(() => {
      coalescedRefreshTimerRef.current = null;
      if (isMountedRef.current) {
        refreshSnapshotRef.current();
      }
    }, 250);
  }, []);

  /**
   * Initialize REST baseline data on attempt mount
   */
  const loadInitialRestState = useCallback(async (signal: AbortSignal) => {
    if (!attemptId) return;
    try {
      setLoading(true);
      setError(null);

      const [attemptRes, snapRes, workersRes, stepsRes] =
        await loadAttemptBaseline(attemptId, signal);
      if (signal.aborted || !isMountedRef.current || currentAttemptRef.current !== attemptId) return;

      if (attemptRes.status === 'fulfilled') {
        setAttempt(attemptRes.value.data);
      } else {
        throw attemptRes.reason;
      }

      if (snapRes.status === 'fulfilled') {
        const snap = snapRes.value.data;
        setSnapshot(snap);
        setIsStale(snap.stale ?? false);
        if (snap.runtime_event_seq) {
          updateSeq(snap.runtime_event_seq);
        }
      }

      if (workersRes.status === 'fulfilled') {
        setWorkers(workersRes.value.data || []);
      }

      if (stepsRes.status === 'fulfilled') {
        setSteps(stepsRes.value.data || []);
        setNextStepsCursor(stepsRes.value.page?.next_cursor ?? null);
      } else setStepsError('Không thể tải lịch sử step. Hãy thử làm mới.');

      if (snapRes.status === 'fulfilled') {
        void loadRecentHistory(attemptId, snapRes.value.data.runtime_event_seq ?? 0,
          signal, isTerminalAttempt(attemptRes.value.data.state)).then(rows => {
          if (!signal.aborted && isMountedRef.current && currentAttemptRef.current === attemptId) {
            setEvents(previous => mergeRuntimeEvents(previous, rows));
          }
        }).catch(() => {});
      }
      return !(isTerminalAttempt(attemptRes.value.data.state)
        && snapRes.status === 'fulfilled' && !snapRes.value.data.stale
        && snapRes.value.data.state === attemptRes.value.data.state);
    } catch (err: any) {
      if (!signal.aborted && isMountedRef.current && currentAttemptRef.current === attemptId) {
        setError(err?.message || `Failed to load attempt ${attemptId}`);
      }
    } finally {
      if (!signal.aborted && isMountedRef.current && currentAttemptRef.current === attemptId) setLoading(false);
    }
  }, [attemptId]);

  /**
   * Connect and manage WebSocket stream lifecycle
   */
  const connectWebSocket = useCallback(() => {
    if (!attemptId || !isMountedRef.current) return;

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const currentSeq = lastSeqRef.current;
    const wsUrl = `${config.wsBaseUrl}/ws/v1/attempts/${encodeURIComponent(
      attemptId
    )}?after_seq=${currentSeq}`;

    setConnectionState(
      reconnectAttemptsRef.current > 0 ? 'RECONNECTING' : 'CONNECTING'
    );

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMountedRef.current || wsRef.current !== ws) return;
        setConnectionState('CONNECTED');
        reconnectAttemptsRef.current = 0;
      };

      const handleMessage = async (event: MessageEvent): Promise<void> => {
        if (!isMountedRef.current || wsRef.current !== ws || ws.readyState !== WebSocket.OPEN) return;
        try {
          const frame: WsFrameData = JSON.parse(event.data);
          if (frame.attempt_id !== attemptId) return;

          if (frame.kind === 'EVENT') {
            const seq = frame.runtime_event_seq;

            // Duplicate event check
            if (seq <= lastSeqRef.current && seq !== 0) {
              return;
            }

            // Apply missing events in sequence before advancing the live cursor.
            if (seq > lastSeqRef.current + 1) {
              setGapDetected(true);
              while (seq > lastSeqRef.current + 1) {
                const before = lastSeqRef.current;
                const page = await attemptsService.getCatchUpEvents(attemptId, {
                  after_seq: before, limit: 200,
                });
                if (!isMountedRef.current || wsRef.current !== ws) return;
                if (page.meta.snapshot_required || !page.data.length) {
                  const snap = (await attemptsService.getSnapshot(attemptId)).data;
                  if (!isMountedRef.current || wsRef.current !== ws) return;
                  if (snap.stale || snap.runtime_event_seq == null || snap.runtime_event_seq < seq - 1) {
                    throw new Error('Authoritative snapshot unavailable for event gap');
                  }
                  setSnapshot(snap);
                  setAttempt(prev => prev ? { ...prev, ...snap } : prev);
                  updateSeq(snap.runtime_event_seq);
                  await refreshSnapshot();
                  break;
                }
                for (const missing of page.data) {
                  if (missing.runtime_event_seq >= seq) break;
                  await handleMessage({
                    data: JSON.stringify({
                      kind: 'EVENT', attempt_id: missing.attempt_id,
                      runtime_event_seq: missing.runtime_event_seq, occurred_at: missing.occurred_at,
                      payload: {
                        event_type: missing.event_type, severity: missing.severity,
                        source_component: missing.source_component, details: missing.details
                      },
                    })
                  } as MessageEvent);
                  if (ws.readyState !== WebSocket.OPEN) throw new Error('Catch-up interrupted');
                }
                if (lastSeqRef.current === before) throw new Error('Event catch-up did not advance');
              }
              setGapDetected(false);
              if (seq <= lastSeqRef.current) return;
            }

            updateSeq(seq);

            const newEventItem: RuntimeEventItemData = {
              attempt_id: frame.attempt_id,
              runtime_event_seq: seq,
              event_type: frame.payload.event_type || 'runtime.event',
              event_schema_version: frame.payload.event_schema_version || 1,
              occurred_at: frame.occurred_at || new Date().toISOString(),
              source_component: frame.payload.source_component || 'Runtime',
              severity: frame.payload.severity || 'INFO',
              details: frame.payload.details || {},
            };

            pendingEventsRef.current.push(newEventItem);
            if (pendingEventsRef.current.length > EVENT_WINDOW) {
              pendingEventsRef.current = pendingEventsRef.current.slice(-EVENT_WINDOW);
            }

            // Reactively update attempt state on critical events
            if (frame.payload.event_type === 'attempt.state_changed') {
              const nextState = frame.payload.details?.state as AttemptState;
              if (nextState) {
                setAttempt(prev => (prev ? { ...prev, state: nextState } : prev));
              }
            } else if (frame.payload.event_type === 'model.updated') {
              const newModelVer = frame.payload.details?.output_model_version;
              if (newModelVer) {
                setAttempt(prev =>
                  prev ? { ...prev, model_version: newModelVer } : prev
                );
              }
            }

            const details = newEventItem.details;
            const observation: Partial<AttemptSnapshotData> = {
              runtime_event_seq: seq, observed_at: newEventItem.occurred_at, stale: false,
            };
            if (details.strategy_state) observation.strategy_state = details.strategy_state;
            if (newEventItem.event_type === 'step.started') {
              observation.epoch = details.epoch;
              observation.current_batch_ordinal = details.batch_ordinal;
              observation.current_operation_id = details.operation_id;
            } else if (newEventItem.event_type === 'model.updated') {
              observation.model_version = details.output_model_version;
            } else if (newEventItem.event_type === 'step.committed' && details.recovery_cursor) {
              observation.epoch = details.recovery_cursor.epoch;
              observation.current_batch_ordinal = details.recovery_cursor.next_batch_ordinal;
            }
            snapshotRevisionRef.current += 1;
            setSnapshot(prev => prev ? { ...prev, ...observation } : prev);
            setIsStale(false);
            if (newEventItem.event_type === 'step.started') {
              const step: LiveStep = {
                step_id: details.step_id, operation_id: details.operation_id,
                input_model_version: details.input_model_version,
                state: 'COLLECTING_GRADIENTS', epoch: details.epoch, batch_ordinal: details.batch_ordinal,
                timing: { started_at: details.started_at ?? newEventItem.occurred_at },
              };
              setSteps(prev => [step, ...prev.filter(item => item.step_id !== step.step_id)]);
            } else if (['model.updated', 'step.committed'].includes(newEventItem.event_type)) {
              setSteps(prev => prev.map(step => step.step_id === details.step_id ? {
                ...step,
                state: newEventItem.event_type === 'step.committed' ? 'COMMITTED' : 'WAITING_PARAMETER_APPLIED',
                output_model_version: details.output_model_version,
                total_sample_count: details.total_sample_count,
                ...(details.committed_at ? { committed_at: details.committed_at } : {}),
                timing: (details.started_at || step.timing?.started_at) ? {
                  ...step.timing,
                  started_at: details.started_at ?? step.timing!.started_at,
                  ...(details.update_completed_at ? { update_completed_at: details.update_completed_at } : {}),
                  ...(details.synchronization_completed_at ? { synchronization_completed_at: details.synchronization_completed_at } : {}),
                  ...(details.committed_at ? { committed_at: details.committed_at } : {}),
                } : step.timing,
                ...(details.contributions ? {
                  worker_steps: details.contributions.map((item: WorkerStepData) => ({
                    ...item, session_id: String(item.session_id), contribution_accepted: true,
                  })),
                } : {}),
              } : step));
            } else if (newEventItem.event_type === 'parameter.applied') {
              setWorkers(prev => prev.map(worker => worker.worker_id === details.worker_id
                && String(worker.session_id) === String(details.session_id)
                ? { ...worker, local_model_version: details.model_version } : worker));
              setSteps(prev => prev.map(step => step.step_id === details.step_id ? {
                ...step, worker_steps: step.worker_steps?.map(worker =>
                  worker.worker_id === details.worker_id && String(worker.session_id) === String(details.session_id)
                    ? { ...worker, parameter_applied: true } : worker),
              } : step));
            }
            // Local step/model updates avoid a REST round-trip per training event.
            if (newEventItem.event_type.startsWith('checkpoint.') ||
              newEventItem.event_type === 'attempt.state_changed') triggerCoalescedRefresh();
          } else if (frame.kind === 'SNAPSHOT') {
            const snapPayload = frame.payload;
            if (snapPayload.snapshot_seq != null && snapPayload.snapshot_seq < lastSeqRef.current) return;
            snapshotRevisionRef.current += 1;
            if (snapPayload.state) {
              if (Array.isArray(snapPayload.state.workers)) setWorkers(snapPayload.state.workers);
              setSnapshot(prev => ({
                ...(prev || ({} as any)),
                ...snapPayload.state,
              }));
              if (snapPayload.state.state) {
                setAttempt(prev =>
                  prev ? {
                    ...prev, state: snapPayload.state.state,
                    model_version: snapPayload.state.model_version ?? prev.model_version,
                    epoch: snapPayload.state.epoch ?? prev.epoch,
                    strategy_state: snapPayload.state.strategy_state ?? prev.strategy_state,
                  } : prev
                );
              }
              if (typeof snapPayload.state.stale === 'boolean') {
                setIsStale(snapPayload.state.stale);
              }
            }
            if (snapPayload.snapshot_seq != null) {
              updateSeq(snapPayload.snapshot_seq);
            }
            triggerCoalescedRefresh();
          } else if (frame.kind === 'ATTEMPT_STATE_CHANGED') {
            setAttempt(prev => prev ? { ...prev, state: frame.payload.state } : prev);
            triggerCoalescedRefresh();
          } else if (frame.kind === 'GAP') {
            if (frame.payload.snapshot_required) {
              setGapDetected(true);
              const snap = (await attemptsService.getSnapshot(attemptId)).data;
              if (!isMountedRef.current || wsRef.current !== ws) return;
              if (snap.stale || snap.runtime_event_seq == null) throw new Error('Snapshot required');
              setSnapshot(snap);
              setAttempt(prev => prev ? { ...prev, ...snap } : prev);
              updateSeq(snap.runtime_event_seq);
              await refreshSnapshot();
              setGapDetected(false);
            }
          }
        } catch (parseErr) {
          if (!isMountedRef.current || wsRef.current !== ws) return;
          setGapDetected(true);
          setIsStale(true);
          console.error('Failed to reconcile WebSocket frame:', parseErr);
          ws.close(1013, 'Event reconciliation required');
        }
      };

      let delivery = Promise.resolve();
      let queued = 0;
      ws.onmessage = event => {
        if (++queued > EVENT_WINDOW) { ws.close(1013, 'Client backlog'); return; }
        delivery = delivery.then(() => handleMessage(event)).finally(() => { queued--; });
      };

      ws.onerror = () => {
        if (!isMountedRef.current || wsRef.current !== ws) return;
        setConnectionState('DEGRADED');
      };

      ws.onclose = (e) => {
        if (!isMountedRef.current || wsRef.current !== ws) return;
        setConnectionState('DISCONNECTED');
        setIsStale(true);
        wsRef.current = null;

        // Controlled exponential backoff reconnect
        if (e.code !== 1008) {
          const backoffDelay = Math.min(
            1000 * Math.pow(2, reconnectAttemptsRef.current),
            15000
          );
          reconnectAttemptsRef.current += 1;
          reconnectTimerRef.current = setTimeout(() => {
            if (isMountedRef.current) {
              connectWebSocket();
            }
          }, backoffDelay);
        }
      };
    } catch (wsErr) {
      setConnectionState('DISCONNECTED');
    }
  }, [attemptId, refreshSnapshot]);

  // Main lifecycle effect
  useEffect(() => {
    const controller = new AbortController();
    lifecycleRef.current = controller;
    isMountedRef.current = true;
    snapshotRevisionRef.current += 1;
    lastSeqRef.current = 0;
    setLastReceivedSeq(0);
    pendingEventsRef.current = [];
    refreshInFlightRef.current = null;
    reconnectAttemptsRef.current = 0;
    setNextStepsCursor(null);
    loadingMoreRef.current = false;
    stepPageCursorsRef.current.clear();
    setLoadingMoreSteps(false);
    setStepsError(null);

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (attemptId) {
      setAttempt(null);
      setSnapshot(null);
      setWorkers([]);
      setSteps([]);
      setEvents([]);
      setIsStale(false);
      setGapDetected(false);
      setConnectionState('IDLE');
      loadInitialRestState(controller.signal).then(shouldConnect => {
        if (shouldConnect !== false && !controller.signal.aborted && isMountedRef.current && currentAttemptRef.current === attemptId) {
          connectWebSocket();
        }
      });
    } else {
      setConnectionState('IDLE');
      setAttempt(null);
      setSnapshot(null);
      setWorkers([]);
      setSteps([]);
      setEvents([]);
      setIsStale(false);
      setGapDetected(false);
      setLoading(false);
      setRuntimeStale?.(false);
      setHistoryGap?.(false);
    }

    return () => {
      controller.abort();
      isMountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (coalescedRefreshTimerRef.current) {
        clearTimeout(coalescedRefreshTimerRef.current);
        coalescedRefreshTimerRef.current = null;
      }
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setRuntimeStale?.(false);
      setHistoryGap?.(false);
    };
  }, [attemptId, loadInitialRestState, connectWebSocket, setRuntimeStale, setHistoryGap]);

  /**
   * Action: Manual Checkpoint Request (API 34.0)
   */
  const requestCheckpointAction = async (reason = 'manual') => {
    if (!attemptId) return;
    await attemptsService.requestCheckpoint(attemptId, { reason });
  };

  /**
   * Action: Abort Attempt (API 25.0)
   */
  const abortAttemptAction = async (reason = 'Operator aborted attempt') => {
    if (!attemptId) return;
    await attemptsService.abortAttempt(attemptId, { reason });
  };

  return {
    connectionState,
    attempt,
    snapshot,
    workers,
    steps,
    events,
    lastReceivedSeq,
    isStale,
    gapDetected,
    loading,
    error,
    hasMoreSteps,
    loadingMoreSteps,
    stepsError,
    loadMoreSteps,
    refreshSnapshot,
    requestCheckpoint: requestCheckpointAction,
    abortAttempt: abortAttemptAction,
  };
}

