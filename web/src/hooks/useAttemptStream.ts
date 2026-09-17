/**
 * Attempt Realtime Stream Hook & State Controller
 *
 * Source of Truth: API_contract.md (24.0, 25.0, 27.0 - 31.0, 34.0, 35.0, 39.0)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { config } from '../config';
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
  WorkerSessionItemData,
  WsFrameData,
} from '../types/api';

export type StreamConnectionState =
  | 'IDLE'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'DISCONNECTED'
  | 'DEGRADED';

export interface UseAttemptStreamResult {
  connectionState: StreamConnectionState;
  attempt: AttemptDetailData | null;
  snapshot: AttemptSnapshotData | null;
  workers: WorkerSessionItemData[];
  steps: StepListItemData[];
  events: RuntimeEventItemData[];
  lastReceivedSeq: number;
  isStale: boolean;
  gapDetected: boolean;
  loading: boolean;
  error: string | null;
  refreshSnapshot: () => Promise<void>;
  requestCheckpoint: (reason?: string) => Promise<void>;
  abortAttempt: (reason?: string) => Promise<void>;
}

export function useAttemptStream(attemptId: string | null): UseAttemptStreamResult {
  const [connectionState, setConnectionState] = useState<StreamConnectionState>('IDLE');
  const [attempt, setAttempt] = useState<AttemptDetailData | null>(null);
  const [snapshot, setSnapshot] = useState<AttemptSnapshotData | null>(null);
  const [workers, setWorkers] = useState<WorkerSessionItemData[]>([]);
  const [steps, setSteps] = useState<StepListItemData[]>([]);
  const [events, setEvents] = useState<RuntimeEventItemData[]>([]);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [gapDetected, setGapDetected] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // References for connection management
  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef<number>(0);
  const reconnectTimerRef = useRef<any>(null);
  const reconnectAttemptsRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);
  const [lastReceivedSeq, setLastReceivedSeq] = useState<number>(0);

  const updateSeq = (newSeq: number) => {
    if (newSeq > lastSeqRef.current) {
      lastSeqRef.current = newSeq;
      setLastReceivedSeq(newSeq);
    }
  };

  /**
   * Fetch full fresh snapshot and reconcile local live state
   */
  const refreshSnapshot = useCallback(async () => {
    if (!attemptId) return;
    try {
      const [snapRes, workersRes, stepsRes] = await Promise.allSettled([
        attemptsService.getSnapshot(attemptId),
        workersService.listWorkers(attemptId),
        stepsService.listSteps(attemptId, { limit: 50 }),
      ]);

      if (snapRes.status === 'fulfilled') {
        const snap = snapRes.value.data;
        setSnapshot(snap);
        setIsStale(snap.stale ?? false);
        if (snap.runtime_event_seq) {
          updateSeq(snap.runtime_event_seq);
        }
        if (snap.state) {
          setAttempt(prev => (prev ? { ...prev, state: snap.state } : prev));
        }
      }

      if (workersRes.status === 'fulfilled') {
        setWorkers(workersRes.value.data || []);
      }

      if (stepsRes.status === 'fulfilled') {
        setSteps(stepsRes.value.data || []);
      }
    } catch (err: any) {
      // Degraded state notification
      setIsStale(true);
    }
  }, [attemptId]);

  /**
   * Initialize REST baseline data on attempt mount
   */
  const loadInitialRestState = useCallback(async () => {
    if (!attemptId) return;
    try {
      setLoading(true);
      setError(null);

      const [attemptRes, snapRes, workersRes, stepsRes, eventsRes] =
        await Promise.allSettled([
          attemptsService.getAttempt(attemptId),
          attemptsService.getSnapshot(attemptId),
          workersService.listWorkers(attemptId),
          stepsService.listSteps(attemptId, { limit: 50 }),
          attemptsService.getCatchUpEvents(attemptId, { after_seq: 0, limit: 50 }),
        ]);

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
      }

      if (eventsRes.status === 'fulfilled') {
        const evts = eventsRes.value.data || [];
        setEvents(evts);
        const maxSeq = evts.reduce(
          (max, e) => Math.max(max, e.runtime_event_seq || 0),
          lastSeqRef.current
        );
        updateSeq(maxSeq);
      }
    } catch (err: any) {
      setError(err?.message || `Failed to load attempt ${attemptId}`);
    } finally {
      setLoading(false);
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
        if (!isMountedRef.current) return;
        setConnectionState('CONNECTED');
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = async (event: MessageEvent) => {
        if (!isMountedRef.current) return;
        try {
          const frame: WsFrameData = JSON.parse(event.data);

          if (frame.kind === 'EVENT') {
            const seq = frame.runtime_event_seq;

            // Duplicate event check
            if (seq <= lastSeqRef.current && seq !== 0) {
              return;
            }

            // Gap detection check
            if (lastSeqRef.current > 0 && seq > lastSeqRef.current + 1) {
              setGapDetected(true);
              // Trigger catch-up from REST
              attemptsService
                .getCatchUpEvents(attemptId, {
                  after_seq: lastSeqRef.current,
                  limit: 50,
                })
                .then(res => {
                  if (res.data && res.data.length > 0) {
                    setEvents(prev => {
                      const existingSeqs = new Set(
                        prev.map(e => e.runtime_event_seq)
                      );
                      const newItems = res.data.filter(
                        e => !existingSeqs.has(e.runtime_event_seq)
                      );
                      return [...newItems, ...prev];
                    });
                  }
                  setGapDetected(false);
                })
                .catch(() => {
                  setGapDetected(false);
                });
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

            setEvents(prev => {
              if (prev.some(e => e.runtime_event_seq === seq)) {
                return prev;
              }
              return [newEventItem, ...prev];
            });

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
          } else if (frame.kind === 'SNAPSHOT') {
            const snapPayload = frame.payload;
            if (snapPayload.state) {
              setSnapshot(prev => ({
                ...(prev || ({} as any)),
                ...snapPayload.state,
              }));
              if (snapPayload.state.state) {
                setAttempt(prev =>
                  prev ? { ...prev, state: snapPayload.state.state } : prev
                );
              }
              if (typeof snapPayload.state.stale === 'boolean') {
                setIsStale(snapPayload.state.stale);
              }
            }
            if (snapPayload.snapshot_seq) {
              updateSeq(snapPayload.snapshot_seq);
            }
          } else if (frame.kind === 'GAP') {
            if (frame.payload.snapshot_required) {
              setGapDetected(true);
              await refreshSnapshot();
              setGapDetected(false);
            }
          }
        } catch (parseErr) {
          console.error('Failed to parse WebSocket frame:', parseErr);
        }
      };

      ws.onerror = () => {
        if (!isMountedRef.current) return;
        setConnectionState('DEGRADED');
      };

      ws.onclose = (e) => {
        if (!isMountedRef.current) return;
        setConnectionState('DISCONNECTED');
        wsRef.current = null;

        // Controlled exponential backoff reconnect
        if (!e.wasClean) {
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
    isMountedRef.current = true;
    lastSeqRef.current = 0;
    setLastReceivedSeq(0);
    reconnectAttemptsRef.current = 0;

    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (attemptId) {
      loadInitialRestState().then(() => {
        if (isMountedRef.current) {
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
      setLoading(false);
    }

    return () => {
      isMountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [attemptId, loadInitialRestState, connectWebSocket]);

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
    refreshSnapshot,
    requestCheckpoint: requestCheckpointAction,
    abortAttempt: abortAttemptAction,
  };
}
