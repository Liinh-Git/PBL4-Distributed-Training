import React, { useMemo, useRef, useEffect } from 'react';
import {
  Terminal,
  CheckCircle2,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { TrainingStep, WorkerSession, Attempt } from '../../types';
import { StrategyStateStrictBSPData, StepListItemData } from '../../types/api';
import { EpochMetricData } from '../charts/LiveTrainingCharts';
import { getPreparationStatus } from '../../utils/preparation';

export interface TrainingTopologyVisualizerProps {
  currentStep?: TrainingStep | null;
  workers: WorkerSession[];
  expectedWorkers: number;
  attempt?: Attempt | null;
  strategyState?: StrategyStateStrictBSPData | null;
  isStale?: boolean;
  isSimulating?: boolean;
  onToggleSimulating?: () => void;
  onSelectWorker?: (worker: WorkerSession) => void;
  // Terminal training telemetry props
  epochMetrics?: EpochMetricData[];
  jobDisplayName?: string | null;
  totalEpochs?: number;
  stepsHistory?: StepListItemData[];
  snapshot?: any;
}

/**
 * Format accuracy percentage without abbreviations
 */
function formatAccuracy(acc: number | null | undefined): string | null {
  if (acc == null) return null;
  if (acc > 1) {
    return `${acc.toFixed(2)}%`;
  }
  return `${(acc * 100).toFixed(2)}%`;
}

/**
 * Jupyter Notebook / Colab Terminal Component
 * Features:
 * - Dedicated scroll container (max-h-[360px]) with auto-scroll to latest active line
 * - Graphical & numerical progress bar for active running epoch (never disappears while active)
 * - Accurate realtime epoch progress % calculated from actual step & batch ordinal
 * - Crisp monospace font size
 * - No arbitrary prefix (removed 'Kiểm -')
 * - Full words without abbreviations (accuracy, loss, samples, status)
 * - Rich metrics: batch progress, sample counts, step compute duration, StrictBSP barrier state
 */
export const TrainingTopologyVisualizer: React.FC<TrainingTopologyVisualizerProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  attempt,
  strategyState,
  isStale = false,
  epochMetrics = [],
  jobDisplayName,
  totalEpochs = 10,
  stepsHistory = [],
  snapshot,
}) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const preparation = getPreparationStatus(attempt?.state || 'RUNNING', workers);

  const total = totalEpochs > 0 ? totalEpochs : 10;
  const totalDigits = total >= 100 ? 3 : total >= 10 ? 2 : 1;
  const formatEpoch = (ep: number) => String(ep).padStart(totalDigits, '0');
  const totalFormatted = formatEpoch(total);

  // Derive Clean Header Prompt (No awkward cuts)
  const headerPrompt = useMemo(() => {
    if (jobDisplayName) {
      const trimmed = jobDisplayName.trim();
      return trimmed.startsWith('Huấn luyện')
        ? `${trimmed}... (Tổng số: ${total} epochs)`
        : `Huấn luyện mô hình: ${trimmed}... (Tổng số: ${total} epochs)`;
    }
    return `Huấn luyện mô hình phân tán... (Tổng số: ${total} epochs)`;
  }, [jobDisplayName, total]);

  // Completed Epochs List (Frozen lines without progress bar, full words, no abbreviations)
  const completedEpochLines = useMemo(() => {
    if (!epochMetrics || epochMetrics.length === 0) return [];
    return [...epochMetrics]
      .sort((a, b) => a.epoch_index - b.epoch_index)
      .map((m) => {
        const epochNum = m.epoch_index + 1; // 1-indexed for display
        const epochStr = formatEpoch(epochNum);
        const lossStr = m.training_loss != null ? m.training_loss.toFixed(4) : '—';
        const accFormatted = formatAccuracy(m.training_accuracy);
        const accPart = accFormatted ? ` - accuracy = ${accFormatted}` : '';
        const samplesPart = m.sample_count > 0 ? ` - số mẫu: ${m.sample_count.toLocaleString()}` : '';

        return {
          epochNum,
          text: `Epoch ${epochStr}/${totalFormatted}: loss = ${lossStr}${accPart}${samplesPart}`,
        };
      });
  }, [epochMetrics, totalFormatted, totalDigits]);

  // Lifecycle states
  const isCompleted = attempt?.state === 'COMPLETED';
  const isFailed = attempt?.state === 'FAILED' || attempt?.state === 'ABORTED';
  const isRunning = !isCompleted && !isFailed;
  const isPreparing = preparation.preparing && !isStale && !isCompleted && !isFailed;

  // Active Running Epoch Number (1-indexed for display)
  // Guarantee activeEpochNum is ALWAYS strictly greater than completedEpochLines.length
  // so the active progress bar never gets hidden prematurely
  const activeEpochNum = useMemo(() => {
    const stepEpoch =
      typeof (currentStep as any)?.epoch === 'number'
        ? (currentStep as any).epoch + 1
        : null;
    const snapshotEpoch =
      snapshot?.epoch != null
        ? Number(snapshot.epoch) + 1
        : null;
    const attemptEpoch =
      attempt?.epoch != null
        ? Number(attempt.epoch) + 1
        : null;

    const observedMax = Math.max(
      stepEpoch ?? 1,
      snapshotEpoch ?? 1,
      attemptEpoch ?? 1,
      completedEpochLines.length + 1
    );

    return observedMax;
  }, [currentStep, snapshot?.epoch, attempt?.epoch, completedEpochLines.length]);

  // Pinned total batches in epoch (guaranteed stable across step lifecycles)
  const pinnedTotalBatchesRef = useRef<number>(48);

  const resolvedTotalBatches = useMemo(() => {
    // 1. From max observed batch_ordinal in steps history (authoritative)
    if (stepsHistory && stepsHistory.length > 0) {
      const maxOrdinal = stepsHistory.reduce((max, s) => Math.max(max, s.batch_ordinal ?? -1), -1);
      if (maxOrdinal > 0) {
        pinnedTotalBatchesRef.current = Math.max(pinnedTotalBatchesRef.current, maxOrdinal + 1);
        return pinnedTotalBatchesRef.current;
      }
    }

    // 2. From completed epoch metrics sample count if known
    if (epochMetrics && epochMetrics.length > 0 && epochMetrics[0].sample_count > 0) {
      const sampleCount = epochMetrics[0].sample_count;
      // In PBL4, standard batch_size is 64 samples per step
      const calculated = Math.round(sampleCount / 64);
      if (calculated > 0 && calculated <= 1000) {
        pinnedTotalBatchesRef.current = Math.max(pinnedTotalBatchesRef.current, calculated);
        return pinnedTotalBatchesRef.current;
      }
    }

    return pinnedTotalBatchesRef.current;
  }, [stepsHistory, epochMetrics]);

  // Realtime Batch Ordinal for the active epoch
  const currentBatchOrdinal = useMemo(() => {
    if (currentStep) {
      const stepEpoch = (currentStep as any).epoch;
      if (typeof stepEpoch === 'number' && stepEpoch === activeEpochNum - 1) {
        const val = (currentStep as any).batchOrdinal ?? (currentStep as any).batch_ordinal;
        if (typeof val === 'number' && val >= 0) return val;
      }
    }
    if (snapshot?.epoch != null && Number(snapshot.epoch) === activeEpochNum - 1) {
      if (snapshot.current_batch_ordinal != null) {
        const val = Number(snapshot.current_batch_ordinal);
        if (val >= 0) return val;
      }
    }
    // Fallback: check raw values if epoch matches
    const rawEpoch = (currentStep as any)?.epoch ?? snapshot?.epoch;
    if (rawEpoch != null && Number(rawEpoch) === activeEpochNum - 1) {
      const fallbackVal = (currentStep as any)?.batchOrdinal ?? (currentStep as any)?.batch_ordinal;
      if (typeof fallbackVal === 'number' && fallbackVal >= 0) return fallbackVal;
    }

    return 0;
  }, [currentStep, snapshot, activeEpochNum]);

  const rawBatch = currentBatchOrdinal + 1;

  // Monotonic linear progress tracking (strictly non-decreasing within an epoch)
  const lastProgressRef = useRef<{ epoch: number; maxBatch: number; maxPercent: number }>({
    epoch: 0,
    maxBatch: 0,
    maxPercent: 0,
  });

  const { progressPercent, progressText, currentBatch } = useMemo(() => {
    const total = resolvedTotalBatches > 0 ? resolvedTotalBatches : 48;

    // Reset when moving to a new epoch
    if (lastProgressRef.current.epoch !== activeEpochNum) {
      const initialPercent = Math.min(100, Math.max(1, Math.round((Math.min(rawBatch, total) / total) * 100)));
      lastProgressRef.current = {
        epoch: activeEpochNum,
        maxBatch: Math.min(rawBatch, total),
        maxPercent: initialPercent,
      };
    }

    // Ensure batch ordinal and percentage NEVER decrease within the active epoch
    const monotonicBatch = Math.max(lastProgressRef.current.maxBatch, rawBatch);
    const clampedBatch = Math.min(monotonicBatch, total);

    const calculatedPercent = Math.min(100, Math.max(1, Math.round((clampedBatch / total) * 100)));
    const monotonicPercent = Math.max(lastProgressRef.current.maxPercent, calculatedPercent);

    // Save high-water mark for this epoch
    lastProgressRef.current.maxBatch = clampedBatch;
    lastProgressRef.current.maxPercent = monotonicPercent;

    return {
      progressPercent: monotonicPercent,
      progressText: `${clampedBatch}/${total}`,
      currentBatch: clampedBatch,
    };
  }, [activeEpochNum, rawBatch, resolvedTotalBatches]);

  // Progress Bar ASCII (10 characters for tight square aspect ratio)
  const progressBar = useMemo(() => {
    const barLength = 10;
    const filled = Math.min(barLength, Math.max(0, Math.round((progressPercent / 100) * barLength)));
    const empty = barLength - filled;
    return '█'.repeat(filled) + '░'.repeat(empty);
  }, [progressPercent]);

  // Worker contributions & timings
  const contribs = useMemo<any[]>(() => {
    return (currentStep as any)?.workerContributions ?? (currentStep as any)?.contributions ?? [];
  }, [currentStep]);

  // Step Loss
  const currentStepLoss = useMemo(() => {
    if (currentStep?.metrics?.loss != null) {
      return currentStep.metrics.loss.toFixed(4);
    }
    if ((currentStep as any)?.loss != null) {
      return Number((currentStep as any).loss).toFixed(4);
    }
    const valid = contribs.map((c) => c.loss).filter((l): l is number => typeof l === 'number');
    if (valid.length > 0) {
      const avg = valid.reduce((a, b) => a + b, 0) / valid.length;
      return avg.toFixed(4);
    }
    return null;
  }, [currentStep, contribs]);

  // Step Compute Duration / Speed (in ms)
  const stepComputeMs = useMemo(() => {
    const timingMs = (currentStep as any)?.timings?.totalDurationMs;
    if (typeof timingMs === 'number' && timingMs > 0) return Math.round(timingMs);

    const validComputes = contribs
      .map((c) => c.computeMs)
      .filter((t): t is number => typeof t === 'number' && t > 0);
    if (validComputes.length > 0) {
      return Math.round(validComputes.reduce((a, b) => a + b, 0) / validComputes.length);
    }
    return null;
  }, [currentStep, contribs]);

  // Step Samples Count in Current Epoch
  const sampleProgress = useMemo(() => {
    const stepSampleCount =
      (currentStep as any)?.totalSampleCount ??
      (currentStep as any)?.total_sample_count ??
      (contribs.length > 0
        ? contribs.reduce((sum, c) => sum + (c.sampleCount || c.samples || 0), 0)
        : null);

    const totalSamplesInEpoch =
      epochMetrics.length > 0 && epochMetrics[0].sample_count > 0
        ? epochMetrics[0].sample_count
        : stepSampleCount && resolvedTotalBatches
        ? stepSampleCount * resolvedTotalBatches
        : null;

    if (stepSampleCount && totalSamplesInEpoch) {
      const currentProcessed = Math.min(totalSamplesInEpoch, currentBatch * stepSampleCount);
      return `${currentProcessed.toLocaleString()}/${totalSamplesInEpoch.toLocaleString()}`;
    }
    return null;
  }, [currentStep, contribs, epochMetrics, currentBatch, resolvedTotalBatches]);

  // StrictBSP Waiting / Gate Status Text (Full words, no abbreviations)
  const barrierStatusText = useMemo(() => {
    if (!currentStep) return '';
    const acceptedIds = new Set(
      contribs.filter((c) => c.contributionAccepted === true).map((c) => c.workerId)
    );
    const waitingWorkers = workers.filter((w) => !acceptedIds.has(w.workerId));

    const isCollecting = strategyState?.state === 'COLLECTING' || !strategyState?.state;
    const isUpdating = strategyState?.state === 'UPDATING';
    const isBroadcasting = strategyState?.state === 'BROADCASTING';
    const isCommitted = currentStep.state === 'COMMITTED';

    if (isCollecting && waitingWorkers.length > 0) {
      return `[Trạng thái StrictBSP: Đang chờ ${waitingWorkers.map((w) => `Worker-${w.workerId}`).join(', ')}]`;
    }
    if (isUpdating) {
      return `[Trạng thái StrictBSP: Đang tổng hợp Gradient All-Reduce]`;
    }
    if (isBroadcasting) {
      const versionStr = currentStep.outputModelVersion || attempt?.modelVersion || '';
      return `[Trạng thái: Đang phát tán trọng số mô hình v${versionStr}]`;
    }
    if (isCommitted) {
      return `[Trạng thái: Bước hoàn tất · Sẵn sàng bước tiếp theo]`;
    }
    return `[Trạng thái StrictBSP: Đang đồng bộ]`;
  }, [currentStep, contribs, workers, strategyState, attempt?.modelVersion]);

  // Auto-scroll to bottom of the terminal on new line or batch change
  useEffect(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
  }, [completedEpochLines.length, currentBatchOrdinal, currentStep?.operationId, activeEpochNum]);

  return (
    <div className="bg-[#0b0c0e] rounded border border-white/[0.08] shadow-2xl overflow-hidden font-mono text-zinc-300">
      {/* Terminal Title Bar */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-[#121317] border-b border-white/[0.06] text-xs">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-zinc-400" />
          <span className="text-zinc-300 font-medium tracking-wide text-[11px]">Training Output</span>
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="text-zinc-400">
            Tiến độ: <strong className="text-zinc-200">Epoch {Math.min(activeEpochNum, total)}/{total}</strong>
          </span>
          <span
            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-semibold uppercase ${
              isCompleted
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : isFailed
                ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isCompleted
                  ? 'bg-emerald-400'
                  : isFailed
                  ? 'bg-rose-400'
                  : 'bg-blue-400 animate-pulse'
              }`}
            />
            <span>{attempt?.state || 'RUNNING'}</span>
          </span>
        </div>
      </div>

      {/* Terminal Body — Dedicated Scroll Area with Auto-Scroll */}
      <div
        ref={scrollContainerRef}
        className="p-3.5 sm:p-4 max-h-[360px] overflow-y-auto space-y-2 text-[11px] sm:text-xs leading-5 select-text"
        style={{ scrollBehavior: 'smooth' }}
      >
        {/* Header line */}
        <div className="text-zinc-200 font-semibold pb-1 border-b border-white/[0.04]">
          {headerPrompt}
        </div>

        {/* Completed Epochs (No progress bar, full text, no 'Kiểm -') */}
        {completedEpochLines.map((line) => (
          <div key={`completed-epoch-${line.epochNum}`} className="text-zinc-300 hover:text-zinc-100 transition-colors">
            {line.text}
          </div>
        ))}

        {/* Current Active Epoch (Rendered directly in the terminal text flow, calm & non-jittery) */}
        {isRunning && activeEpochNum <= total && (
          <div className="text-emerald-400 font-medium flex items-center gap-2 flex-wrap">
            <span>
              Epoch {formatEpoch(activeEpochNum)}/{totalFormatted}:
            </span>
            <span className="font-mono text-[10px] leading-none py-0.5 text-zinc-400 tracking-tight inline-flex items-center">
              [{progressBar}]
            </span>
            <span className="text-emerald-300 font-bold font-mono">
              {progressPercent}%
            </span>
            <span className="text-zinc-600">|</span>
            <span className="text-zinc-300 font-mono">
              batch {progressText}
            </span>
            {sampleProgress && (
              <>
                <span className="text-zinc-600">|</span>
                <span className="text-zinc-400 font-mono">
                  mẫu: {sampleProgress}
                </span>
              </>
            )}
            {currentStepLoss != null && (
              <>
                <span className="text-zinc-600">|</span>
                <span className="text-amber-300 font-mono">
                  loss = {currentStepLoss}
                </span>
              </>
            )}
            {stepComputeMs != null && (
              <>
                <span className="text-zinc-600">|</span>
                <span className="text-zinc-400 font-mono">
                  thời gian bước: {stepComputeMs}ms
                </span>
              </>
            )}
          </div>
        )}

        {/* Completed Run Message */}
        {isCompleted && (
          <div className="text-emerald-400 pt-1 flex items-center gap-1.5 font-semibold">
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            <span>
              Quá trình huấn luyện đã hoàn tất thành công. Mô hình đã sẵn sàng.
            </span>
          </div>
        )}

        {/* Failed / Aborted Run Message */}
        {isFailed && (
          <div className="text-rose-400 pt-1 flex items-center gap-1.5 font-semibold">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>
              Quá trình huấn luyện đã kết thúc ({attempt?.state}): {attempt?.failure?.message || 'Tiến trình bị dừng.'}
            </span>
          </div>
        )}

        {/* Preparing Environment Message */}
        {isPreparing && (
          <div className="text-blue-400 pt-1 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 animate-spin shrink-0" />
            <span>
              Khởi tạo giao thức DTP/1: Đang chờ kết nối cụm {expectedWorkers > 0 ? `${preparation.connected}/${expectedWorkers}` : preparation.connected} Workers...
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
