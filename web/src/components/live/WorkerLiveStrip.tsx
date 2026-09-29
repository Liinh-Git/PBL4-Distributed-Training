import React, { useMemo } from 'react';
import { CheckCircle2, Clock, ArrowRight, Server, ShieldCheck, AlertTriangle, HelpCircle } from 'lucide-react';
import { TrainingStep, WorkerSession } from '../../types';
import { detectSlowWorkers, WorkerComputeTelemetry } from '../../utils/stragglerDetection';

interface WorkerLiveStripProps {
  currentStep: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  onSelectWorker: (worker: WorkerSession) => void;
  onViewDetails: () => void;
  recentSteps?: TrainingStep[];
  workloadPolicy?: 'equal' | 'dbs' | string;
}

interface WorkerVisualState {
  dotClass: string;
  label: string;
}

const WORKER_STATE_VISUALS: Record<string, WorkerVisualState> = {
  CONNECTING: { dotClass: 'bg-zinc-400 animate-pulse', label: 'Connecting' },
  REGISTERING: { dotClass: 'bg-blue-400 animate-pulse', label: 'Registering' },
  PROVISIONING: { dotClass: 'bg-blue-400', label: 'Provisioning' },
  SHARD_READY: { dotClass: 'bg-cyan-400', label: 'Shard Ready' },
  MODEL_SYNCING: { dotClass: 'bg-indigo-400 animate-pulse', label: 'Model Syncing' },
  READY: { dotClass: 'bg-emerald-400', label: 'Ready' },
  RUNNING: { dotClass: 'bg-emerald-400', label: 'Running' },
  DISCONNECTED: { dotClass: 'bg-zinc-500', label: 'Disconnected' },
  FAILED: { dotClass: 'bg-rose-500', label: 'Failed' },
};

function getWorkerVisual(state: string | undefined): WorkerVisualState {
  if (!state) return { dotClass: 'bg-zinc-500', label: 'Unknown' };
  const key = state.toUpperCase();
  return WORKER_STATE_VISUALS[key] || { dotClass: 'bg-zinc-400', label: state };
}

export const WorkerLiveStrip: React.FC<WorkerLiveStripProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  onSelectWorker,
  onViewDetails,
  recentSteps,
  workloadPolicy,
}) => {
  const contributions = currentStep?.workerContributions || [];
  const acceptedCount = contributions.filter(c => c.contributionAccepted === true).length;
  const waitingCount = contributions.filter(c => c.contributionAccepted === false).length;
  const unknownCount = contributions.filter(c => c.contributionAccepted == null).length;
  const hasUnknown = unknownCount > 0 || contributions.length === 0;
  const isCommitted = currentStep?.state === 'COMMITTED' && !hasUnknown;
  const isDBS = workloadPolicy === 'dbs';

  // Presentation heuristic: Analyze recent steps for compute stragglers
  const stepsToAnalyze = useMemo(() => {
    if (recentSteps && recentSteps.length > 0) return recentSteps;
    return currentStep ? [currentStep] : [];
  }, [recentSteps, currentStep]);

  const slowWorkersMap = useMemo(
    () => detectSlowWorkers(stepsToAnalyze),
    [stepsToAnalyze]
  );

  // Determine current sync status text
  let syncStatusText = '';
  if (isCommitted) {
    syncStatusText = 'All contributions synchronized · Parameters applied';
  } else if (acceptedCount === expectedWorkers && expectedWorkers > 0) {
    syncStatusText = 'All contributions received · Updating global model';
  } else if (contributions.length === 0 || (hasUnknown && acceptedCount === 0 && waitingCount === 0)) {
    syncStatusText = 'Waiting for step telemetry · Status unknown';
  } else {
    const missingWorker = contributions.find(c => c.contributionAccepted === false);
    const waitingFor = missingWorker !== undefined ? `Worker ${missingWorker.workerId}` : 'remaining workers';
    syncStatusText = `${acceptedCount} of ${expectedWorkers} contributions received · Waiting for ${waitingFor}`;
  }

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
      {/* Synchronization Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            isCommitted || (acceptedCount === expectedWorkers && expectedWorkers > 0)
              ? 'bg-emerald-400'
              : hasUnknown && acceptedCount === 0
              ? 'bg-zinc-500'
              : 'bg-amber-400'
          }`} />
          <div className="flex items-center gap-1.5 flex-wrap text-xs">
            <span className="font-semibold text-[#f3f3f4]">Synchronization:</span>
            <span className="text-[#a1a1a8] font-normal">{syncStatusText}</span>
          </div>
        </div>

        <button
          type="button"
          onClick={onViewDetails}
          className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 font-normal transition-colors cursor-pointer self-start sm:self-auto"
        >
          <span>Details</span>
          <ArrowRight className="w-3 h-3" />
        </button>
      </div>

      {/* Workers Quick Status Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {workers.map((worker) => {
          const contrib = contributions.find(c => c.workerId === worker.workerId);
          const isReceived = contrib?.contributionAccepted === true || (isCommitted && contrib?.contributionAccepted !== false);
          const isWaiting = contrib?.contributionAccepted === false;
          const isUnknown = !isReceived && !isWaiting;
          const visual = getWorkerVisual(worker.state);
          const telemetry = slowWorkersMap.get(worker.workerId);
          const computeMs = contrib?.computeMs ?? telemetry?.currentComputeMs ?? telemetry?.medianComputeMs;
          const isSlow = Boolean(telemetry?.isSlow);

          return (
            <button
              type="button"
              key={worker.workerId}
              onClick={() => onSelectWorker(worker)}
              aria-label={`Worker ${worker.workerId}, ${visual.label}, ${
                isReceived
                  ? 'contribution received'
                  : isWaiting
                  ? 'waiting for contribution'
                  : 'contribution status unknown'
              }${isSlow ? ', slow worker' : ''}`}
              className="p-2.5 rounded bg-[#171719] hover:bg-[#1f1f23] focus:outline-none focus:ring-1 focus:ring-blue-500/50 transition-colors cursor-pointer flex items-center justify-between group text-left w-full border-0"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${visual.dotClass}`} />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-xs font-semibold text-[#f3f3f4] group-hover:text-white transition-colors">
                      Worker {worker.workerId}
                    </span>
                    {isSlow && (
                      <span
                        data-testid={`slow-badge-worker-${worker.workerId}`}
                        className="px-1.5 py-0.2 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40 inline-flex items-center"
                        title={`Compute straggler detected: median compute time (${Math.round(telemetry?.medianComputeMs || computeMs || 0)}ms) > 1.5x group median`}
                      >
                        Slow
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-[#73737c] truncate flex items-center gap-1.5 flex-wrap">
                    <span>{visual.label}</span>
                    {computeMs != null && (
                      <span className="text-[#a1a1a8] font-mono">
                        · {Math.round(computeMs)}ms
                      </span>
                    )}
                    {isDBS && contrib?.sampleCount != null && (
                      <span className="text-[#73737c]">
                        · {contrib.sampleCount} units
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="shrink-0 pl-2">
                {isReceived ? (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                    <CheckCircle2 className="w-3 h-3 shrink-0" />
                    <span>Received</span>
                  </span>
                ) : isWaiting ? (
                  <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                    <Clock className="w-3 h-3 shrink-0 animate-spin" />
                    <span>Waiting</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                    <HelpCircle className="w-3 h-3 shrink-0" />
                    <span>Unknown</span>
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
