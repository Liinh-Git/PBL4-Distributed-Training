import React from 'react';
import { Drawer } from '../common/Drawer';
import { TrainingStep } from '../../types';
import { StepStateBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { Layers, Clock, Cpu, CheckCircle2, AlertCircle } from 'lucide-react';

interface StepInspectorDrawerProps {
  step: TrainingStep | null;
  onClose: () => void;
}

export const StepInspectorDrawer: React.FC<StepInspectorDrawerProps> = ({
  step,
  onClose,
}) => {
  if (!step) return null;

  const timings = step.timings;

  return (
    <Drawer
      isOpen={!!step}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-blue-400" />
          <span>Step #{step.operationId} Inspector</span>
        </span>
      }
      subtitle={`Attempt: ${step.attemptId} • Batch Ordinal: ${step.batchOrdinal}`}
      widthClass="max-w-2xl"
    >
      <div className="space-y-6">
        {/* Overview Banner */}
        <div className="p-4 bg-[#171719] rounded-lg border border-white/[0.04] grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
          <div>
            <div className="text-[#73737c]">Step State</div>
            <div className="mt-1.5">
              <StepStateBadge state={step.state} />
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Epoch / Batch</div>
            <div className="font-semibold text-[#f3f3f4] mt-1.5">
              Epoch {step.epoch} (b#{step.batchOrdinal})
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Model Transition</div>
            <div className="text-blue-400 font-mono font-medium mt-1.5">
              v{step.inputModelVersion} → v{step.outputModelVersion}
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Total Sample Count</div>
            <div className="text-[#f3f3f4] font-semibold mt-1.5">
              {step.totalSampleCount.toLocaleString()}
            </div>
          </div>
        </div>

        {/* Timestamps */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-[#f3f3f4] flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-[#a1a1a8]" />
              <span>Strict BSP Step Timestamps</span>
            </h3>
            <span className="text-xs text-[#a1a1a8] font-mono">
              Duration: {timings.totalDurationMs ? `${timings.totalDurationMs} ms` : 'In progress'}
            </span>
          </div>

          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Started At</span>
              <span className="text-[#f3f3f4] font-mono">{timings.startedAt}</span>
            </div>
            {timings.updateCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Update Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{timings.updateCompletedAt}</span>
              </div>
            )}
            {timings.synchronizationCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Synchronization Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{timings.synchronizationCompletedAt}</span>
              </div>
            )}
            {timings.checkpointCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Checkpoint Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{timings.checkpointCompletedAt}</span>
              </div>
            )}
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Committed At</span>
              <span className="text-[#f3f3f4] font-mono">
                {timings.committedAt || 'In Progress (Awaiting Barrier)'}
              </span>
            </div>
          </div>
        </div>

        {/* Per-Worker Step Contribution Table */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4] flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5 text-[#a1a1a8]" />
            <span>Worker Synchronization Barrier Gates ({(step.workerContributions || []).length})</span>
          </h3>

          <div className="overflow-x-auto bg-[#171719] rounded-lg border border-white/[0.04]">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[#73737c]">
                  <th className="py-2.5 px-3 font-medium">Worker</th>
                  <th className="py-2.5 px-3 font-medium">Session</th>
                  <th className="py-2.5 px-3 font-medium">Shard</th>
                  <th className="py-2.5 px-3 font-medium text-right">Samples</th>
                  <th className="py-2.5 px-3 font-medium text-right">Contribution Gate</th>
                  <th className="py-2.5 px-3 font-medium text-right">Parameter Gate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {(step.workerContributions || []).map(w => (
                  <tr key={w.workerId} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-2.5 px-3 text-[#f3f3f4] font-semibold">
                      Worker {w.workerId}
                    </td>
                    <td className="py-2.5 px-3 text-[#73737c] font-mono text-[11px]">
                      <CopyableId value={w.sessionId} truncateLength={10} />
                    </td>
                    <td className="py-2.5 px-3 text-blue-400 font-mono text-[11px]">
                      {w.shardId || '—'}
                    </td>
                    <td className="py-2.5 px-3 text-[#f3f3f4] text-right font-medium">
                      {(w.sampleCount ?? w.samples ?? 0).toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <span
                        className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-sm ${
                          w.contributionAccepted
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                        }`}
                      >
                        {w.contributionAccepted ? (
                          <CheckCircle2 className="w-3 h-3" />
                        ) : (
                          <AlertCircle className="w-3 h-3" />
                        )}
                        <span>{w.contributionAccepted ? 'ACCEPTED' : 'PENDING'}</span>
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <span
                        className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-sm ${
                          w.parameterApplied
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-zinc-800 text-zinc-400 border border-zinc-700/30'
                        }`}
                      >
                        {w.parameterApplied ? (
                          <CheckCircle2 className="w-3 h-3" />
                        ) : (
                          <AlertCircle className="w-3 h-3" />
                        )}
                        <span>{w.parameterApplied ? 'APPLIED' : 'WAITING'}</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
