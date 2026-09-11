import React from 'react';
import { CheckCircle2, Clock, ArrowRight, Server, ShieldCheck } from 'lucide-react';
import { TrainingStep, WorkerSession } from '../../types';

interface WorkerLiveStripProps {
  currentStep: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  onSelectWorker: (worker: WorkerSession) => void;
  onViewDetails: () => void;
}

export const WorkerLiveStrip: React.FC<WorkerLiveStripProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  onSelectWorker,
  onViewDetails,
}) => {
  const contributions = currentStep?.workerContributions || [];
  const acceptedCount = contributions.filter(c => c.contributionAccepted).length;
  const isCommitted = currentStep?.state === 'COMMITTED';

  // Determine current sync status text
  let syncStatusText = '';
  if (isCommitted) {
    syncStatusText = 'All contributions synchronized · Parameters applied';
  } else if (acceptedCount === expectedWorkers) {
    syncStatusText = 'All contributions received · Updating global model';
  } else {
    const missingWorker = contributions.find(c => !c.contributionAccepted);
    const waitingFor = missingWorker !== undefined ? `Worker ${missingWorker.workerId}` : 'remaining workers';
    syncStatusText = `${acceptedCount} of ${expectedWorkers} contributions received · Waiting for ${waitingFor}`;
  }

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
      {/* Synchronization Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-white/[0.07]">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
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
          const hasReceived = isCommitted || contrib?.contributionAccepted;

          return (
            <div
              key={worker.workerId}
              onClick={() => onSelectWorker(worker)}
              className="p-2.5 rounded bg-[#171719] hover:bg-[#1f1f23] transition-colors cursor-pointer flex items-center justify-between group"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-[#f3f3f4] group-hover:text-white transition-colors">
                    Worker {worker.workerId}
                  </div>
                  <div className="text-[11px] text-[#73737c] truncate">
                    Ready
                  </div>
                </div>
              </div>

              <div className="shrink-0 pl-2">
                {hasReceived ? (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                    <CheckCircle2 className="w-3 h-3 shrink-0" />
                    <span>Received</span>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                    <Clock className="w-3 h-3 shrink-0 animate-spin" />
                    <span>Waiting</span>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
