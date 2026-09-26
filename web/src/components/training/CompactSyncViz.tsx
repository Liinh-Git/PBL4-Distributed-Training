import React, { useMemo } from 'react';
import { TrainingStep, WorkerSession } from '../../types';
import { StrategyStateStrictBSPData, WorkerSessionItemData } from '../../types/api';
import { ChevronRight } from 'lucide-react';

export interface CompactSyncVizProps {
  currentStep?: TrainingStep | null;
  workers: (WorkerSession | WorkerSessionItemData)[];
  expectedWorkers?: number | null;
  strategyState?: StrategyStateStrictBSPData | null;
  onOpenDetails: () => void;
}

export const CompactSyncViz: React.FC<CompactSyncVizProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  strategyState,
  onOpenDetails,
}) => {
  const contributions = currentStep?.workerContributions || [];

  // Derive synchronization metrics strictly from authoritative strategy_state when available
  const hasStrategyState = Boolean(strategyState);

  const acceptedCount = hasStrategyState
    ? (strategyState?.accepted_contribution_count ?? null)
    : (contributions.length > 0
        ? contributions.filter(c => c.contributionAccepted).length
        : null);

  const expectedCount = hasStrategyState
    ? (strategyState?.expected_contribution_count ?? expectedWorkers ?? null)
    : (expectedWorkers ?? null);

  const isSyncComplete = hasStrategyState
    ? Boolean(strategyState?.synchronization_complete)
    : (currentStep?.state === 'COMMITTED');

  // Honest display: If neither strategyState nor contribution data is available, do not fake 3/3
  const isTelemetryAvailable = hasStrategyState || currentStep != null;

  let statusText: string;
  let badgeColor: string;
  let countText: string;

  if (!isTelemetryAvailable || (acceptedCount === null && !isSyncComplete)) {
    statusText = 'Synchronization telemetry unavailable';
    badgeColor = 'bg-zinc-500';
    countText = 'Unknown / Unavailable';
  } else if (isSyncComplete) {
    statusText = 'Synchronization complete';
    badgeColor = 'bg-emerald-400';
    countText = expectedCount != null
      ? `${expectedCount} of ${expectedCount} contributions applied`
      : 'All contributions applied';
  } else {
    statusText = 'Waiting for worker contributions';
    badgeColor = 'bg-amber-400';
    if (acceptedCount != null && expectedCount != null) {
      countText = `${acceptedCount} of ${expectedCount} gradients received`;
    } else if (acceptedCount != null) {
      countText = `${acceptedCount} gradients received`;
    } else {
      countText = 'Waiting for gradients';
    }
  }

  // Merge observed worker sessions with expected worker slots so the display is never missing workers
  const displayWorkers = useMemo(() => {
    const total = expectedCount ?? (workers.length > 0 ? workers.length : 3);
    const observedMap = new Map<number, any>();
    workers.forEach((w: any) => {
      const id = w.workerId ?? w.worker_id;
      if (id !== undefined && id !== null) {
        observedMap.set(Number(id), w);
      }
    });

    const items = [];
    for (let id = 0; id < total; id++) {
      const observed = observedMap.get(id);
      const contrib = contributions.find(c => c.workerId === id);

      let itemStatus = 'Waiting';
      let itemClass = 'text-amber-400 font-mono';

      if (isSyncComplete) {
        itemStatus = 'Received';
        itemClass = 'text-emerald-400 font-mono';
      } else if (contrib?.contributionAccepted === true) {
        itemStatus = 'Received';
        itemClass = 'text-emerald-400 font-mono';
      } else if (contrib?.contributionAccepted === false) {
        itemStatus = 'Pending';
        itemClass = 'text-amber-400 font-mono';
      } else if (acceptedCount != null && expectedCount != null) {
        // If strategyState tells us how many have been accepted (e.g. 2 of 3)
        if (id < acceptedCount) {
          itemStatus = 'Received';
          itemClass = 'text-emerald-400 font-mono';
        } else {
          itemStatus = 'Waiting';
          itemClass = 'text-amber-400 font-mono';
        }
      }

      items.push({
        workerId: id,
        isObserved: Boolean(observed),
        status: itemStatus,
        itemClass,
      });
    }
    return items;
  }, [expectedCount, workers, contributions, isSyncComplete, acceptedCount]);

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
          <span className={`w-1.5 h-1.5 rounded-full ${badgeColor} shrink-0`} />
          <span>{statusText}</span>
        </div>
        <div className="text-xs text-[#73737c]">
          {countText}
        </div>
      </div>

      {/* Flat worker rows with subtle separators */}
      <div className="divide-y divide-white/[0.04] pt-1">
        {displayWorkers.map((item) => (
          <div
            key={item.workerId}
            className="flex items-center justify-between py-2 text-xs"
          >
            <div className="flex items-center gap-2">
              <span className="text-[#f3f3f4]">Worker {item.workerId}</span>
              {!item.isObserved && (
                <span className="text-[10px] text-[#73737c]" title="Participating in DTP training data plane">(DTP active)</span>
              )}
            </div>
            <span className={item.itemClass}>
              {item.status}
            </span>
          </div>
        ))}
      </div>

      {expectedCount != null && workers.length < expectedCount && (
        <div className="text-[11px] text-amber-400/90 pt-1 border-t border-white/[0.04]">
          Partial session telemetry: {workers.length} of {expectedCount} sessions observed
        </div>
      )}

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
