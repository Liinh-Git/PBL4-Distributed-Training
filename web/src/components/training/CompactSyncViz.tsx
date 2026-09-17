import React, { useMemo } from 'react';
import { TrainingStep, WorkerSession } from '../../types';
import { ChevronRight } from 'lucide-react';

interface CompactSyncVizProps {
  currentStep: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  onOpenDetails: () => void;
}

export const CompactSyncViz: React.FC<CompactSyncVizProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  onOpenDetails,
}) => {
  const contributions = currentStep?.workerContributions || [];

  const acceptedCount = useMemo(
    () => contributions.filter(c => c.contributionAccepted).length,
    [contributions]
  );

  const isBarrierOpen = acceptedCount >= expectedWorkers;
  const isCommitted = currentStep?.state === 'COMMITTED';

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3 font-sans select-none">
      {/* Header */}
      <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
        <h3 className="text-xs font-semibold text-[#f3f3f4]">
          Current synchronization
        </h3>
        <span className="text-[11px] text-[#73737c]">
          Strict BSP
        </span>
      </div>

      {/* Summary state */}
      <div className="space-y-0.5">
        <div className="flex items-center gap-1.5 text-xs text-[#f3f3f4]">
          {isBarrierOpen || isCommitted ? (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
          ) : (
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
          )}
          <span>{isBarrierOpen || isCommitted ? 'All workers contributed' : 'Waiting for workers'}</span>
        </div>
        <div className="text-xs text-[#73737c]">
          {acceptedCount} of {expectedWorkers} gradients received
        </div>
      </div>

      {/* Flat worker rows with subtle separators */}
      <div className="divide-y divide-white/[0.04] pt-1">
        {workers.map((w, idx) => {
          const contrib = contributions.find(c => c.workerId === w.workerId);
          const received = isCommitted || contrib?.contributionAccepted;

          return (
            <div
              key={w.workerId}
              className="flex items-center justify-between py-2 text-xs"
            >
              <span className="text-[#f3f3f4]">Worker {idx}</span>
              <span className={received ? 'text-[#a1a1a8]' : 'text-amber-400'}>
                {received ? 'Received' : 'Waiting'}
              </span>
            </div>
          );
        })}
      </div>

      {/* Subtle text link: View details */}
      <div className="pt-2 border-t border-white/[0.07]">
        <button
          type="button"
          onClick={onOpenDetails}
          className="text-xs text-[#73737c] hover:text-[#f3f3f4] inline-flex items-center gap-1 transition-colors"
        >
          <span>View details</span>
          <ChevronRight className="w-3 h-3 text-[#73737c]" />
        </button>
      </div>
    </div>
  );
};
