import React from 'react';
import {
  CheckCircle2,
  Clock,
  ArrowRight,
  ShieldCheck,
  AlertCircle,
} from 'lucide-react';
import { TrainingStep, WorkerSession } from '../../types';
import { Badge } from '../common/Badge';

interface StrictBspVisualizerProps {
  currentStep: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  barrierWaitMs: number;
  compact?: boolean;
}

export const StrictBspVisualizer: React.FC<StrictBspVisualizerProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  barrierWaitMs,
  compact = false,
}) => {
  const contributions = currentStep?.workerContributions || [];
  const acceptedCount = contributions.filter(c => c.contributionAccepted).length;
  const isCommitted = currentStep?.state === 'COMMITTED';
  const parameterAppliedCount = isCommitted
    ? expectedWorkers
    : contributions.filter(c => c.parameterApplied).length;

  const STAGES = [
    { id: 'COLLECT', label: 'Gradient Computation', description: 'Workers compute backward pass' },
    { id: 'BARRIER', label: 'Strict Barrier Gate', description: 'All workers must reach barrier' },
    { id: 'AGGREGATE', label: 'Gradient All-Reduce', description: 'Parameter aggregation on coordinator' },
    { id: 'APPLY', label: 'Parameter Application', description: 'Broadcast & update weights' },
    { id: 'COMMITTED', label: 'Step Commit', description: 'State locked & model version updated' },
  ];

  const getStageStatus = (stageId: string) => {
    if (isCommitted) return 'completed';
    switch (stageId) {
      case 'COLLECT':
        return currentStep.state === 'COLLECTING_GRADIENTS' ? 'active' : 'completed';
      case 'BARRIER':
        return acceptedCount === expectedWorkers ? 'completed' : 'active';
      case 'AGGREGATE':
        if (currentStep.state === 'AGGREGATING' || currentStep.state === 'UPDATING') return 'active';
        return 'pending';
      case 'APPLY':
        if (currentStep.state === 'WAITING_PARAMETER_APPLIED' || currentStep.state === 'BROADCASTING') return 'active';
        return 'pending';
      case 'COMMITTED':
        return isCommitted ? 'completed' : 'pending';
      default:
        return 'pending';
    }
  };

  if (compact) {
    return (
      <div className="space-y-3 font-sans select-none">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#f3f3f4]">Strict BSP Synchronization</span>
            <span className="font-mono text-[#73737c]">Step #{currentStep.operationId}</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[#a1a1a8]">
              Gradients: <span className="text-[#f3f3f4] font-semibold font-mono">{acceptedCount}/{expectedWorkers}</span>
            </span>
            <Badge variant={isCommitted ? 'success' : 'warning'}>
              {isCommitted ? 'Step Committed' : 'Barrier Active'}
            </Badge>
          </div>
        </div>

        {/* Worker Mini Contribution Strip */}
        <div className="grid grid-cols-3 gap-2 pt-1">
          {contributions.map(c => {
            return (
              <div
                key={c.workerId}
                className="p-2 rounded bg-[#171719] border border-white/[0.04] flex items-center justify-between text-xs"
              >
                <span className="font-medium text-[#f3f3f4]">Worker {c.workerId}</span>
                {c.contributionAccepted ? (
                  <span className="text-emerald-400 text-[11px] flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Accepted
                  </span>
                ) : (
                  <span className="text-amber-400 text-[11px] flex items-center gap-1">
                    <Clock className="w-3 h-3 animate-spin" /> Pending
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded-lg p-5 space-y-6 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.06]">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-base font-semibold text-[#f3f3f4]">
              Strict BSP Barrier Status
            </h3>
            <span className="font-mono text-xs text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20 font-medium">
              Step #{currentStep.operationId}
            </span>
            <Badge variant={isCommitted ? 'success' : 'warning'}>
              {isCommitted ? 'Synchronized' : 'Barrier Wait In Progress'}
            </Badge>
          </div>
          <p className="text-xs text-[#a1a1a8] mt-1">
            Deterministic Bulk Synchronous Parallelism barrier. Every worker must contribute verified gradients before parameters are updated.
          </p>
        </div>

        <div className="flex items-center gap-4 text-xs font-medium">
          <div className="text-right">
            <div className="text-[#73737c]">Barrier Wait Time</div>
            <div className="text-[#f3f3f4] font-mono mt-0.5">{barrierWaitMs} ms</div>
          </div>
        </div>
      </div>

      {/* Primary Status Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#171719] rounded-md p-3.5 border border-white/[0.04]">
          <div className="text-xs text-[#73737c]">Gradient Contributions</div>
          <div className="text-xl font-bold text-[#f3f3f4] mt-1">
            {acceptedCount} <span className="text-sm text-[#73737c] font-normal">/ {expectedWorkers} workers</span>
          </div>
          <div className="text-xs text-[#a1a1a8] mt-1">
            {acceptedCount === expectedWorkers
              ? 'All 3 worker gradients verified and accepted'
              : `Awaiting gradients from ${expectedWorkers - acceptedCount} worker`}
          </div>
        </div>

        <div className="bg-[#171719] rounded-md p-3.5 border border-white/[0.04]">
          <div className="text-xs text-[#73737c]">Parameter Application</div>
          <div className="text-xl font-bold text-[#f3f3f4] mt-1">
            {parameterAppliedCount} <span className="text-sm text-[#73737c] font-normal">/ {expectedWorkers} workers</span>
          </div>
          <div className="text-xs text-[#a1a1a8] mt-1">
            {parameterAppliedCount === expectedWorkers
              ? 'Weight tensors applied across all workers'
              : 'Waiting for aggregation commit'}
          </div>
        </div>

        <div className="bg-[#171719] rounded-md p-3.5 border border-white/[0.04]">
          <div className="text-xs text-[#73737c]">Step Synchronization</div>
          <div className="text-xl font-bold text-emerald-400 mt-1">
            {isCommitted ? 'Committed' : 'Collecting'}
          </div>
          <div className="text-xs text-[#a1a1a8] mt-1">
            Model version output: <span className="font-mono text-blue-400 font-medium">v{currentStep.outputModelVersion}</span>
          </div>
        </div>
      </div>

      {/* Pipeline Stage Progression */}
      <div className="space-y-2">
        <div className="text-xs font-medium text-[#73737c]">
          Step Execution Pipeline
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
          {STAGES.map((stage) => {
            const status = getStageStatus(stage.id);
            return (
              <div
                key={stage.id}
                className={`p-3 rounded-md border transition-colors ${
                  status === 'active'
                    ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                    : status === 'completed'
                    ? 'bg-[#171719] border-white/[0.06] text-emerald-400'
                    : 'bg-[#171719] border-white/[0.03] text-[#73737c]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{stage.label}</span>
                  {status === 'completed' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                  {status === 'active' && <Clock className="w-3.5 h-3.5 text-amber-400 animate-spin" />}
                </div>
                <div className="text-[11px] text-[#73737c] mt-1 line-clamp-2">
                  {stage.description}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Detailed Worker Contribution Grid */}
      <div className="space-y-3 pt-2">
        <div className="text-xs font-medium text-[#73737c]">
          Worker Barrier Contributions
        </div>
        <div className="divide-y divide-white/[0.04] border border-white/[0.06] rounded-md bg-[#171719] overflow-hidden">
          {contributions.map((c) => {
            const worker = workers.find(w => w.workerId === c.workerId);
            return (
              <div
                key={c.workerId}
                className="p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-white/[0.06] flex items-center justify-center font-semibold text-[#f3f3f4]">
                    {c.workerId}
                  </div>
                  <div>
                    <div className="font-semibold text-[#f3f3f4]">Worker {c.workerId}</div>
                    <div className="text-[11px] text-[#73737c] font-mono">
                      {worker?.nodeLabel || 'node-0'} • Session {c.sessionId.slice(0, 12)}...
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-6 text-[#a1a1a8]">
                  <div>
                    <span className="text-[#73737c]">Batch:</span> <span className="font-mono text-[#f3f3f4]">{c.batchId}</span>
                  </div>
                  <div>
                    <span className="text-[#73737c]">Samples:</span> <span className="font-semibold text-[#f3f3f4]">{c.sampleCount}</span>
                  </div>
                  <div>
                    {c.contributionAccepted ? (
                      <span className="inline-flex items-center gap-1.5 text-emerald-400 font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Gradient Accepted
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-amber-400 font-medium">
                        <Clock className="w-3.5 h-3.5 animate-spin" />
                        Computing Gradient
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
