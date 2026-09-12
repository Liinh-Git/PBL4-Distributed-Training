import React, { useMemo } from 'react';
import {
  Server,
  Cpu,
  RefreshCw,
  CheckCircle2,
  Clock,
  Radio,
  Save,
  ArrowRight,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { TrainingStep, WorkerSession, StepState } from '../../types';

interface DistributedTrainingFlowVizProps {
  currentStep: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  onSelectWorker?: (worker: WorkerSession) => void;
  onInspectStep?: (step: TrainingStep) => void;
}

export const DistributedTrainingFlowViz: React.FC<DistributedTrainingFlowVizProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  onSelectWorker,
  onInspectStep,
}) => {
  const contributions = currentStep?.workerContributions || [];
  const acceptedWorkers = useMemo(
    () => contributions.filter(c => c.contributionAccepted),
    [contributions]
  );
  const acceptedCount = acceptedWorkers.length;
  const isBarrierOpen = acceptedCount === expectedWorkers;

  const appliedWorkers = useMemo(
    () => contributions.filter(c => c.parameterApplied),
    [contributions]
  );
  const appliedCount = currentStep?.state === 'COMMITTED' ? expectedWorkers : appliedWorkers.length;

  const isUpdating =
    currentStep?.state === 'UPDATING' || currentStep?.state === 'AGGREGATING';
  const isBroadcasting =
    currentStep?.state === 'BROADCASTING' ||
    currentStep?.state === 'WAITING_PARAMETER_APPLIED';
  const isCommitted = currentStep?.state === 'COMMITTED';
  const isCheckpointing = currentStep?.state === 'CHECKPOINTING';

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3 font-sans select-none">
      {/* Header with Title and Realtime State */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Synchronization Pipeline
          </h3>
          <span className="text-xs text-[#73737c]">·</span>
          <span className="text-xs text-[#73737c]">Strict BSP Barrier</span>
        </div>

        {/* Phase Pill Indicator */}
        <div className="flex items-center gap-3 self-start sm:self-auto text-xs">
          {isCheckpointing && (
            <div className="flex items-center gap-1 text-amber-400">
              <Save className="w-3 h-3" />
              <span>Checkpointing</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 text-[#73737c]">
            <span>Barrier:</span>
            <span
              className={`font-medium ${
                isBarrierOpen ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {acceptedCount} / {expectedWorkers} Gradients
            </span>
          </div>
        </div>
      </div>

      {/* Visual Pipeline Canvas */}
      <div className="relative bg-[#0b0b0c] rounded border border-white/[0.07] p-3.5 lg:p-4 overflow-x-auto">
        <div className="min-w-[760px] flex items-center justify-between gap-4">
          
          {/* 1. WORKERS COLUMN */}
          <div className="w-56 shrink-0 space-y-2">
            <div className="text-xs text-[#73737c] mb-1.5 flex items-center justify-between">
              <span>Workers ({(workers || []).length})</span>
              <span className="text-emerald-400 text-xs">All healthy</span>
            </div>

            {(workers || []).map(worker => {
              const contrib = contributions.find(c => c.workerId === worker.workerId);
              const hasAccepted = contrib?.contributionAccepted ?? false;
              const hasApplied = isCommitted ? true : (contrib?.parameterApplied ?? false);

              return (
                <div
                  key={worker.workerId}
                  onClick={() => onSelectWorker?.(worker)}
                  className={`p-2.5 rounded border transition-colors cursor-pointer relative ${
                    hasApplied
                      ? 'bg-[#141416] border-emerald-500/20 hover:border-emerald-500/40'
                      : hasAccepted
                      ? 'bg-[#141416] border-blue-500/20 hover:border-blue-500/40'
                      : 'bg-[#141416] border-white/[0.06] hover:border-white/[0.12]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-5 h-5 rounded flex items-center justify-center text-xs font-medium ${
                          hasApplied
                            ? 'bg-emerald-500/10 text-emerald-400'
                            : hasAccepted
                            ? 'bg-blue-500/10 text-blue-400'
                            : 'bg-white/[0.04] text-[#73737c]'
                        }`}
                      >
                        {worker.workerId}
                      </div>
                      <div>
                        <div className="text-xs font-medium text-[#f3f3f4]">
                          Worker {worker.workerId}
                        </div>
                        <div className="text-[11px] text-[#73737c]">
                          {worker.nodeLabel || `node-${worker.workerId}`}
                        </div>
                      </div>
                    </div>

                    {/* Status Badge */}
                    <div className="text-xs">
                      {hasApplied ? (
                        <span className="text-emerald-400 inline-flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Applied</span>
                        </span>
                      ) : hasAccepted ? (
                        <span className="text-blue-400 inline-flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Sent</span>
                        </span>
                      ) : (
                        <span className="text-amber-400 inline-flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          <span>Computing</span>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Shard & samples info */}
                  <div className="flex items-center justify-between text-[11px] text-[#73737c] mt-1.5 pt-1.5 border-t border-white/[0.04]">
                    <span>Shard {worker.shardId || worker.workerId}</span>
                    <span>64 samples</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 2. GRADIENT INGESTION PATH (CONVERGING CONNECTOR) */}
          <div className="flex-1 flex items-center justify-center relative px-2">
            <svg className="w-full h-40 overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none">
              <path
                d="M 0 18 C 50 18, 50 50, 100 50"
                fill="none"
                stroke={contributions[0]?.contributionAccepted ? '#3b82f6' : '#27272a'}
                strokeWidth={contributions[0]?.contributionAccepted ? '1.5' : '1'}
                strokeDasharray={contributions[0]?.contributionAccepted ? 'none' : '3 3'}
                className="transition-colors duration-300"
              />
              <path
                d="M 0 50 L 100 50"
                fill="none"
                stroke={contributions[1]?.contributionAccepted ? '#3b82f6' : '#27272a'}
                strokeWidth={contributions[1]?.contributionAccepted ? '1.5' : '1'}
                strokeDasharray={contributions[1]?.contributionAccepted ? 'none' : '3 3'}
                className="transition-colors duration-300"
              />
              <path
                d="M 0 82 C 50 82, 50 50, 100 50"
                fill="none"
                stroke={contributions[2]?.contributionAccepted ? '#3b82f6' : '#27272a'}
                strokeWidth={contributions[2]?.contributionAccepted ? '1.5' : '1'}
                strokeDasharray={contributions[2]?.contributionAccepted ? 'none' : '3 3'}
                className="transition-colors duration-300"
              />

              {/* Event-driven animated gradient signal packets */}
              {contributions.map((c, idx) => {
                if (!c.contributionAccepted) return null;
                return (
                  <circle
                    key={c.workerId}
                    r="2.5"
                    fill="#60a5fa"
                  >
                    <animateMotion
                      path={
                        idx === 0
                          ? 'M 0 18 C 50 18, 50 50, 100 50'
                          : idx === 1
                          ? 'M 0 50 L 100 50'
                          : 'M 0 82 C 50 82, 50 50, 100 50'
                      }
                      dur="1.2s"
                      repeatCount="indefinite"
                    />
                  </circle>
                );
              })}
            </svg>
          </div>

          {/* 3. STRICT BARRIER / COLLECT GRADIENTS NODE */}
          <div
            onClick={() => onInspectStep?.(currentStep)}
            className={`w-44 p-3 rounded border transition-colors cursor-pointer text-center relative ${
              isBarrierOpen
                ? 'bg-[#141416] border-emerald-500/30'
                : 'bg-[#141416] border-amber-500/30'
            }`}
          >
            <div className="flex items-center justify-center gap-1.5 text-xs font-medium text-[#f3f3f4]">
              <ShieldCheck
                className={`w-3.5 h-3.5 ${isBarrierOpen ? 'text-emerald-400' : 'text-amber-400'}`}
              />
              <span>Collect Gradients</span>
            </div>
            <div className="text-[11px] text-[#73737c] mt-0.5">
              Barrier Gate
            </div>
            <div
              className={`mt-1.5 py-0.5 px-1.5 rounded text-xs font-mono font-medium ${
                isBarrierOpen
                  ? 'text-emerald-400 bg-emerald-500/10'
                  : 'text-amber-400 bg-amber-500/10'
              }`}
            >
              {acceptedCount} / {expectedWorkers} Arrived
            </div>
            <div className="text-[11px] text-[#73737c] mt-1">
              {isBarrierOpen ? 'Barrier satisfied' : 'Waiting for barrier'}
            </div>
          </div>

          {/* Arrow 1 */}
          <div className="text-[#3f3f46]">
            <ArrowRight className="w-3.5 h-3.5" />
          </div>

          {/* 4. UPDATE GLOBAL MODEL NODE */}
          <div
            onClick={() => onInspectStep?.(currentStep)}
            className={`w-44 p-3 rounded border transition-colors cursor-pointer text-center relative ${
              isUpdating
                ? 'bg-[#141416] border-blue-500/40'
                : isCommitted || isBroadcasting
                ? 'bg-[#141416] border-emerald-500/30'
                : 'bg-[#141416] border-white/[0.06]'
            }`}
          >
            <div className="flex items-center justify-center gap-1.5 text-xs font-medium text-[#f3f3f4]">
              <Cpu
                className={`w-3.5 h-3.5 ${
                  isUpdating
                    ? 'text-blue-400'
                    : isCommitted || isBroadcasting
                    ? 'text-emerald-400'
                    : 'text-[#73737c]'
                }`}
              />
              <span>Update Model</span>
            </div>
            <div className="text-[11px] text-[#73737c] mt-0.5">
              SGD Optimizer
            </div>
            <div className="mt-1.5 py-0.5 px-1.5 rounded text-xs font-mono font-medium text-blue-400 bg-white/[0.03]">
              v{currentStep.outputModelVersion?.replace('v', '') || '3264'}
            </div>
            <div className="text-[11px] text-[#73737c] mt-1">
              {isUpdating
                ? 'Applying all-reduce'
                : isCommitted || isBroadcasting
                ? 'Weights updated'
                : 'Awaiting barrier gate'}
            </div>
          </div>

          {/* Arrow 2 */}
          <div className="text-[#3f3f46]">
            <ArrowRight className="w-3.5 h-3.5" />
          </div>

          {/* 5. BROADCAST NODE */}
          <div
            onClick={() => onInspectStep?.(currentStep)}
            className={`w-40 p-3 rounded border transition-colors cursor-pointer text-center relative ${
              isBroadcasting
                ? 'bg-[#141416] border-blue-500/30'
                : appliedCount === expectedWorkers
                ? 'bg-[#141416] border-emerald-500/30'
                : 'bg-[#141416] border-white/[0.06]'
            }`}
          >
            <div className="flex items-center justify-center gap-1.5 text-xs font-medium text-[#f3f3f4]">
              <Radio
                className={`w-3.5 h-3.5 ${
                  isBroadcasting ? 'text-blue-400' : 'text-emerald-400'
                }`}
              />
              <span>Broadcast</span>
            </div>
            <div className="text-[11px] text-[#73737c] mt-0.5">
              Distribution
            </div>
            <div
              className={`mt-1.5 py-0.5 px-1.5 rounded text-xs font-mono font-medium ${
                appliedCount === expectedWorkers
                  ? 'text-emerald-400 bg-emerald-500/10'
                  : 'text-blue-400 bg-blue-500/10'
              }`}
            >
              {appliedCount} / {expectedWorkers} Synced
            </div>
            <div className="text-[11px] text-[#73737c] mt-1">
              {appliedCount === expectedWorkers
                ? 'ACK confirmed'
                : 'Distributing'}
            </div>
          </div>
        </div>

        {/* 6. RETURN FEEDBACK LOOP: "NEW PARAMETERS APPLIED" */}
        <div className="mt-3 pt-2.5 border-t border-white/[0.05] flex items-center justify-between text-xs text-[#73737c]">
          <div className="flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-emerald-400" />
            <span className="text-[#a1a1a8]">Closed-loop synchronization:</span>
            <span>Parameters verified before next batch</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span>Step</span>
            <span className="text-[#f3f3f4] font-mono">
              #{currentStep.operationId} (Epoch {currentStep.epoch} · Batch {currentStep.batchOrdinal})
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
