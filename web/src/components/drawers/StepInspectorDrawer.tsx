import React, { useState, useEffect } from 'react';
import { Drawer } from '../common/Drawer';
import { TrainingStep } from '../../types';
import { StepDetailData } from '../../types/api';
import { StepStateBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { stepsService } from '../../api';
import {
  Layers,
  Clock,
  Cpu,
  CheckCircle2,
  AlertCircle,
  TrendingDown,
  TrendingUp,
  RefreshCw,
  Zap,
  ArrowRight,
  HardDrive,
} from 'lucide-react';

interface StepInspectorDrawerProps {
  step: TrainingStep | null;
  attemptId?: string | null;
  onClose: () => void;
}

function formatBytes(bytes?: number | null): string {
  if (bytes === undefined || bytes === null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatMs(ms?: number | null): string {
  if (ms === undefined || ms === null) return '—';
  return `${ms.toFixed(1)} ms`;
}

function formatIso(iso?: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toISOString().replace('T', ' ').replace('Z', ' UTC');
  } catch {
    return iso;
  }
}

export const StepInspectorDrawer: React.FC<StepInspectorDrawerProps> = ({
  step,
  attemptId,
  onClose,
}) => {
  const [detail, setDetail] = useState<StepDetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveAttemptId = attemptId || step?.attemptId;
  const effectiveStepId = step?.stepId ?? step?.operationId;

  useEffect(() => {
    if (!step || !effectiveAttemptId || effectiveStepId === undefined) {
      setDetail(null);
      return;
    }

    let isMounted = true;
    const fetchDetail = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await stepsService.getStep(effectiveAttemptId, effectiveStepId);
        if (isMounted) {
          setDetail(res.data);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err?.message || 'Could not fetch step details');
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchDetail();

    return () => {
      isMounted = false;
    };
  }, [step, effectiveAttemptId, effectiveStepId]);

  if (!step) return null;

  // Use API detail if available, otherwise fall back to step props
  const state = detail?.state || step.state;
  const epoch = detail?.epoch ?? step.epoch;
  const batchOrdinal = detail?.batch_ordinal ?? step.batchOrdinal;
  const inputModelVersion = detail?.input_model_version ?? step.inputModelVersion;
  const outputModelVersion =
    detail?.output_model_version ?? step.outputModelVersion ?? (Number(inputModelVersion) + 1);
  const totalSamples = detail?.total_sample_count ?? step.totalSampleCount ?? 0;
  const trainingStrategy = detail?.training_strategy || step.trainingStrategy || 'strict_bsp';

  // Metrics (Loss & Accuracy)
  const loss = detail?.metrics?.loss ?? step.loss ?? step.metrics?.loss;
  const accuracy = detail?.metrics?.accuracy ?? step.accuracy ?? step.metrics?.accuracy;

  // Timings
  const timing = detail?.timing;
  const timingsFallback = step.timings;
  const startedAt = formatIso(timing?.started_at || timingsFallback?.startedAt);
  const updateCompletedAt = timing?.update_completed_at
    ? formatIso(timing.update_completed_at)
    : timingsFallback?.updateCompletedAt
      ? formatIso(timingsFallback.updateCompletedAt)
      : null;
  const synchronizationCompletedAt = timing?.synchronization_completed_at
    ? formatIso(timing.synchronization_completed_at)
    : timingsFallback?.synchronizationCompletedAt
      ? formatIso(timingsFallback.synchronizationCompletedAt)
      : null;
  const checkpointCompletedAt = timing?.checkpoint_completed_at
    ? formatIso(timing.checkpoint_completed_at)
    : timingsFallback?.checkpointCompletedAt
      ? formatIso(timingsFallback.checkpointCompletedAt)
      : null;
  const committedAt = timing?.committed_at
    ? formatIso(timing.committed_at)
    : timingsFallback?.committedAt
      ? formatIso(timingsFallback.committedAt)
      : null;

  // Worker steps list
  const workerSteps = detail?.worker_steps || [];
  const hasApiWorkerSteps = workerSteps.length > 0;

  // Aggregated Worker Telemetry totals
  const totalComputeMs = hasApiWorkerSteps
    ? workerSteps.reduce((acc, ws) => acc + (ws.compute_ms || 0), 0) / workerSteps.length
    : null;
  const totalUploadMs = hasApiWorkerSteps
    ? workerSteps.reduce((acc, ws) => acc + (ws.upload_ms || 0), 0) / workerSteps.length
    : null;
  const totalBytesTransferred = hasApiWorkerSteps
    ? workerSteps.reduce((acc, ws) => acc + (ws.bytes_sent || 0) + (ws.bytes_received || 0), 0)
    : null;

  return (
    <Drawer
      isOpen={!!step}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-blue-400" />
          <span>Step #{effectiveStepId} Telemetry Inspector</span>
        </span>
      }
      subtitle={`Attempt: ${effectiveAttemptId || '—'} • Batch Ordinal: ${batchOrdinal} • Strategy: ${trainingStrategy}`}
      widthClass="max-w-4xl"
    >
      <div className="space-y-6">
        {/* Loading / Refresh State */}
        {loading && (
          <div className="flex items-center gap-2 px-3 py-2 bg-blue-500/10 border border-blue-500/20 rounded text-xs text-blue-300">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Fetching authoritative step telemetry from API...</span>
          </div>
        )}

        {/* Overview & Metrics KPIs */}
        <div className="p-4 bg-[#171719] rounded-lg border border-white/[0.04] grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4 text-xs">
          <div>
            <div className="text-[#73737c]">Step State</div>
            <div className="mt-1.5">
              <StepStateBadge state={state} />
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Epoch / Batch</div>
            <div className="font-semibold text-[#f3f3f4] mt-1.5">
              Epoch {epoch} (b#{batchOrdinal})
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Model Version</div>
            <div className="text-blue-400 font-mono font-medium mt-1.5">
              v{inputModelVersion} → v{outputModelVersion}
            </div>
          </div>
          <div>
            <div className="text-[#73737c]">Total Samples</div>
            <div className="text-[#f3f3f4] font-semibold mt-1.5">
              {totalSamples.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-[#73737c] flex items-center gap-1">
              <TrendingDown className="w-3 h-3 text-amber-400" />
              <span>Loss</span>
            </div>
            <div className="text-amber-400 font-mono font-semibold mt-1.5">
              {loss !== undefined && loss !== null ? Number(loss).toFixed(4) : '—'}
            </div>
          </div>
          <div>
            <div className="text-[#73737c] flex items-center gap-1">
              <TrendingUp className="w-3 h-3 text-emerald-400" />
              <span>Accuracy</span>
            </div>
            <div className="text-emerald-400 font-mono font-semibold mt-1.5">
              {accuracy !== undefined && accuracy !== null ? `${Number(accuracy).toFixed(2)}%` : '—'}
            </div>
          </div>
        </div>

        {/* Summary Telemetry Badges */}
        {hasApiWorkerSteps && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div className="p-3 bg-[#171719] rounded-lg border border-white/[0.04] flex items-center justify-between">
              <div className="space-y-0.5">
                <span className="text-[#73737c] text-[11px]">Avg Training Time (Compute)</span>
                <div className="font-mono text-amber-400 font-semibold">{formatMs(totalComputeMs)}</div>
              </div>
              <Cpu className="w-4 h-4 text-amber-400/60" />
            </div>
            <div className="p-3 bg-[#171719] rounded-lg border border-white/[0.04] flex items-center justify-between">
              <div className="space-y-0.5">
                <span className="text-[#73737c] text-[11px]">Avg Pushing Time (Upload)</span>
                <div className="font-mono text-emerald-400 font-semibold">{formatMs(totalUploadMs)}</div>
              </div>
              <Zap className="w-4 h-4 text-emerald-400/60" />
            </div>
            <div className="p-3 bg-[#171719] rounded-lg border border-white/[0.04] flex items-center justify-between">
              <div className="space-y-0.5">
                <span className="text-[#73737c] text-[11px]">Total Step Network Transfer</span>
                <div className="font-mono text-blue-400 font-semibold">{formatBytes(totalBytesTransferred)}</div>
              </div>
              <HardDrive className="w-4 h-4 text-blue-400/60" />
            </div>
          </div>
        )}

        {/* Detailed Timestamps Timeline */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-[#f3f3f4] flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-[#a1a1a8]" />
              <span>Strict BSP Step Timestamps</span>
            </h3>
            {timing?.started_at && timing?.committed_at && (
              <span className="text-xs text-blue-400 font-mono font-medium">
                Total:{' '}
                {Math.max(
                  0,
                  new Date(timing.committed_at).getTime() - new Date(timing.started_at).getTime()
                )}{' '}
                ms
              </span>
            )}
          </div>

          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Started At</span>
              <span className="text-[#f3f3f4] font-mono">{startedAt}</span>
            </div>
            {updateCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Update Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{updateCompletedAt}</span>
              </div>
            )}
            {synchronizationCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Synchronization Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{synchronizationCompletedAt}</span>
              </div>
            )}
            {checkpointCompletedAt && (
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#73737c]">Checkpoint Completed At</span>
                <span className="text-[#a1a1a8] font-mono">{checkpointCompletedAt}</span>
              </div>
            )}
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Committed At</span>
              <span className="text-[#f3f3f4] font-mono">
                {committedAt || 'In Progress (Awaiting Barrier)'}
              </span>
            </div>
          </div>
        </div>

        {/* Per-Worker Step Contribution & Telemetry Table */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-[#f3f3f4] flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5 text-[#a1a1a8]" />
              <span>
                Worker Execution Telemetry & Barrier Gates (
                {hasApiWorkerSteps ? workerSteps.length : (step.workerContributions || []).length})
              </span>
            </h3>
            <span className="text-[11px] text-[#73737c]">
              Strict BSP Gradient Barrier
            </span>
          </div>

          <div className="overflow-x-auto bg-[#171719] rounded-lg border border-white/[0.04]">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-[#73737c]">
                  <th className="py-2.5 px-3 font-medium">Worker</th>
                  <th className="py-2.5 px-3 font-medium">Session ID</th>
                  <th className="py-2.5 px-3 font-medium">Shard / Batch</th>
                  <th className="py-2.5 px-3 font-medium text-right">Samples</th>
                  <th className="py-2.5 px-3 font-medium text-right">Training Time</th>
                  <th className="py-2.5 px-3 font-medium text-right">Pushing Time</th>
                  <th className="py-2.5 px-3 font-medium text-right">Apply Time</th>
                  <th className="py-2.5 px-3 font-medium text-right">Loss / Acc</th>
                  <th className="py-2.5 px-3 font-medium text-right">Network I/O</th>
                  <th className="py-2.5 px-3 font-medium text-right">Gates</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {hasApiWorkerSteps ? (
                  workerSteps.map((ws) => (
                    <tr key={ws.worker_id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="py-2.5 px-3 text-[#f3f3f4] font-semibold">
                        Worker {ws.worker_id}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] font-mono text-[11px]">
                        <CopyableId value={ws.session_id} truncateLength={10} />
                      </td>
                      <td className="py-2.5 px-3 text-blue-400 font-mono text-[11px]">
                        shard-{ws.shard_id ?? 0} <span className="text-[#73737c]">b#{ws.batch_id ?? '—'}</span>
                      </td>
                      <td className="py-2.5 px-3 text-[#f3f3f4] text-right font-medium font-mono">
                        {(ws.sample_count || 0).toLocaleString()}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-amber-400 font-medium">
                        {formatMs(ws.compute_ms)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-emerald-400 font-medium">
                        {formatMs(ws.upload_ms)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[#a1a1a8]">
                        {formatMs(ws.parameter_apply_ms)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[11px]">
                        {ws.loss !== undefined && ws.loss !== null ? (
                          <span className="text-amber-300">{Number(ws.loss).toFixed(2)}</span>
                        ) : (
                          '—'
                        )}
                        {' / '}
                        {ws.accuracy !== undefined && ws.accuracy !== null ? (
                          <span className="text-emerald-300">{Number(ws.accuracy).toFixed(1)}%</span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[11px] text-[#73737c]">
                        ↑{formatBytes(ws.bytes_sent)} ↓{formatBytes(ws.bytes_received)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <span
                            className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-sm ${
                              ws.contribution_accepted
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                            }`}
                            title="Contribution Gate"
                          >
                            {ws.contribution_accepted ? (
                              <CheckCircle2 className="w-2.5 h-2.5" />
                            ) : (
                              <AlertCircle className="w-2.5 h-2.5" />
                            )}
                            <span>{ws.contribution_accepted ? 'ACCEPTED' : 'PENDING'}</span>
                          </span>

                          <span
                            className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-sm ${
                              ws.parameter_applied
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-zinc-800 text-zinc-400 border border-zinc-700/30'
                            }`}
                            title="Parameter Applied Gate"
                          >
                            {ws.parameter_applied ? (
                              <CheckCircle2 className="w-2.5 h-2.5" />
                            ) : (
                              <AlertCircle className="w-2.5 h-2.5" />
                            )}
                            <span>{ws.parameter_applied ? 'APPLIED' : 'WAITING'}</span>
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  (step.workerContributions || []).map((w) => (
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
                      <td className="py-2.5 px-3 text-[#f3f3f4] text-right font-medium font-mono">
                        {(w.sampleCount ?? w.samples ?? 0).toLocaleString()}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-amber-400 font-medium">
                        {formatMs(w.computeMs)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-emerald-400 font-medium">
                        {formatMs(w.uploadMs)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[#a1a1a8]">
                        {formatMs(w.parameterApplyMs)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[11px]">
                        {w.loss !== undefined && w.loss !== null ? w.loss.toFixed(2) : '—'} /{' '}
                        {w.accuracy !== undefined && w.accuracy !== null ? `${w.accuracy.toFixed(1)}%` : '—'}
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono text-[11px] text-[#73737c]">
                        ↑{formatBytes(w.bytesSent)} ↓{formatBytes(w.bytesReceived)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <span
                            className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-sm ${
                              w.contributionAccepted
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                            }`}
                          >
                            <span>{w.contributionAccepted ? 'ACCEPTED' : 'PENDING'}</span>
                          </span>
                          <span
                            className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-sm ${
                              w.parameterApplied
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-zinc-800 text-zinc-400 border border-zinc-700/30'
                            }`}
                          >
                            <span>{w.parameterApplied ? 'APPLIED' : 'WAITING'}</span>
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
