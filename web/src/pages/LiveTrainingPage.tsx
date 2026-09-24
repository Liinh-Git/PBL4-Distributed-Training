import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
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
} from 'lucide-react';
import { useAttemptStream } from '../hooks/useAttemptStream';
import { attemptsService, metricsService, workersService, stepsService } from '../api';
import { MetricItemData, WorkerSessionItemData, StepListItemData } from '../types/api';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { LiveActivityConsole } from '../components/live/LiveActivityConsole';
import { CompactSyncViz } from '../components/training/CompactSyncViz';
import { DistributedTrainingFlowViz } from '../components/training/DistributedTrainingFlowViz';
import { TrainingTopologyVisualizer } from '../components/training/TrainingTopologyVisualizer';
import { LiveTrainingCharts, FullMetricsDashboard } from '../components/charts/LiveTrainingCharts';
import { TechnicalDetailsDrawer } from '../components/drawers/TechnicalDetailsDrawer';
import { EventDetailDrawer } from '../components/drawers/EventDetailDrawer';
import { WorkerDetailDrawer } from '../components/drawers/WorkerDetailDrawer';
import { StepInspectorDrawer } from '../components/drawers/StepInspectorDrawer';
import { CopyableId } from '../components/common/CopyableId';
import { AttemptStateBadge } from '../components/common/Badge';

