import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useSearchParams, Link, useNavigate, useLocation } from 'react-router-dom';
import {
  Save,
  CheckCircle2,
  X,
  Plus,
  Activity,
  MoreHorizontal,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  Wifi,
  WifiOff,
  ArrowLeft,
} from 'lucide-react';
import { useAttemptStream } from '../hooks/useAttemptStream';
import { attemptsService, workersService, stepsService, systemService, jobsService, checkpointsService } from '../api';
import { isActiveAttempt } from '../api/attempts';
import { historyReads, HISTORY_CACHE_MS, isTerminalAttempt, loadEpochHistory } from '../api/attemptHistory';
import {
  MetricItemData,
  WorkerSessionItemData,
  StepListItemData,
  CapabilitiesData,
  StepDetailData,
  AttemptListItemData,
} from '../types/api';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { PreparationStatus } from '../components/live/PreparationStatus';
import { getPreparationStatus } from '../utils/preparation';
import { DistributedTrainingFlowViz } from '../components/training/DistributedTrainingFlowViz';
import { TrainingTopologyVisualizer } from '../components/training/TrainingTopologyVisualizer';
import { ClusterIdleView } from '../components/training/ClusterIdleView';
import { StepHistoryControls } from '../components/training/StepHistoryControls';
import { FullMetricsDashboard, EpochMetricData } from '../components/charts/LiveTrainingCharts';
import { EventDetailDrawer } from '../components/drawers/EventDetailDrawer';
import { WorkerDetailDrawer } from '../components/drawers/WorkerDetailDrawer';
import { AttemptStateBadge } from '../components/common/Badge';
import { detectSlowWorkers } from '../utils/stragglerDetection';
import { toDiagnosticEvent } from '../utils/runtimeEvents';

export interface LiveTrainingPageProps {
  attemptIdOverride?: string | null;
  onBack?: () => void;
  backLabel?: string;
  defaultTab?: 'live' | 'metrics' | 'technical';
}

export const LiveTrainingPage: React.FC<LiveTrainingPageProps> = ({
  attemptIdOverride,
  onBack,
  backLabel,
  defaultTab,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const explicitAttemptId = attemptIdOverride ?? (searchParams.get('attemptId') ?? searchParams.get('attempt_id'));
  const explicitJobId = searchParams.get('jobId');

  // Attempt Resolution
  const [resolvedAttemptId, setResolvedAttemptId] = useState<string | null>(explicitAttemptId);
  const [attemptResolving, setAttemptResolving] = useState<boolean>(!explicitAttemptId);
  const [siblingAttempts, setSiblingAttempts] = useState<AttemptListItemData[]>([]);
  const [activeClusterAttempt, setActiveClusterAttempt] = useState<AttemptListItemData | null>(null);

  useEffect(() => {
    if (explicitAttemptId) {
      setResolvedAttemptId(explicitAttemptId);
      setAttemptResolving(false);
      return;
    }

    // Resolve latest running or created attempt
    const resolveAttempt = async () => {
      try {
        setAttemptResolving(true);
        if (explicitJobId) {
          const res = await attemptsService.listAttempts({ job_id: explicitJobId, limit: 1 });
          if (res.data && res.data.length > 0) {
            setResolvedAttemptId(res.data[0].attempt_id);
            return;
          }
        }
        const active = await attemptsService.getActiveAttempt();
        if (active) {
          setResolvedAttemptId(active.attempt_id);
        } else {
          setResolvedAttemptId(null);
        }
      } catch {
        setResolvedAttemptId(null);
      } finally {
        setAttemptResolving(false);
      }
    };

    resolveAttempt();
  }, [explicitAttemptId, explicitJobId]);

  useEffect(() => {
    let isMounted = true;
    attemptsService.getActiveAttempt().then(res => {
      if (isMounted) setActiveClusterAttempt(res);
    }).catch(() => {});
    return () => { isMounted = false; };
  }, [resolvedAttemptId]);

  // Realtime stream hook
  const stream = useAttemptStream(resolvedAttemptId);

  // System capabilities (protocol versions, runtime instance, supported models, feature flags)
  const [capabilities, setCapabilities] = useState<CapabilitiesData | null>(null);

  useEffect(() => {
    let isMounted = true;
    systemService
      .getCapabilities()
      .then((res) => {
        if (isMounted) setCapabilities(res.data);
      })
      .catch(() => { });
    return () => {
      isMounted = false;
    };
  }, []);

  // Drawer selected items
  const [selectedWorker, setSelectedWorker] = useState<any>(null);
  const [selectedStep, setSelectedStep] = useState<any>(null);
  const [selectedStepIndex, setSelectedStepIndex] = useState<number>(0);
  const [selectedEvent, setSelectedEvent] = useState<any>(null);

  // Step Details cache for inspected step (authoritative worker telemetry: compute_ms, upload_ms, loss, accuracy, timings)
  const [stepDetailsMap, setStepDetailsMap] = useState<Record<number, StepDetailData>>({});
  const detailsControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    detailsControllerRef.current = controller;
    setStepDetailsMap({});
    setSelectedStep(null);
    setSelectedStepIndex(0);
    setSelectedWorker(null);
    setSelectedEvent(null);
    return () => controller.abort();
  }, [resolvedAttemptId]);

  const requestStepDetail = useCallback((stepId: number, revision = 0) => {
    if (!resolvedAttemptId || (revision === 0 && stepDetailsMap[stepId])) return;
    const signal = detailsControllerRef.current?.signal;
    historyReads.read(`detail:${resolvedAttemptId}:${stepId}:${revision}`,
      sharedSignal => stepsService.getStep(resolvedAttemptId, stepId, { signal: sharedSignal }),
      signal, isTerminalAttempt(stream.attempt?.state) ? HISTORY_CACHE_MS : 0)
      .then(res => {
        if (!signal?.aborted && res.data) setStepDetailsMap(previous => ({ ...previous, [stepId]: res.data }));
      }).catch(() => {});
  }, [resolvedAttemptId, stepDetailsMap, stream.attempt?.state]);

  // Auto-fetch step details for the most recent steps so charts have full worker breakdown telemetry (compute_ms, upload_ms)
  useEffect(() => {
    if (!resolvedAttemptId || stream.steps.length === 0) return;
    let isMounted = true;
    const stepsToFetch = stream.steps.slice(0, 5).filter((s) => !stepDetailsMap[s.step_id]);
    if (stepsToFetch.length === 0) return;

    Promise.allSettled(
      stepsToFetch.map((s) => stepsService.getStep(resolvedAttemptId, s.step_id))
    ).then((results) => {
      if (!isMounted) return;
      const updates: Record<number, StepDetailData> = {};
      results.forEach((res) => {
        if (res.status === 'fulfilled' && res.value.data) {
          updates[res.value.data.step_id] = res.value.data;
        }
      });
      if (Object.keys(updates).length > 0) {
        setStepDetailsMap((prev) => ({ ...prev, ...updates }));
      }
    }).catch(() => {});

    return () => {
      isMounted = false;
    };
  }, [resolvedAttemptId, stream.steps]);

  // Epoch metrics
  const [epochMetrics, setEpochMetrics] = useState<EpochMetricData[]>([]);
  const [epochMetricsError, setEpochMetricsError] = useState<string | null>(null);
  const [epochRefresh, setEpochRefresh] = useState(0);
  const epochAttemptId = stream.attempt?.attempt_id;
  const terminalEpochHistory = isTerminalAttempt(stream.attempt?.state);
  const epochMetricsCursor = useRef({ attemptId: resolvedAttemptId, seq: 0 });

  // Track latest sequence of epoch.metrics.finalized from WS events to trigger refresh
  const latestEpochEventSeq = useMemo(() => stream.events.reduce(
    (seq, event) => event.event_type === 'epoch.metrics.finalized'
      ? Math.max(seq, event.runtime_event_seq) : seq,
    0,
  ), [stream.events]);

  useEffect(() => {
    epochMetricsCursor.current = { attemptId: resolvedAttemptId, seq: 0 };
    setEpochMetrics([]);
    setEpochMetricsError(null);
  }, [resolvedAttemptId]);

  const fetchEpochMetrics = useCallback(async (signal: AbortSignal) => {
    if (!resolvedAttemptId || epochAttemptId !== resolvedAttemptId) {
      setEpochMetrics([]);
      return;
    }
    try {
      setEpochMetricsError(null);
      const cursor = epochMetricsCursor.current.attemptId === resolvedAttemptId
        ? epochMetricsCursor.current.seq : 0;
      const { events: allEvents, cursor: afterSeq } = await loadEpochHistory(resolvedAttemptId, cursor, signal, terminalEpochHistory);
      const epochMap = new Map<number, EpochMetricData>();
      for (const ev of allEvents) {
        const d = ev.details as any;
        if (d && typeof d.epoch_index === 'number') {
          epochMap.set(d.epoch_index, {
            epoch_index: d.epoch_index,
            sample_count: d.sample_count ?? 0,
            training_loss: d.training_loss ?? null,
            training_accuracy: d.training_accuracy ?? null,
          });
        }
      }
      if (!signal.aborted) {
        epochMetricsCursor.current = { attemptId: resolvedAttemptId, seq: afterSeq };
        setEpochMetrics(previous => {
          const merged = new Map<number, EpochMetricData>(previous.map(metric => [metric.epoch_index, metric]));
          for (const [epoch, metric] of epochMap) merged.set(epoch, metric);
          return Array.from(merged.values()).sort((a, b) => a.epoch_index - b.epoch_index);
        });
      }
    } catch {
      if (!signal.aborted) setEpochMetricsError('Không thể tải metrics theo epoch.');
    }
  }, [resolvedAttemptId, epochAttemptId, terminalEpochHistory]);

  useEffect(() => {
    const controller = new AbortController();
    fetchEpochMetrics(controller.signal);
    return () => controller.abort();
  }, [fetchEpochMetrics, latestEpochEventSeq, epochRefresh]);

  const attempt = stream.attempt;

  // UI state
  const requestedTab = defaultTab || (searchParams.get('tab') as 'live' | 'metrics') || null;
  const [activeTab, setActiveTab] = useState<'live' | 'metrics'>(
    requestedTab || 'live'
  );

  const visibleLiveStepId = activeTab === 'live' && !stream.steps[0]?.timing
    ? stream.steps[0]?.step_id : undefined;
  useEffect(() => {
    if (visibleLiveStepId != null && epochAttemptId === resolvedAttemptId) requestStepDetail(visibleLiveStepId);
  }, [visibleLiveStepId, epochAttemptId, resolvedAttemptId, requestStepDetail]);

  useEffect(() => {
    if (requestedTab) {
      setActiveTab(requestedTab);
    } else if (attempt && (attempt.state === 'COMPLETED' || attempt.state === 'FAILED' || attempt.state === 'ABORTED')) {
      setActiveTab('metrics');
    }
  }, [requestedTab, attempt?.state]);
  const [isAbortModalOpen, setIsAbortModalOpen] = useState(false);
  const [showDetailedSyncModal, setShowDetailedSyncModal] = useState(false);
  const [isOverflowOpen, setIsOverflowOpen] = useState(false);
  const [jobDetail, setJobDetail] = useState<import('../types/api').JobDetailData | null>(null);
  const [jobDisplayName, setJobDisplayName] = useState<string | null>(null);

  const [recoveryInfo, setRecoveryInfo] = useState<{
    status: 'idle' | 'checking' | 'verified_final' | 'final_failed' | 'no_checkpoint' | 'unverified';
    lastIndexedEpoch?: number;
    checkpointId?: string;
  }>({ status: 'idle' });

  // Resolve Job Display Name
  useEffect(() => {
    setJobDetail(null);
    setJobDisplayName(null);
    if (!attempt?.job_id) return;
    let isMounted = true;
    jobsService.getJob(attempt.job_id)
      .then(res => {
        if (isMounted && res.data?.display_name) {
          setJobDisplayName(res.data.display_name);
          setJobDetail(res.data);
        }
      })
      .catch(() => {
        // Fallback
      });
    attemptsService.listAttempts({ job_id: attempt.job_id, limit: 20 })
      .then(res => {
        if (isMounted) setSiblingAttempts(res.data || []);
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, [attempt?.job_id]);
  const snapshot = stream.snapshot;
  const workers = stream.workers;
  const steps = stream.steps;
  const events = stream.events;
  const diagnosticEvents = useMemo(() => events.map(toDiagnosticEvent), [events]);
  const activeStep = steps[0];

  // Verify checkpoint lineage when training run COMPLETED
  useEffect(() => {
    if (!attempt || attempt.state !== 'COMPLETED') {
      setRecoveryInfo({ status: 'idle' });
      return;
    }

    const finalFailedInMeta = Boolean(attempt.runtime_metadata?.final_checkpoint_failed);
    const finalFailedInEvents = events.some(
      (e) => e.event_type === 'checkpoint.failed' && (e.details?.is_final || e.details?.final)
    );
    const isFinalFailed = finalFailedInMeta || finalFailedInEvents;

    let isMounted = true;
    setRecoveryInfo({ status: 'checking' });

    // Fetch COMPLETE checkpoints for THIS attempt only (lineage safety: do not cross to unrelated attempts)
    checkpointsService
      .listCheckpoints({ attempt_id: attempt.attempt_id, state: 'COMPLETE', limit: 1 })
      .then(async (res) => {
        if (!isMounted) return;
        const currentAttemptComplete = res.data?.[0];

        if (currentAttemptComplete) {
          try {
            const detailRes = await checkpointsService.getCheckpoint(currentAttemptComplete.checkpoint_id);
            if (!isMounted) return;
            const cursorEpoch = detailRes.data?.recovery_cursor?.epoch;
            const totalEpochs =
              jobDetail?.resolved_contract?.training?.epochs ??
              jobDetail?.requested_contract?.epochs ??
              attempt.epoch;

            if (!totalEpochs || cursorEpoch === undefined) {
              setRecoveryInfo({ status: 'unverified' });
            } else if (isFinalFailed || cursorEpoch !== totalEpochs) {
              setRecoveryInfo({
                status: 'final_failed',
                lastIndexedEpoch: cursorEpoch,
                checkpointId: currentAttemptComplete.checkpoint_id,
              });
            } else {
              setRecoveryInfo({ status: 'verified_final' });
            }
          } catch {
            if (isMounted) setRecoveryInfo({ status: 'unverified' });
          }
        } else if (attempt.resume_from_checkpoint_id) {
          try {
            const sourceDetail = await checkpointsService.getCheckpoint(attempt.resume_from_checkpoint_id);
            if (!isMounted) return;
            const cursorEpoch = sourceDetail.data?.recovery_cursor?.epoch;
            setRecoveryInfo({
              status: 'final_failed',
              lastIndexedEpoch: cursorEpoch,
              checkpointId: attempt.resume_from_checkpoint_id,
            });
          } catch {
            if (isMounted) setRecoveryInfo({ status: 'unverified' });
          }
        } else {
          if (isFinalFailed) {
            setRecoveryInfo({ status: 'no_checkpoint' });
          } else {
            setRecoveryInfo({ status: 'unverified' });
          }
        }
      })
      .catch(() => {
        if (isMounted) setRecoveryInfo({ status: 'unverified' });
      });

    return () => {
      isMounted = false;
    };
  }, [attempt?.attempt_id, attempt?.state, attempt?.runtime_metadata, attempt?.resume_from_checkpoint_id, events, jobDetail]);

  const handleRequestCheckpoint = async () => {
    try {
      await stream.requestCheckpoint('manual');
    } catch (err: any) {
      alert(`Checkpoint request failed: ${err?.message || 'Unknown error'}`);
    }
  };

  const TERMINAL_STATES = new Set(['COMPLETED', 'FAILED', 'ABORTED', 'CANCELLED']);
  const isTerminal = attempt ? TERMINAL_STATES.has(attempt.state) : false;

  const handleConfirmAbort = async () => {
    try {
      await stream.abortAttempt('Operator aborted training run');
      setIsAbortModalOpen(false);
      // Force a REST refresh so UI reflects the new state immediately,
      // without depending on a WebSocket push (WS closes quickly on CREATED attempts).
      await stream.refreshSnapshot();
    } catch (err: any) {
      alert(`Failed to abort attempt: ${err?.message || 'Unknown error'}`);
    }
  };


  // Authoritative expected and observed worker counts
  const expectedWorkersCount = attempt?.expected_workers ?? attempt?.membership?.expected_workers ?? null;
  const observedWorkersCount = workers.length;
  const preparation = getPreparationStatus(attempt?.state, workers);

  // Adapter for subcomponents expecting legacy shapes (memoized to eliminate cascade re-renders)
  const legacyAttemptAdapter = useMemo<any>(() => attempt ? ({
    id: attempt.attempt_id,
    jobId: attempt.job_id,
    jobName: attempt.job_id,
    state: attempt.state,
    executionMode: attempt.execution_mode,
    epoch: snapshot?.epoch ?? attempt.epoch ?? 0,
    totalEpochs: jobDetail?.resolved_contract?.training.epochs ?? jobDetail?.requested_contract.epochs,
    currentBatch: snapshot?.current_batch_ordinal ?? attempt.progress_cursor?.next_batch_ordinal ?? 0,
    totalBatches: 0,
    activeWorkers: workers.filter(w => w.state === 'READY' || w.state === 'INITIALIZING' || w.state === 'RUNNING').length,
    expectedWorkers: expectedWorkersCount ?? 0,
    modelVersion: snapshot?.model_version !== null && snapshot?.model_version !== undefined
      ? `v${snapshot.model_version}`
      : (attempt.model_version !== null && attempt.model_version !== undefined ? `v${attempt.model_version}` : 'v—'),
    datasetBuildId: jobDetail?.resolved_contract?.dataset.dataset_build_id ?? jobDetail?.requested_contract.dataset_build_id ?? '—',
    elapsedFormatted: attempt.started_at ? 'Active run' : 'Pending',
    runtimeEventSeq: stream.lastReceivedSeq,
  }) : null, [attempt, snapshot, jobDetail, workers, expectedWorkersCount, stream.lastReceivedSeq]);

  const legacyWorkersAdapter = useMemo<any[]>(() => workers.map(w => ({
    workerId: w.worker_id,
    sessionId: w.session_id,
    nodeLabel: w.node_label || `node-${w.worker_id}`,
    state: w.state,
    assignedShard: w.shard_id !== null && w.shard_id !== undefined ? `shard-${w.shard_id}` : 'Unassigned',
    currentModelVersion: w.local_model_version !== null && w.local_model_version !== undefined
      ? w.local_model_version
      : (attempt?.model_version ?? null),
    protocolVersion: w.protocol_version ? `dtp/v${w.protocol_version}` : 'dtp/v1',
    connectedAt: w.connected_at,
    lastHeartbeatMs: w.last_heartbeat_at ? Math.max(0, Math.round(Date.now() - new Date(w.last_heartbeat_at).getTime())) : null,
  })), [workers, attempt?.model_version]);

  const legacyStepsAdapter = useMemo<any[]>(() => steps.map((st) => {
    const detail = stepDetailsMap[st.step_id];
    const workerSteps = st.worker_steps ?? detail?.worker_steps;
    const workerContributions =
      workerSteps && workerSteps.length > 0
        ? workerSteps.map((ws) => ({
          workerId: ws.worker_id,
          sessionId: ws.session_id,
          shardId: ws.shard_id,
          batchId: ws.batch_id,
          sampleCount: ws.sample_count,
          samples: ws.sample_count,
          contributionAccepted: typeof ws.contribution_accepted === 'boolean' ? ws.contribution_accepted : undefined,
          parameterApplied: typeof ws.parameter_applied === 'boolean' ? ws.parameter_applied : undefined,
          loss: ws.loss,
          accuracy: ws.accuracy,
          computeMs: ws.compute_ms,
          uploadMs: ws.upload_ms,
          parameterApplyMs: ws.parameter_apply_ms,
          bytesSent: ws.bytes_sent,
          bytesReceived: ws.bytes_received,
        }))
        : [];

    const timing = st.timing ?? detail?.timing;
    const totalDurationMs =
      timing?.started_at && timing?.committed_at
        ? Math.max(0, new Date(timing.committed_at).getTime() - new Date(timing.started_at).getTime())
        : undefined;

    return {
      stepId: st.step_id,
      operationId: st.operation_id,
      epoch: st.epoch,
      batchOrdinal: st.batch_ordinal,
      state: st.state,
      inputModelVersion: st.input_model_version,
      outputModelVersion: st.output_model_version,
      totalSampleCount: st.total_sample_count,
      loss: st.metrics?.loss ?? detail?.metrics?.loss ?? null,
      accuracy: st.metrics?.accuracy ?? detail?.metrics?.accuracy ?? null,
      metrics: st.metrics ?? detail?.metrics ?? null,
      timings: {
        startedAt: timing?.started_at || (st.committed_at ? 'Committed' : 'In progress'),
        committedAt: timing?.committed_at || st.committed_at || undefined,
        updateCompletedAt: timing?.update_completed_at,
        synchronizationCompletedAt: timing?.synchronization_completed_at,
        checkpointCompletedAt: timing?.checkpoint_completed_at,
        totalDurationMs,
      },
      workerContributions,
    };
  }), [steps, stepDetailsMap]);

  const slowWorkersMap = useMemo(() => detectSlowWorkers(legacyStepsAdapter), [legacyStepsAdapter]);

  const currentViewStep = legacyStepsAdapter[selectedStepIndex] || legacyStepsAdapter[0];
  const inspectedStepId = currentViewStep?.stepId ?? currentViewStep?.operationId ?? selectedStep?.stepId ?? selectedStep?.operationId;
  const inspectedStepEventSeq = useMemo(() => stream.events.reduce((latest, event) => {
    const relevant = event.event_type === 'model.updated' || event.event_type === 'step.committed'
      || event.event_type.startsWith('checkpoint.');
    return relevant && (event.details.step_id ?? event.details.source_step_id) === inspectedStepId
      ? Math.max(latest, event.runtime_event_seq) : latest;
  }, 0), [stream.events, inspectedStepId]);
  useEffect(() => {
    if (!resolvedAttemptId || inspectedStepId === undefined) return;
    requestStepDetail(inspectedStepId, inspectedStepEventSeq);
  }, [resolvedAttemptId, inspectedStepId, inspectedStepEventSeq, requestStepDetail]);

  if (attemptResolving || (stream.loading && !attempt)) {
    return (
      <div className="w-full py-20 flex flex-col items-center justify-center text-center font-sans select-none text-xs text-[#73737c] gap-3">
        <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
        <span>{activeTab === 'metrics' || (attempt && (attempt.state === 'COMPLETED' || attempt.state === 'FAILED' || attempt.state === 'ABORTED'))
          ? 'Đang tải kết quả và chỉ số huấn luyện...'
          : 'Đang kết nối luồng huấn luyện...'}</span>
      </div>
    );
  }

  if (!resolvedAttemptId || !attempt) {
    return <ClusterIdleView />;
  }

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Final Checkpoint Failure Persistent Warning */}
      {attempt.state === 'COMPLETED' && recoveryInfo.status === 'final_failed' && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-200 space-y-2">
          <div className="flex items-center gap-2 font-semibold text-amber-300">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Huấn luyện hoàn thành nhưng checkpoint cuối cùng lưu không thành công.</span>
          </div>
          {recoveryInfo.lastIndexedEpoch !== undefined && recoveryInfo.lastIndexedEpoch > 0 ? (
            <p className="text-amber-200/90 leading-relaxed">
              Mốc khôi phục khả dụng gần nhất trong chuỗi thực thi: <strong>cuối epoch {recoveryInfo.lastIndexedEpoch}</strong> (tiếp tục từ <strong>epoch {recoveryInfo.lastIndexedEpoch + 1}</strong>).
            </p>
          ) : (
            <p className="text-amber-200/90 leading-relaxed">
              Mốc khôi phục khả dụng: Checkpoint ID <span className="font-mono text-amber-300">{recoveryInfo.checkpointId}</span>.
            </p>
          )}
          {recoveryInfo.checkpointId && (
            <div className="flex items-center gap-3 pt-1">
              <span className="font-mono text-[11px] text-amber-300/80">
                Checkpoint: {recoveryInfo.checkpointId}
              </span>
              <Link
                to="/checkpoints"
                className="px-2.5 py-1 bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded border border-amber-500/30 transition-colors"
              >
                Xem danh sách checkpoint
              </Link>
            </div>
          )}
        </div>
      )}

      {attempt.state === 'COMPLETED' && recoveryInfo.status === 'no_checkpoint' && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-200 space-y-1.5">
          <div className="flex items-center gap-2 font-semibold text-amber-300">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>Huấn luyện hoàn thành nhưng checkpoint cuối cùng lưu không thành công.</span>
          </div>
          <p className="text-amber-200/90">
            Không có điểm khôi phục khả dụng trong chuỗi thực thi này.
          </p>
        </div>
      )}

      {attempt.state === 'COMPLETED' && recoveryInfo.status === 'unverified' && (
        <div className="p-3 bg-zinc-800/80 border border-white/[0.08] rounded text-xs text-[#a1a1a8] flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-[#73737c] shrink-0" />
          <span>Chưa xác minh được mốc khôi phục từ backend.</span>
        </div>
      )}

      {/* Gap / Stale Warnings */}
      {stream.gapDetected && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded flex items-center gap-2 text-xs text-amber-300">
          <AlertTriangle className="w-4 h-4 text-amber-400 animate-spin" />
          <span>Gap detected in event stream. Reconciling authoritative snapshot from server...</span>
        </div>
      )}

      {stream.isStale && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded flex items-center justify-between text-xs text-amber-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-400" />
            <span>Runtime telemetry snapshot is stale. State may not reflect current worker progress.</span>
          </div>
          <button
            type="button"
            onClick={() => stream.refreshSnapshot()}
            className="px-2 py-1 bg-amber-500/20 hover:bg-amber-500/30 rounded text-amber-200 transition-colors"
          >
            Refresh Snapshot
          </button>
        </div>
      )}

      {/* Banner if cluster has an active run and user is viewing an older/completed attempt */}
      {activeClusterAttempt && activeClusterAttempt.attempt_id !== attempt.attempt_id && isActiveAttempt(activeClusterAttempt.state) && (
        <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded flex items-center justify-between text-xs text-blue-300">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Cụm đang có một phiên huấn luyện đang hoạt động trực tiếp.</span>
          </div>
          <Link
            to={`/live?attempt_id=${encodeURIComponent(activeClusterAttempt.attempt_id)}`}
            className="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-medium transition-colors"
          >
            Chuyển tới phiên Live
          </Link>
        </div>
      )}

      {/* Back button if embedded in JobDetailPage or TrainingRunsPage */}
      {onBack && (
        <div className="pb-1">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>{backLabel || 'Quay lại'}</span>
          </button>
        </div>
      )}

      {/* Page Header */}
      <div className="space-y-2 pb-3 border-b border-white/[0.07]">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-base font-semibold text-[#f3f3f4]">
                {jobDisplayName || 'Tiến trình Huấn luyện'}
              </h1>
              <AttemptStateBadge state={attempt.state} />

              {/* Sibling runs selector */}
              {siblingAttempts.length > 1 && (
                <div className="relative inline-flex items-center">
                  <select
                    value={attempt.attempt_id}
                    onChange={(e) => {
                      if (e.target.value) {
                        if (location.pathname.startsWith('/jobs/')) {
                          navigate(`${location.pathname}?attempt_id=${encodeURIComponent(e.target.value)}`);
                        } else if (location.pathname.startsWith('/runs')) {
                          navigate(`/runs?attempt_id=${encodeURIComponent(e.target.value)}`);
                        } else {
                          navigate(`/live?attempt_id=${encodeURIComponent(e.target.value)}`);
                        }
                      }
                    }}
                    className="bg-[#171719] border border-white/[0.08] text-[#f3f3f4] text-xs rounded px-2 py-0.5 outline-none focus:border-blue-500 cursor-pointer"
                  >
                    {siblingAttempts.map((sAtt, idx) => {
                      const num = siblingAttempts.length - idx;
                      return (
                        <option key={sAtt.attempt_id} value={sAtt.attempt_id}>
                          Lần chạy #{num} ({sAtt.state})
                        </option>
                      );
                    })}
                  </select>
                </div>
              )}

              {stream.connectionState === 'RECONNECTING' && (
                <span className="inline-flex items-center gap-1.5 text-[11px] text-amber-400 font-mono animate-pulse">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  <span>Reconnecting...</span>
                </span>
              )}
              {stream.connectionState === 'DEGRADED' && (
                <span className="inline-flex items-center gap-1.5 text-[11px] text-rose-400 font-mono">
                  <WifiOff className="w-3 h-3 text-rose-400" />
                  <span>Stream Degraded</span>
                </span>
              )}
              {stream.connectionState === 'DISCONNECTED' && (
                <span className="inline-flex items-center gap-1.5 text-[11px] text-[#73737c] font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#73737c]" />
                  <span>Disconnected</span>
                </span>
              )}
            </div>

            {/* Sub-header: Only Model Name (remove redundant metadata) */}
            {(() => {
              const modelId = jobDetail?.resolved_contract?.model.model_id
                ?? jobDetail?.requested_contract.model_id ?? attempt.model_id;
              const modelInfo =
                capabilities?.supported_models?.find((m) => m.model_id === modelId);
              const modelDisplayName =
                modelInfo?.display_name || modelId || '—';

              return (
                <div className="text-xs text-[#a1a1a8]">
                  <span>{modelDisplayName}</span>
                </div>
              );
            })()}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 self-start sm:self-center">
            {(() => {
              const manualCheckpointAllowed =
                capabilities?.feature_flags?.manual_checkpoint_request !== false;
              return (
                <button
                  type="button"
                  onClick={handleRequestCheckpoint}
                  disabled={attempt.state !== 'RUNNING' || !manualCheckpointAllowed}
                  title={
                    !manualCheckpointAllowed
                      ? 'Manual checkpoint disabled by system capabilities'
                      : 'Trigger immediate checkpoint'
                  }
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] text-xs font-normal transition-colors border border-white/[0.07] disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Save className="w-3.5 h-3.5 text-[#73737c]" />
                  <span>Checkpoint</span>
                </button>
              );
            })()}

            {/* Overflow Menu */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsOverflowOpen(prev => !prev)}
                className="p-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.07] transition-colors"
                title="More actions"
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>

              {isOverflowOpen && (
                <div
                  className="absolute right-0 top-full mt-1 w-44 bg-[#121214] border border-white/[0.1] rounded shadow-xl py-1 z-40 text-xs"
                  onMouseLeave={() => setIsOverflowOpen(false)}
                >
                  <Link
                    to={`/jobs/${attempt.job_id}`}
                    className="flex items-center px-3 py-1.5 text-[#a1a1a8] hover:text-[#f3f3f4] hover:bg-white/[0.04]"
                    onClick={() => setIsOverflowOpen(false)}
                  >
                    View job
                  </Link>
                  <Link
                    to="/checkpoints"
                    className="flex items-center px-3 py-1.5 text-[#a1a1a8] hover:text-[#f3f3f4] hover:bg-white/[0.04]"
                    onClick={() => setIsOverflowOpen(false)}
                  >
                    View checkpoints
                  </Link>
                  <div className="h-px bg-white/[0.07] my-1" />
                  <button
                    type="button"
                    disabled={isTerminal}
                    onClick={() => {
                      setIsOverflowOpen(false);
                      setIsAbortModalOpen(true);
                    }}
                    className="w-full text-left px-3 py-1.5 text-rose-400 hover:bg-rose-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
                    title={isTerminal ? `Attempt already ${attempt?.state}` : 'Abort this training run'}
                  >
                    {isTerminal ? `Already ${attempt?.state?.toLowerCase()}` : 'Abort training'}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Tab Controls */}
        <div className="flex items-center gap-1.5 pt-1 text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('live')}
            className={`px-3 py-1 rounded transition-colors ${activeTab === 'live'
              ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
              : 'text-[#73737c] hover:text-[#f3f3f4]'
              }`}
          >
            Live
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('metrics')}
            className={`px-3 py-1 rounded transition-colors ${activeTab === 'metrics'
              ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
              : 'text-[#73737c] hover:text-[#f3f3f4]'
              }`}
          >
            Metrics
          </button>
        </div>
      </div>

      {/* TAB 1: LIVE */}
      {activeTab === 'live' && (
        <div className="space-y-4">
          <PreparationStatus state={attempt.state} workers={workers}
            expectedWorkers={expectedWorkersCount} isStale={stream.isStale}
            observedAt={snapshot?.observed_at} />
          <TrainingTopologyVisualizer
            currentStep={legacyStepsAdapter[0]}
            workers={legacyWorkersAdapter}
            expectedWorkers={expectedWorkersCount ?? 0}
            attempt={legacyAttemptAdapter}
            strategyState={snapshot?.strategy_state || attempt.strategy_state || null}
            isStale={stream.isStale}
            onSelectWorker={setSelectedWorker}
            epochMetrics={epochMetrics}
            jobDisplayName={jobDisplayName}
            totalEpochs={
              jobDetail?.resolved_contract?.training?.epochs ||
              jobDetail?.requested_contract?.epochs ||
              attempt.runtime_metadata?.epochs ||
              10
            }
            stepsHistory={steps}
            snapshot={snapshot}
          />

                {/* UNIFIED CLUSTER WORKLOAD & WORKER SYNCHRONIZATION PANEL */}
                <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-4">
                  {/* 1. TOP HEADER: Title, Strategy & Step Navigation Controls */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <h3 className="text-xs font-semibold text-[#f3f3f4]">
                        Điều phối Khối lượng &amp; Đồng bộ Worker
                      </h3>
                      {(() => {
                        const policy =
                          jobDetail?.resolved_contract?.workload?.policy ||
                          jobDetail?.requested_contract?.workload?.policy ||
                          (attempt as any)?.runtime_metadata?.workload_policy ||
                          'strict_bsp';
                        return policy === 'dbs' ? (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20" title="Adaptive DBS: Phân bổ số mẫu động thích ứng theo tốc độ xử lý thực tế của từng worker">
                            Adaptive DBS
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-zinc-800 text-zinc-400 border border-white/[0.06]" title="Equal Policy: Các worker nhận số mẫu bằng nhau">
                            Equal BSP
                          </span>
                        );
                      })()}

                      {currentViewStep && (
                        <div className="flex items-center gap-2 text-xs">
                          {currentViewStep.state === 'COMMITTED' ? (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                              COMMITTED
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-blue-500/10 text-blue-400 border border-blue-500/20 inline-flex items-center gap-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                              <span>IN PROGRESS</span>
                            </span>
                          )}
                          <span className="text-[#a1a1a8] text-xs">
                            Epoch {currentViewStep.epoch} (b#{currentViewStep.batchOrdinal})
                          </span>
                          <span className="text-[#73737c]">·</span>
                          <span className="text-[#a1a1a8] font-mono text-[11px]">
                            v{currentViewStep.inputModelVersion} → {currentViewStep.outputModelVersion != null ? `v${currentViewStep.outputModelVersion}` : `v${Number(currentViewStep.inputModelVersion) + 1}`}
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Step Navigation Controls directly on the panel */}
                    {legacyStepsAdapter.length > 1 && (
                      <div className="flex items-center gap-2 self-start sm:self-auto">
                        {selectedStepIndex > 0 && (
                          <button
                            type="button"
                            onClick={() => setSelectedStepIndex(0)}
                            className="px-2 py-1 text-[11px] rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/20 transition-colors cursor-pointer"
                          >
                            Về bước mới nhất
                          </button>
                        )}
                        <div className="inline-flex items-center rounded border border-white/[0.08] bg-[#171719] text-xs">
                          <button
                            type="button"
                            onClick={() => setSelectedStepIndex(prev => Math.min(legacyStepsAdapter.length - 1, prev + 1))}
                            disabled={selectedStepIndex >= legacyStepsAdapter.length - 1}
                            className="px-2.5 py-1 text-[#a1a1a8] hover:text-[#f3f3f4] disabled:opacity-30 disabled:hover:text-[#a1a1a8] transition-colors cursor-pointer"
                            title="Bước trước"
                          >
                            ← Trước
                          </button>
                          <span className="px-2.5 py-1 text-[#f3f3f4] font-mono font-medium border-x border-white/[0.06]">
                            Bước #{currentViewStep?.operationId ?? '—'}
                          </span>
                          <button
                            type="button"
                            onClick={() => setSelectedStepIndex(prev => Math.max(0, prev - 1))}
                            disabled={selectedStepIndex <= 0}
                            className="px-2.5 py-1 text-[#a1a1a8] hover:text-[#f3f3f4] disabled:opacity-30 disabled:hover:text-[#a1a1a8] transition-colors cursor-pointer"
                            title="Bước sau"
                          >
                            Sau →
                          </button>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Partial projection warning if session count < expected */}
                  {expectedWorkersCount != null && observedWorkersCount < expectedWorkersCount && (
                    <div className="p-2 bg-amber-500/10 border border-amber-500/20 rounded flex items-center gap-2 text-[11px] text-amber-300">
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                      <span>
                        Partial projection: {observedWorkersCount} of {expectedWorkersCount} expected worker sessions observed from API.
                      </span>
                    </div>
                  )}

                  {/* 2. INLINE STATS ROW & WORKER TABLE */}
                  {(() => {
                    const currentContribs = currentViewStep?.workerContributions || [];
                    const total = currentViewStep?.totalSampleCount || currentContribs.reduce((sum: number, c: any) => sum + (c.sampleCount || 0), 0);
                    const totalExpected = expectedWorkersCount ?? workers.length;
                    const observedMap = new Map<number, any>();
                    workers.forEach(w => observedMap.set(Number(w.worker_id), w));

                    const workerBgClasses = ['bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-purple-500', 'bg-cyan-500', 'bg-pink-500'];

                    const validComputes = currentContribs.map((c: any) => c.computeMs).filter((v: any) => typeof v === 'number');
                    const avgComputeMs = validComputes.length > 0 ? validComputes.reduce((a: number, b: number) => a + b, 0) / validComputes.length : null;

                    const validUploads = currentContribs.map((c: any) => c.uploadMs).filter((v: any) => typeof v === 'number');
                    const avgUploadMs = validUploads.length > 0 ? validUploads.reduce((a: number, b: number) => a + b, 0) / validUploads.length : null;

                    const stepDurationMs = currentViewStep?.timings?.totalDurationMs;

                    return (
                      <div className="space-y-4">
                        {/* 4 Clean Stats from Telemetry Drawer, directly displayed inline */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                          <div className="bg-[#171719] rounded p-3 border border-white/[0.04]">
                            <div className="text-[11px] text-[#73737c]">Thời gian chu kỳ bước</div>
                            <div className="mt-1 font-mono text-blue-400 font-semibold text-sm">
                              {stepDurationMs != null ? `${stepDurationMs} ms` : '—'}
                            </div>
                          </div>
                          <div className="bg-[#171719] rounded p-3 border border-white/[0.04]">
                            <div className="text-[11px] text-[#73737c]">Tính toán TB (Compute)</div>
                            <div className="mt-1 font-mono text-amber-400 font-semibold text-sm">
                              {avgComputeMs != null ? `${avgComputeMs.toFixed(1)} ms` : '—'}
                            </div>
                          </div>
                          <div className="bg-[#171719] rounded p-3 border border-white/[0.04]">
                            <div className="text-[11px] text-[#73737c]">Truyền tải TB (Upload)</div>
                            <div className="mt-1 font-mono text-emerald-400 font-semibold text-sm">
                              {avgUploadMs != null ? `${avgUploadMs.toFixed(1)} ms` : '—'}
                            </div>
                          </div>
                          <div className="bg-[#171719] rounded p-3 border border-white/[0.04]">
                            <div className="text-[11px] text-[#73737c]">Tổng mẫu xử lý</div>
                            <div className="mt-1 font-mono text-[#f3f3f4] font-semibold text-sm">
                              {total ? `${total} mẫu` : '—'}
                            </div>
                          </div>
                        </div>

                        {/* Integrated Slim Workload Distribution Indicator */}
                        {total > 0 && currentContribs.length > 0 && (
                          <div className="space-y-1.5">
                            <div className="flex items-center justify-between text-[11px] text-[#73737c]">
                              <span>Phân bổ số mẫu bước #{currentViewStep?.operationId}</span>
                              <span className="font-mono text-[#f3f3f4] font-medium">Tổng: {total} mẫu · {currentContribs.length} workers</span>
                            </div>
                            <div className="w-full h-1.5 rounded-full bg-white/[0.06] overflow-hidden flex gap-0.5">
                              {currentContribs.map((c: any) => {
                                const samples = c.sampleCount ?? c.samples ?? 0;
                                const pct = total > 0 ? (samples / total) * 100 : 0;
                                const color = workerBgClasses[c.workerId % workerBgClasses.length];
                                return (
                                  <div
                                    key={c.workerId}
                                    style={{ width: `${pct}%` }}
                                    className={`${color} h-full transition-all`}
                                    title={`Worker ${c.workerId}: ${samples} mẫu (${Math.round(pct * 10) / 10}%)`}
                                  />
                                );
                              })}
                            </div>
                          </div>
                        )}

                        {/* Simplified Clean Worker Table */}
                        <div className="overflow-x-auto rounded border border-white/[0.06] bg-[#141416]">
                          <table className="w-full text-left text-xs">
                            <thead>
                              <tr className="border-b border-white/[0.06] text-[#73737c] text-[11px] bg-[#171719]/80">
                                <th className="py-2.5 px-3 font-medium">Worker / Node</th>
                                <th className="py-2.5 px-3 font-medium">Tải DBS (Mẫu)</th>
                                <th className="py-2.5 px-3 font-medium">Tính toán (Compute)</th>
                                <th className="py-2.5 px-3 font-medium">Truyền tải (Upload)</th>
                                <th className="py-2.5 px-3 font-medium text-right">Cổng đóng góp</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-white/[0.04]">
                              {Array.from({ length: totalExpected }).map((_, id) => {
                                const w = observedMap.get(id);
                                if (w) {
                                  const telemetry = slowWorkersMap.get(id);
                                  const computeTime = telemetry?.currentComputeMs ?? telemetry?.medianComputeMs;
                                  const isSlow = Boolean(telemetry?.isSlow);

                                  // DBS Workload allocation for this worker in current step
                                  const workerContrib = currentContribs.find((c: any) => c.workerId === id);
                                  const workerSamples = workerContrib?.sampleCount ?? workerContrib?.samples;
                                  const workloadPct = total > 0 && workerSamples != null ? Math.round((workerSamples / total) * 1000) / 10 : null;
                                  const uploadMs = workerContrib?.uploadMs;
                                  const color = workerBgClasses[id % workerBgClasses.length];

                                  return (
                                    <tr key={id} className="hover:bg-[#171719]/60 transition-colors">
                                      {/* Worker / Node */}
                                      <td className="py-2.5 px-3">
                                        <div className="flex items-center gap-2">
                                          <span className={`w-2 h-2 rounded-full ${color} shrink-0`} />
                                          <div className="min-w-0">
                                            <div className="font-medium text-[#f3f3f4]">
                                              Worker {id}
                                            </div>
                                            <div className="text-[10px] text-[#73737c] font-mono truncate max-w-[140px]">
                                              {w.node_label || `node-${id}`}
                                            </div>
                                          </div>
                                        </div>
                                      </td>

                                      {/* Tải DBS (Mẫu) */}
                                      <td className="py-2.5 px-3">
                                        {workerSamples != null ? (
                                          <div className="flex items-center gap-2">
                                            <div className="w-12 h-1.5 rounded-full bg-white/[0.06] overflow-hidden shrink-0">
                                              <div
                                                className={`${color} h-full rounded-full`}
                                                style={{ width: `${Math.min(100, Math.max(0, workloadPct || 0))}%` }}
                                              />
                                            </div>
                                            <span className="font-mono text-[#f3f3f4] text-xs font-medium">
                                              {workerSamples} mẫu
                                            </span>
                                            {workloadPct != null && (
                                              <span className="text-[10px] text-[#73737c] font-mono">
                                                ({workloadPct}%)
                                              </span>
                                            )}
                                          </div>
                                        ) : (
                                          <span className="text-[#73737c] font-mono text-[11px]">—</span>
                                        )}
                                      </td>

                                      {/* Tính toán (Compute) */}
                                      <td className="py-2.5 px-3">
                                        <div className="flex items-center gap-1.5 font-mono text-xs">
                                          {workerContrib?.computeMs != null ? (
                                            <span className="text-[#f3f3f4]">{Math.round(workerContrib.computeMs)}ms</span>
                                          ) : computeTime != null ? (
                                            <span className="text-[#f3f3f4]">{Math.round(computeTime)}ms</span>
                                          ) : (
                                            <span className="text-[#73737c]">—</span>
                                          )}
                                          {isSlow && (
                                            <span
                                              data-testid={`slow-badge-worker-${id}`}
                                              className="px-1.5 py-0.2 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40 inline-flex items-center"
                                              title={`Compute straggler detected: median compute time (${Math.round(telemetry?.medianComputeMs || computeTime)}ms) > 1.5x group median`}
                                            >
                                              Slow
                                            </span>
                                          )}
                                        </div>
                                      </td>

                                      {/* Đẩy tensor (Upload) */}
                                      <td className="py-2.5 px-3 font-mono text-xs text-[#a1a1a8]">
                                        {uploadMs != null && uploadMs > 0 ? `${Math.round(uploadMs)}ms` : '—'}
                                      </td>

                                      {/* Cổng đóng góp */}
                                      <td className="py-2.5 px-3 text-right">
                                        {workerContrib?.contributionAccepted === true ? (
                                          <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-mono">
                                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                                            <span>Đã nhận</span>
                                          </span>
                                        ) : workerContrib?.contributionAccepted === false ? (
                                          <span className="inline-flex items-center gap-1 text-[11px] text-amber-400 font-mono">
                                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                                            <span>Đang chờ</span>
                                          </span>
                                        ) : (
                                          <span className="text-[#73737c] font-mono text-[11px]">—</span>
                                        )}
                                      </td>
                                    </tr>
                                  );
                                } else {
                                  return (
                                    <tr key={id} className="opacity-60 bg-[#171719]/20">
                                      <td className="py-2.5 px-3">
                                        <div className="flex items-center gap-2">
                                          <span className="w-2 h-2 rounded-full bg-zinc-600 shrink-0" />
                                          <span className="font-medium text-[#73737c]">Worker {id}</span>
                                        </div>
                                      </td>
                                      <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                                        Waiting for projection
                                      </td>
                                      <td className="py-2.5 px-3 text-[11px] font-mono text-zinc-500">
                                        Not observed
                                      </td>
                                      <td className="py-2.5 px-3 text-[#73737c]">—</td>
                                      <td className="py-2.5 px-3 text-right text-[#73737c]">—</td>
                                    </tr>
                                  );
                                }
                              })}
                            </tbody>
                          </table>
                        </div>

                        {/* Lịch sử thích ứng tải DBS qua các bước gần nhất */}
                        {(() => {
                          const recentSteps = legacyStepsAdapter
                            .filter((s) => s.state === 'COMMITTED' && s.workerContributions && s.workerContributions.length > 0)
                            .slice(0, 10)
                            .reverse();

                          if (recentSteps.length <= 1) return null;

                          return (
                            <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs border-t border-white/[0.04]">
                              <span className="text-[#73737c] text-[11px]">
                                Chọn nhanh bước ({recentSteps.length} bước gần nhất):
                              </span>
                              <div className="flex items-center gap-1.5 flex-wrap">
                                {recentSteps.map((st) => {
                                  const isSelected = st.operationId === currentViewStep?.operationId;
                                  return (
                                    <button
                                      key={st.operationId}
                                      type="button"
                                      onClick={() => {
                                        const idx = legacyStepsAdapter.findIndex((s: any) => s.operationId === st.operationId);
                                        if (idx >= 0) setSelectedStepIndex(idx);
                                      }}
                                      className={`px-2 py-1 rounded border transition-colors flex items-center gap-1.5 text-[10px] font-mono cursor-pointer ${
                                        isSelected
                                          ? 'bg-blue-600/20 border-blue-500/50 text-blue-400 font-semibold'
                                          : 'bg-[#171719] hover:bg-[#202024] border-white/[0.06] text-[#a1a1a8]'
                                      }`}
                                      title={`Xem bước #${st.operationId}`}
                                    >
                                      <span>#{st.operationId}</span>
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    );
                  })()}
                </div>
        </div>
      )}


                                            {/* TAB 3: FULL METRICS */ }
                                            {
                                              activeTab === 'metrics' && (
                                                <div className="space-y-4">
                                                  <StepHistoryControls
                                                    error={stream.stepsError}
                                                    onRetry={stream.hasMoreSteps ? stream.loadMoreSteps : stream.refreshSnapshot}
                                                  />
                                                  {epochMetricsError && <div role="alert" className="flex items-center gap-3 text-xs text-rose-400">
                                                    <span>{epochMetricsError}</span>
                                                    <button type="button" className="underline focus-visible:outline-2 focus-visible:outline-blue-400" onClick={() => setEpochRefresh(value => value + 1)}>Thử lại</button>
                                                  </div>}
                                                  <FullMetricsDashboard
                                                    key={resolvedAttemptId}
                                                    steps={legacyStepsAdapter}
                                                    expectedWorkers={expectedWorkersCount ?? 0}
                                                    epochMetrics={epochMetrics}
                                                    onSelectStepDetail={requestStepDetail}
                                                  />
                                                </div>
                                              )
                                            }

                                            {/* Detailed Synchronization Modal */ }
                                            {
                                              showDetailedSyncModal && legacyStepsAdapter[0] && (
                                                <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4 backdrop-blur-xs">
                                                  <div className="bg-[#121214] border border-white/[0.1] rounded max-w-4xl w-full p-4 space-y-3">
                                                    <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
                                                      <h3 className="text-xs font-semibold text-[#f3f3f4]">
                                                        Strict BSP Synchronization Pipeline
                                                      </h3>
                                                      <button
                                                        type="button"
                                                        onClick={() => setShowDetailedSyncModal(false)}
                                                        className="p-1 rounded text-[#73737c] hover:text-[#f3f3f4] transition-colors"
                                                      >
                                                        <X className="w-4 h-4" />
                                                      </button>
                                                    </div>

                                                    <DistributedTrainingFlowViz
                                                      currentStep={legacyStepsAdapter[0]}
                                                      workers={legacyWorkersAdapter}
                                                      expectedWorkers={expectedWorkersCount ?? 0}
                                                      onSelectWorker={worker => {
                                                        setSelectedWorker(worker);
                                                        setShowDetailedSyncModal(false);
                                                      }}
                                                      onInspectStep={step => {
                                                        const idx = legacyStepsAdapter.findIndex((s: any) => s.stepId === step.stepId || s.operationId === step.operationId);
                                                        if (idx >= 0) setSelectedStepIndex(idx);
                                                        setShowDetailedSyncModal(false);
                                                      }}
                                                    />
                                                  </div>
                                                </div>
                                              )
                                            }

                                            {/* Confirmation Modal for Abort */ }
                                            <ConfirmationModal
                                              isOpen={isAbortModalOpen}
                                              title="Abort Distributed Training Run"
                                              message="Are you sure you want to abort this training attempt? The coordinator will signal all participating workers to halt gradient computations immediately."
                                              confirmLabel="Abort Run"
                                              isDestructive={true}
                                              onConfirm={handleConfirmAbort}
                                              onCancel={() => setIsAbortModalOpen(false)}
                                            />

                                            {/* Drawers */ }
      <EventDetailDrawer
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
      />

      <WorkerDetailDrawer
        worker={selectedWorker}
        onClose={() => setSelectedWorker(null)}
      />
    </div>
                                      );
};