export const LiveTrainingPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const explicitAttemptId = searchParams.get('attemptId');
  const explicitJobId = searchParams.get('jobId');

  // Attempt Resolution
  const [resolvedAttemptId, setResolvedAttemptId] = useState<string | null>(explicitAttemptId);
  const [attemptResolving, setAttemptResolving] = useState<boolean>(!explicitAttemptId);

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
        const params: any = { limit: 1 };
        if (explicitJobId) {
          params.job_id = explicitJobId;
        }
        const res = await attemptsService.listAttempts(params);
        if (res.data && res.data.length > 0) {
          setResolvedAttemptId(res.data[0].attempt_id);
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

  // Realtime stream hook
  const stream = useAttemptStream(resolvedAttemptId);

  // Metrics from API 40.0
  const [metrics, setMetrics] = useState<MetricItemData[]>([]);
  const [metricsLoading, setMetricsLoading] = useState<boolean>(false);
  const [metricsUnavailable, setMetricsUnavailable] = useState<boolean>(false);

  useEffect(() => {
    if (!resolvedAttemptId) return;

    const fetchMetrics = async () => {
      try {
        setMetricsLoading(true);
        setMetricsUnavailable(false);
        const res = await metricsService.queryMetrics(resolvedAttemptId, { limit: 100 });
        setMetrics(res.data || []);
      } catch (err: any) {
        // Backend discrepancy: API 40.0 not yet implemented in backend
        setMetricsUnavailable(true);
      } finally {
        setMetricsLoading(false);
      }
    };

    fetchMetrics();
  }, [resolvedAttemptId, stream.lastReceivedSeq]);

  // UI state
  const [activeTab, setActiveTab] = useState<'live' | 'topology' | 'metrics' | 'technical'>('live');
  const [isAbortModalOpen, setIsAbortModalOpen] = useState(false);
  const [isTechnicalDrawerOpen, setIsTechnicalDrawerOpen] = useState(false);
  const [checkpointSavedToast, setCheckpointSavedToast] = useState(false);
  const [showDetailedSyncModal, setShowDetailedSyncModal] = useState(false);
  const [isOverflowOpen, setIsOverflowOpen] = useState(false);

  // Drawer selected items
  const [selectedWorker, setSelectedWorker] = useState<any>(null);
  const [selectedStep, setSelectedStep] = useState<any>(null);
  const [selectedEvent, setSelectedEvent] = useState<any>(null);

  const attempt = stream.attempt;
  const snapshot = stream.snapshot;
  const workers = stream.workers;
  const steps = stream.steps;
  const events = stream.events;
  const activeStep = steps[0];

  const handleRequestCheckpoint = async () => {
    try {
      await stream.requestCheckpoint('manual');
      setCheckpointSavedToast(true);
      setTimeout(() => setCheckpointSavedToast(false), 3500);
    } catch (err: any) {
      alert(`Checkpoint request failed: ${err?.message || 'Unknown error'}`);
    }
  };

  const handleConfirmAbort = async () => {
    try {
      await stream.abortAttempt('Operator aborted training run');
      setIsAbortModalOpen(false);
    } catch (err: any) {
      alert(`Failed to abort attempt: ${err?.message || 'Unknown error'}`);
    }
  };

  if (attemptResolving || (stream.loading && !attempt)) {
    return (
      <div className="w-full py-20 flex flex-col items-center justify-center text-center font-sans select-none text-xs text-[#73737c] gap-3">
        <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
        <span>Connecting to training attempt runtime stream...</span>
      </div>
    );
  }

  if (!resolvedAttemptId || !attempt) {
    return (
      <div className="w-full py-16 flex flex-col items-center justify-center text-center font-sans select-none">
        <div className="w-12 h-12 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mb-4 text-[#73737c]">
          <Activity className="w-5 h-5 text-[#a1a1a8]" />
        </div>
        <h2 className="text-base font-semibold text-[#f3f3f4]">
          No active training attempt found.
        </h2>
        <p className="text-xs text-[#73737c] mt-1 max-w-md">
          Start a new training run or select an existing attempt to observe realtime progress.
        </p>
        <div className="flex items-center gap-3 mt-5">
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New training</span>
          </Link>
          <Link
            to="/jobs"
            className="px-3.5 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#a1a1a8] hover:text-[#f3f3f4] text-xs transition-colors border border-white/[0.07]"
          >
            View saved jobs
          </Link>
        </div>
      </div>
    );
  }

  // Adapter for subcomponents expecting legacy shapes
  const legacyAttemptAdapter: any = {
    id: attempt.attempt_id,
    jobId: attempt.job_id,
    jobName: attempt.job_id,
    state: attempt.state,
    executionMode: attempt.execution_mode,
    epoch: snapshot?.epoch || attempt.epoch || 1,
    totalEpochs: 20,
    currentBatch: snapshot?.current_batch_ordinal || 0,
    totalBatches: 782,
    activeWorkers: workers.filter(w => w.state === 'READY' || w.state === 'INITIALIZING').length || workers.length || 3,
    expectedWorkers: attempt.expected_workers || 3,
    modelVersion: `v${snapshot?.model_version || attempt.model_version || 1}`,
    datasetBuildId: snapshot?.strategy_state?.current_step_id ? `step_${snapshot.strategy_state.current_step_id}` : 'dsb_cifar10',
    elapsedFormatted: 'Active run',
    runtimeEventSeq: stream.lastReceivedSeq,
  };

  const legacyWorkersAdapter: any[] = workers.map(w => ({
    workerId: w.worker_id,
    sessionId: w.session_id,
    nodeLabel: w.node_label || `node-${w.worker_id}`,
    state: w.state,
    assignedShard: `shard-${w.shard_id ?? w.worker_id}`,
    currentModelVersion: w.local_model_version || attempt.model_version || 1,
    protocolVersion: `dtp/v${w.protocol_version || 1}`,
    connectedAt: w.connected_at,
    lastHeartbeatMs: w.last_heartbeat_at ? Math.max(50, Math.round(Date.now() - new Date(w.last_heartbeat_at).getTime())) : 150,
  }));

  const legacyStepsAdapter: any[] = steps.map(st => ({
    stepId: st.step_id,
    operationId: st.operation_id,
    epoch: st.epoch,
    batchOrdinal: st.batch_ordinal,
    state: st.state,
    inputModelVersion: st.input_model_version,
    outputModelVersion: st.output_model_version || st.input_model_version + 1,
    totalSampleCount: st.total_sample_count || 192,
    timings: {
      startedAt: 'T-10s',
      committedAt: st.committed_at || 'T-2s',
      totalDurationMs: 420,
    },
    workerContributions: [
      { workerId: 0, contributionAccepted: true, parameterApplied: true },
      { workerId: 1, contributionAccepted: true, parameterApplied: true },
      { workerId: 2, contributionAccepted: true, parameterApplied: true },
    ],
  }));

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Toast Notification */}
      {checkpointSavedToast && (
        <div className="fixed top-5 right-5 z-50 bg-[#121214] border border-emerald-500/40 text-emerald-300 px-3.5 py-2.5 rounded shadow-2xl flex items-center gap-2 text-xs font-medium animate-in slide-in-from-top-2">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>Checkpoint request accepted by coordinator</span>
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

      {/* Page Header */}
      <div className="space-y-2 pb-3 border-b border-white/[0.07]">
        <div className="flex items-center justify-between">
          <div className="text-[11px] text-[#73737c]">
            Attempt <span className="font-mono text-[#a1a1a8]">{attempt.attempt_id}</span> (Job: {attempt.job_id})
          </div>

          {/* Connection Status Indicator */}
          <div className="flex items-center gap-2 text-[11px]">
            {stream.connectionState === 'CONNECTED' && (
              <span className="inline-flex items-center gap-1.5 text-emerald-400 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                <span>WebSocket Live (seq: {stream.lastReceivedSeq})</span>
              </span>
            )}
            {stream.connectionState === 'RECONNECTING' && (
              <span className="inline-flex items-center gap-1.5 text-amber-400 font-mono animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                <span>Reconnecting (after_seq: {stream.lastReceivedSeq})...</span>
              </span>
            )}
            {stream.connectionState === 'DEGRADED' && (
              <span className="inline-flex items-center gap-1.5 text-rose-400 font-mono">
                <WifiOff className="w-3 h-3 text-rose-400" />
                <span>Stream Degraded</span>
              </span>
            )}
            {stream.connectionState === 'DISCONNECTED' && (
              <span className="inline-flex items-center gap-1.5 text-[#73737c] font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-[#73737c]" />
                <span>Disconnected</span>
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-base font-semibold text-[#f3f3f4]">
                {attempt.job_id}
              </h1>
              <AttemptStateBadge state={attempt.state} />
            </div>

            <div className="flex items-center gap-2 text-xs text-[#73737c] flex-wrap">
              <span>Epoch {snapshot?.epoch || attempt.epoch || 1}</span>
              <span>·</span>
              <span>Model v{snapshot?.model_version || attempt.model_version || 1}</span>
              <span>·</span>
              <span>{workers.length} active workers</span>
              <span>·</span>
              <span>Mode: {attempt.execution_mode}</span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 self-start sm:self-center">
            <button
              type="button"
              onClick={handleRequestCheckpoint}
              disabled={attempt.state !== 'RUNNING'}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] text-xs font-normal transition-colors border border-white/[0.07] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Save className="w-3.5 h-3.5 text-[#73737c]" />
              <span>Checkpoint</span>
            </button>

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
                    onClick={() => {
                      setIsOverflowOpen(false);
                      setIsAbortModalOpen(true);
                    }}
                    className="w-full text-left px-3 py-1.5 text-rose-400 hover:bg-rose-500/10 transition-colors"
                  >
                    Abort training
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
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'live'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Live
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('topology')}
            className={`px-3 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === 'topology'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>Cluster Topology</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('metrics')}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'metrics'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Metrics {metricsUnavailable && <span className="text-[10px] text-amber-400">(Unavailable)</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('technical')}
            className={`px-3 py-1 rounded transition-colors ${
              activeTab === 'technical'
                ? 'bg-[#171719] text-[#f3f3f4] font-medium border border-white/[0.07]'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
            }`}
          >
            Technical
          </button>
        </div>
      </div>

      {/* TAB 1: LIVE */}
      {activeTab === 'live' && (
        <div className="space-y-4">
          <TrainingTopologyVisualizer
            currentStep={legacyStepsAdapter[0]}
            workers={legacyWorkersAdapter}
            expectedWorkers={attempt.expected_workers || 3}
            attempt={legacyAttemptAdapter}
            isSimulating={false}
            onToggleSimulating={() => {}}
            onSelectWorker={setSelectedWorker}
            onOpenServerDetails={() => setIsTechnicalDrawerOpen(true)}
          />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
            {/* LEFT (~65%): Live Activity */}
            <div className="lg:col-span-8 space-y-4">
              <LiveActivityConsole
                events={events as any}
                onSelectEvent={setSelectedEvent}
                isLive={attempt.state === 'RUNNING'}
              />
            </div>

            {/* RIGHT (~35%): Compact Sync + Workers + Current Step */}
            <div className="lg:col-span-4 space-y-3">
              {legacyStepsAdapter[0] && (
                <CompactSyncViz
                  currentStep={legacyStepsAdapter[0]}
                  workers={legacyWorkersAdapter}
                  expectedWorkers={attempt.expected_workers || 3}
                  onOpenDetails={() => setShowDetailedSyncModal(true)}
                />
              )}

              {/* Workers Status List */}
              <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2">
                <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
                  <h3 className="text-xs font-semibold text-[#f3f3f4]">
                    Workers ({workers.length})
                  </h3>
                  <span className="inline-flex items-center gap-1.5 text-xs text-[#a1a1a8]">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    <span>DTP Connected</span>
                  </span>
                </div>

                <div className="divide-y divide-white/[0.04] text-xs">
                  {workers.length === 0 ? (
                    <div className="py-4 text-center text-[#73737c]">
                      No workers connected yet.
                    </div>
                  ) : (
                    workers.map(w => (
                      <div
                        key={w.worker_id}
                        onClick={() => setSelectedWorker({
                          workerId: w.worker_id,
                          sessionId: w.session_id,
                          nodeLabel: w.node_label,
                          state: w.state,
                          protocolVersion: `dtp/v${w.protocol_version}`,
                          connectedAt: w.connected_at,
                          lastHeartbeatMs: w.last_heartbeat_at ? Math.max(50, Math.round(Date.now() - new Date(w.last_heartbeat_at).getTime())) : 150,
                          assignedShard: `shard-${w.shard_id ?? w.worker_id}`,
                          localModelVersion: w.local_model_version,
                          failureCode: w.failure_code,
                        })}
                        className="py-2 flex items-center justify-between hover:text-[#f3f3f4] cursor-pointer transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-[#f3f3f4]">Worker {w.worker_id}</span>
                          <span className="text-[11px] text-[#73737c]">{w.node_label || `node-${w.worker_id}`}</span>
                        </div>
                        <span className="text-[11px] text-emerald-400 font-mono">
                          {w.state}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Current Step Parameters */}
              {activeStep && (
                <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 text-xs">
                  <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
                    <h3 className="text-xs font-semibold text-[#f3f3f4]">
                      Current step
                    </h3>
                    <span className="text-[11px] text-[#73737c] font-mono">
                      #{activeStep.operation_id}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 divide-x divide-white/[0.04] py-1 text-xs">
                    <div>
                      <div className="text-[11px] text-[#73737c]">Input → Output</div>
                      <div className="text-[#f3f3f4] mt-0.5 font-mono">
                        v{activeStep.input_model_version} → v{activeStep.output_model_version || activeStep.input_model_version + 1}
                      </div>
                    </div>
                    <div className="pl-3">
                      <div className="text-[11px] text-[#73737c]">Batch Size</div>
                      <div className="text-[#f3f3f4] mt-0.5">
                        {activeStep.total_sample_count || 192} samples
                      </div>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-white/[0.07]">
                    <button
                      type="button"
                      onClick={() => setSelectedStep({
                        stepId: activeStep.step_id,
                        operationId: activeStep.operation_id,
                        epoch: activeStep.epoch,
                        batchOrdinal: activeStep.batch_ordinal,
                        state: activeStep.state,
                        inputModelVersion: activeStep.input_model_version,
                        outputModelVersion: activeStep.output_model_version || activeStep.input_model_version + 1,
                        totalSampleCount: activeStep.total_sample_count || 192,
                        attemptId: attempt.attempt_id,
                        timings: {
                          startedAt: 'T-10s',
                          committedAt: activeStep.committed_at || 'In progress',
                          totalDurationMs: 420,
                        },
                      })}
                      className="text-xs text-[#73737c] hover:text-[#f3f3f4] inline-flex items-center gap-1 transition-colors"
                    >
                      <span>Inspect step timings</span>
                      <ChevronRight className="w-3 h-3 text-[#73737c]" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Live Metrics Charts */}
          <LiveTrainingCharts
            steps={legacyStepsAdapter}
            onViewAllMetrics={() => setActiveTab('metrics')}
          />
        </div>
      )}

      {/* TAB 2: TOPOLOGY */}
      {activeTab === 'topology' && (
        <div className="space-y-4">
          <TrainingTopologyVisualizer
            currentStep={legacyStepsAdapter[0]}
            workers={legacyWorkersAdapter}
            expectedWorkers={attempt.expected_workers || 3}
            attempt={legacyAttemptAdapter}
            isSimulating={false}
            onToggleSimulating={() => {}}
            onSelectWorker={setSelectedWorker}
            onOpenServerDetails={() => setIsTechnicalDrawerOpen(true)}
          />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {workers.map(w => (
              <div key={w.worker_id} className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 text-xs">
                <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                    <span className="font-semibold text-[#f3f3f4]">Worker {w.worker_id}</span>
                  </div>
                  <span className="text-[#73737c] font-mono">{w.node_label || `worker-${w.worker_id}`}</span>
                </div>
                <div className="space-y-1.5 text-[#a1a1a8]">
                  <div className="flex justify-between">
                    <span className="text-[#73737c]">State:</span>
                    <span className="text-[#f3f3f4] font-medium font-mono">{w.state}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#73737c]">Session:</span>
                    <span className="font-mono text-[#f3f3f4]">{w.session_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#73737c]">Model Ver:</span>
                    <span className="font-mono text-emerald-400">v{w.local_model_version || attempt.model_version || 1}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#73737c]">Protocol:</span>
                    <span className="font-mono text-[#f3f3f4]">DTP v{w.protocol_version || 1}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: FULL METRICS */}
      {activeTab === 'metrics' && (
        <div className="space-y-4">
          {metricsUnavailable && (
            <div className="p-3 bg-[#171719] border border-amber-500/20 rounded flex items-center gap-2 text-xs text-amber-300">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
              <span>Metrics API 40.0 is not yet implemented on the server. Time-series metrics will populate once available.</span>
            </div>
          )}
          <FullMetricsDashboard steps={legacyStepsAdapter} />
        </div>
      )}

      {/* TAB 4: TECHNICAL DETAILS */}
      {activeTab === 'technical' && (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-4 text-xs">
          <div className="pb-2 border-b border-white/[0.07]">
            <h3 className="text-xs font-semibold text-[#f3f3f4]">
              Runtime Diagnostics & Technical Identifiers
            </h3>
            <p className="text-xs text-[#73737c] mt-0.5">
              Coordinator state, transport protocols, and deterministic hashes
            </p>
          </div>

          <div className="divide-y divide-white/[0.04]">
            <div className="flex items-center justify-between py-2.5">
              <span className="text-[#73737c]">Job ID</span>
              <CopyableId value={attempt.job_id} truncateLength={32} />
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-[#73737c]">Attempt ID</span>
              <CopyableId value={attempt.attempt_id} truncateLength={32} />
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-[#73737c]">Contract Hash</span>
              <CopyableId value={attempt.contract_hash || 'Unresolved'} truncateLength={32} />
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-[#73737c]">Deterministic Barrier Protocol</span>
              <span className="text-[#a1a1a8]">Strict BSP (DTP/1)</span>
            </div>
            <div className="flex items-center justify-between py-2.5">
              <span className="text-[#73737c]">Runtime Event Sequence</span>
              <span className="text-emerald-400 font-mono">seq #{stream.lastReceivedSeq}</span>
            </div>
          </div>

          <div className="pt-2 border-t border-white/[0.07] flex justify-end">
            <button
              type="button"
              onClick={() => setIsTechnicalDrawerOpen(true)}
              className="px-3 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-[#f3f3f4] text-xs font-medium transition-colors border border-white/[0.07]"
            >
              Open Technical Inspector Drawer
            </button>
          </div>
        </div>
      )}

      {/* Detailed Synchronization Modal */}
      {showDetailedSyncModal && legacyStepsAdapter[0] && (
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
              expectedWorkers={attempt.expected_workers || 3}
              onSelectWorker={worker => {
                setSelectedWorker(worker);
                setShowDetailedSyncModal(false);
              }}
              onInspectStep={step => {
                setSelectedStep(step);
                setShowDetailedSyncModal(false);
              }}
            />
          </div>
        </div>
      )}

      {/* Confirmation Modal for Abort */}
      <ConfirmationModal
        isOpen={isAbortModalOpen}
        title="Abort Distributed Training Run"
        message="Are you sure you want to abort this training attempt? The coordinator will signal all participating workers to halt gradient computations immediately."
        confirmLabel="Abort Run"
        isDestructive={true}
        onConfirm={handleConfirmAbort}
        onCancel={() => setIsAbortModalOpen(false)}
      />

      {/* Drawers */}
      <TechnicalDetailsDrawer
        isOpen={isTechnicalDrawerOpen}
        onClose={() => setIsTechnicalDrawerOpen(false)}
        attempt={legacyAttemptAdapter}
        workers={legacyWorkersAdapter}
      />

      <EventDetailDrawer
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
      />

      <WorkerDetailDrawer
        worker={selectedWorker}
        onClose={() => setSelectedWorker(null)}
      />

      <StepInspectorDrawer
        step={selectedStep}
        onClose={() => setSelectedStep(null)}
      />
    </div>
  );
};
