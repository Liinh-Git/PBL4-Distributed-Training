import React, { useState, useMemo, useRef, useEffect } from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import {
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  TrendingDown,
  TrendingUp,
  Zap,
  Clock,
} from 'lucide-react';
import { TrainingStep } from '../../types';

export interface EpochMetricData {
  epoch_index: number;
  sample_count: number;
  training_loss?: number | null;
  training_accuracy?: number | null;
}

export interface LiveTrainingChartsProps {
  steps: TrainingStep[];
  expectedWorkers?: number;
  onViewAllMetrics?: () => void;
  epochMetrics?: EpochMetricData[];
}

export function computeEpochMetricsData(epochMetrics: EpochMetricData[] | undefined) {
  if (!epochMetrics || epochMetrics.length === 0) {
    return [];
  }
  return [...epochMetrics]
    .sort((a, b) => a.epoch_index - b.epoch_index)
    .map((em) => ({
      epochIndex: em.epoch_index,
      displayEpoch: `Epoch ${em.epoch_index + 1}`,
      epochNum: em.epoch_index + 1,
      loss: em.training_loss != null ? Number(em.training_loss.toFixed(4)) : null,
      accuracy: em.training_accuracy != null ? Number(em.training_accuracy.toFixed(2)) : null,
      sampleCount: em.sample_count,
    }));
}

/**
 * Calculates the drawing width for the chart canvas based on step count.
 * - For <= threshold steps (default: 16), returns '100%' so the chart fills its container naturally.
 * - For > threshold steps, calculates a comfortable pixel width that ensures readability
 *   without compressing points, and triggers horizontal scrolling in the parent container.
 */
export function getChartContentWidth(totalSteps: number, threshold = 16): string | number {
  if (totalSteps <= threshold) {
    return '100%';
  }
  let stepWidth = 32;
  if (totalSteps > 200) {
    stepWidth = 24;
  } else if (totalSteps > 100) {
    stepWidth = 28;
  }
  return Math.max(600, totalSteps * stepWidth);
}

/**
 * Scrollable container wrapper for Recharts time-series charts.
 * Prevents squishing points when step count is large and isolates horizontal scrolling.
 */
export interface ScrollableChartWrapperProps {
  totalSteps: number;
  height: number;
  threshold?: number;
  children: React.ReactNode;
  autoScrollToEnd?: boolean;
  className?: string;
  testId?: string;
}

export const ScrollableChartWrapper: React.FC<ScrollableChartWrapperProps> = ({
  totalSteps,
  height,
  threshold = 16,
  children,
  autoScrollToEnd = true,
  className = '',
  testId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const prevStepsCount = useRef<number>(totalSteps);
  const isInitialMount = useRef<boolean>(true);
  const isScrollable = totalSteps > threshold;
  const contentWidth = useMemo(
    () => getChartContentWidth(totalSteps, threshold),
    [totalSteps, threshold]
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !isScrollable || !autoScrollToEnd) return;

    const scrollToLatest = (behavior: ScrollBehavior = 'auto') => {
      if (!el) return;
      const targetLeft = Math.max(0, el.scrollWidth - el.clientWidth);
      if (targetLeft > 0) {
        el.scrollTo({ left: targetLeft, behavior });
      }
    };

    if (isInitialMount.current) {
      isInitialMount.current = false;
      // Immediately jump to the latest steps on initial mount
      scrollToLatest('auto');
      const rId = requestAnimationFrame(() => {
        scrollToLatest('auto');
      });
      const tId = setTimeout(() => {
        scrollToLatest('auto');
      }, 60);
      return () => {
        cancelAnimationFrame(rId);
        clearTimeout(tId);
      };
    } else if (totalSteps > prevStepsCount.current) {
      // When new steps arrive during live training, smoothly reveal latest steps
      scrollToLatest('smooth');
    }
    prevStepsCount.current = totalSteps;
  }, [totalSteps, isScrollable, autoScrollToEnd, contentWidth]);

  return (
    <div
      ref={containerRef}
      data-testid={testId}
      className={`w-full overflow-x-auto overflow-y-hidden min-w-0 ${className}`}
      style={{
        WebkitOverflowScrolling: 'touch',
      }}
    >
      <div
        style={{
          minWidth: '100%',
          width: contentWidth,
          height: `${height}px`,
        }}
      >
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </div>
  );
};

// Missing telemetry remains null; charts must never fabricate training results.
// Only COMMITTED steps are included in the training trajectory.
export function computeStepMetrics(steps: TrainingStep[]) {
  return [...steps]
    .filter((st) => st.state === 'COMMITTED')
    .sort((a, b) => (a.stepId ?? a.operationId) - (b.stepId ?? b.operationId))
    .map((st, idx) => {
      const durationMs = st.timings?.totalDurationMs;
      const samples = st.totalSampleCount;
      return {
        step: st,
        operationId: st.operationId,
        opNumber: `#${st.operationId}`,
        normalizedStep: idx,
        stepLabel: `Step ${st.stepId ?? st.operationId}`,
        displayStep: `${st.stepId ?? st.operationId}`,
        inputModelVersion: st.inputModelVersion,
        loss: st.loss ?? st.metrics?.loss ?? null,
        accuracy: st.accuracy ?? st.metrics?.accuracy ?? null,
        avgSamplesPerSec: durationMs != null && durationMs > 0 && samples != null
          ? Math.round(samples * 10000 / durationMs) / 10 : null,
        durationMs,
        acceptedWorkers: (st.workerContributions || []).filter(c => c.contributionAccepted).length,
        timeLabel: st.timings?.committedAt ?? '—',
      };
    });
}

export function computeWorkerBreakdown(step: TrainingStep | undefined, _stepIndex = 1) {
  const workers = (step?.workerContributions || []).map((c: any) => {
    const train = c.computeMs ?? c.compute_ms ?? null;
    const push = c.uploadMs ?? c.upload_ms ?? null;
    return {
      workerId: c.workerId, workerName: `Worker ${c.workerId}`,
      trainingTime: train, pushingTime: push,
      totalTime: train != null && push != null ? train + push : null,
      loss: c.loss, accuracy: c.accuracy,
      parameterApplyMs: c.parameterApplyMs ?? c.parameter_apply_ms,
      bytesSent: c.bytesSent ?? c.bytes_sent, bytesReceived: c.bytesReceived ?? c.bytes_received,
    };
  });
  return { syncMaxTime: Math.max(0, ...workers.map(w => w.totalTime ?? 0)), workers };
}

// Custom data label for Global Loss chart milestones
const renderLossLabel = (props: any) => {
  const { x, y, value, index } = props;
  if (value === undefined || value === null) return null;
  // Annotate the first measured points.
  const isKey = index === 0 || index === 1;
  if (!isKey) return null;
  return (
    <text
      x={x}
      y={y - 7}
      fill="#60a5fa"
      fontSize={11}
      fontWeight={600}
      textAnchor="middle"
    >
      {value}
    </text>
  );
};

// Custom data label for Accuracy chart milestones
const renderAccuracyLabel = (props: any) => {
  const { x, y, value, index } = props;
  if (value === undefined || value === null) return null;
  const isKey = index === 1;
  if (!isKey) return null;
  return (
    <text
      x={x}
      y={y - 7}
      fill="#34d399"
      fontSize={11}
      fontWeight={600}
      textAnchor="middle"
    >
      {value}%
    </text>
  );
};

// Custom data label for Avg Samples per second chart milestones
const renderThroughputLabel = (props: any) => {
  const { x, y, value, index } = props;
  if (value === undefined || value === null) return null;
  const isKey = index === 1;
  if (!isKey) return null;
  return (
    <text
      x={x}
      y={y - 7}
      fill="#34d399"
      fontSize={11}
      fontWeight={600}
      textAnchor="middle"
    >
      {value}
    </text>
  );
};

// Helper for dynamic dot sizing on large step datasets - kept sleek and thin
const getLineDot = (totalSteps: number, strokeColor: string, fillColor: string) => {
  if (totalSteps <= 12) {
    return { r: 2.5, fill: fillColor, stroke: strokeColor, strokeWidth: 1 };
  }
  if (totalSteps <= 24) {
    return { r: 1.5, fill: fillColor, stroke: strokeColor, strokeWidth: 0.5 };
  }
  // For larger datasets (>24 steps), avoid thick beaded dots to keep the line light and modern; hover uses activeDot
  return false;
};

/* =========================================================================
   COMPONENT: WorkerExecutionBreakdownChart
   (Per-step worker execution breakdown with Yellow Training Time,
    Green Pushing Time, Sync line, and large-step navigation)
   ========================================================================= */
export interface WorkerBreakdownProps {
  step?: TrainingStep;
  stepNumberText?: string;
  stepIndex?: number;
  totalSteps?: number;
  onPrevStep?: () => void;
  onNextStep?: () => void;
  onFirstStep?: () => void;
  onLatestStep?: () => void;
  height?: number;
}

export const WorkerExecutionBreakdownChart: React.FC<WorkerBreakdownProps> = ({
  step,
  stepNumberText = 'Step 2',
  stepIndex = 1,
  totalSteps = 2,
  onPrevStep,
  onNextStep,
  onFirstStep,
  onLatestStep,
  height = 168,
}) => {
  const breakdown = useMemo(() => {
    return computeWorkerBreakdown(step, stepIndex);
  }, [step, stepIndex]);

  const maxDomain = Math.ceil((breakdown.syncMaxTime * 1.25) / 10) * 10;

  return (
    <div className="flex flex-col h-full justify-between min-w-0">
      {/* Chart Canvas */}
      <div className="w-full relative" style={{ height: `${height}px` }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            layout="vertical"
            data={breakdown.workers}
            margin={{ top: 8, right: 36, left: 10, bottom: 4 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" horizontal={false} />
            <XAxis
              type="number"
              domain={[0, maxDomain]}
              tick={{ fill: '#73737c', fontSize: 10 }}
              axisLine={{ stroke: '#27272a' }}
              tickLine={false}
              unit="ms"
            />
            <YAxis
              type="category"
              dataKey="workerName"
              tick={{ fill: '#f3f3f4', fontSize: 11, fontWeight: 500 }}
              axisLine={{ stroke: '#27272a' }}
              tickLine={false}
              width={74}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#121214',
                borderColor: '#27272a',
                borderRadius: '4px',
                fontSize: '11px',
                color: '#f3f3f4',
              }}
              formatter={(val: any, name: string) => [
                `${val} ms`,
                name === 'trainingTime'
                  ? 'Training Time (Compute)'
                  : 'Pushing Time (Network)',
              ]}
            />
            {/* Sync Barrier vertical dashed line */}
            <ReferenceLine
              x={breakdown.syncMaxTime}
              stroke="#e2e8f0"
              strokeDasharray="4 4"
              strokeWidth={0.75}
              label={{
                value: 'Max observed',
                position: 'top',
                fill: '#f3f3f4',
                fontSize: 11,
                fontWeight: 600,
                offset: 6,
              }}
            />
            {/* Stacked Bars: Yellow Training Time, Green Pushing Time */}
            <Bar
              dataKey="trainingTime"
              name="Training Time"
              stackId="execution"
              fill="#eab308"
              radius={[0, 0, 0, 0]}
            />
            <Bar
              dataKey="pushingTime"
              name="Pushing Time"
              stackId="execution"
              fill="#10b981"
              radius={[0, 2, 2, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Chart Footer: Step indicator on left & Legend on right */}
      <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-xs min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-[#f3f3f4] truncate">{stepNumberText}</span>
          {onPrevStep && onNextStep && (
            <div className="inline-flex items-center gap-0.5 border border-white/[0.08] rounded px-1 py-0.5 bg-[#171719] shrink-0">
              {onFirstStep && totalSteps > 4 && (
                <button
                  type="button"
                  onClick={onFirstStep}
                  disabled={stepIndex <= 0}
                  className="p-0.5 hover:text-[#f3f3f4] text-[#73737c] disabled:opacity-30 disabled:hover:text-[#73737c]"
                  title="First step"
                >
                  <ChevronsLeft className="w-3 h-3" />
                </button>
              )}
              <button
                type="button"
                onClick={onPrevStep}
                disabled={stepIndex <= 0}
                className="p-0.5 hover:text-[#f3f3f4] text-[#73737c] disabled:opacity-30 disabled:hover:text-[#73737c]"
                title="Previous step"
              >
                <ChevronLeft className="w-3 h-3" />
              </button>
              <span className="text-[10px] text-[#73737c] font-mono px-0.5">
                {totalSteps === 0 ? '0/0' : `${stepIndex + 1}/${totalSteps}`}
              </span>
              <button
                type="button"
                onClick={onNextStep}
                disabled={stepIndex >= totalSteps - 1}
                className="p-0.5 hover:text-[#f3f3f4] text-[#73737c] disabled:opacity-30 disabled:hover:text-[#73737c]"
                title="Next step"
              >
                <ChevronRight className="w-3 h-3" />
              </button>
              {onLatestStep && totalSteps > 4 && (
                <button
                  type="button"
                  onClick={onLatestStep}
                  disabled={stepIndex >= totalSteps - 1}
                  className="p-0.5 hover:text-[#f3f3f4] text-[#73737c] disabled:opacity-30 disabled:hover:text-[#73737c]"
                  title="Latest step"
                >
                  <ChevronsRight className="w-3 h-3" />
                </button>
              )}
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 text-[11px] shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-[#eab308] border border-amber-500/40 inline-block" />
            <span className="text-[#f3f3f4] font-medium text-[11px]">Training</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm bg-[#10b981] border border-emerald-500/40 inline-block" />
            <span className="text-[#f3f3f4] font-medium text-[11px]">Pushing</span>
          </div>
        </div>
      </div>
    </div>
  );
};

/* =========================================================================
   PRIMARY COMPONENT: LiveTrainingCharts
   (Used on Live Training Tab)
   ========================================================================= */
export const LiveTrainingCharts: React.FC<LiveTrainingChartsProps> = ({
  steps,
  expectedWorkers = 0,
  onViewAllMetrics,
  epochMetrics,
}) => {
  const chartData = useMemo(() => computeStepMetrics(steps), [steps]);
  const epochChartData = useMemo(() => computeEpochMetricsData(epochMetrics), [epochMetrics]);
  const latestEpochMetric = epochChartData[epochChartData.length - 1];

  const [selectedStepIdx, setSelectedStepIdx] = useState<number>(() => {
    return chartData.length > 0 ? chartData.length - 1 : 0;
  });

  const prevChartLen = useRef(chartData.length);
  useEffect(() => {
    // Follow latest step if previously viewing latest step
    if (selectedStepIdx >= prevChartLen.current - 1 && chartData.length > prevChartLen.current) {
      setSelectedStepIdx(chartData.length - 1);
    }
    prevChartLen.current = chartData.length;
  }, [chartData.length, selectedStepIdx]);

  const activeStepItem = chartData[selectedStepIdx] || chartData[0];
  const latestItem = chartData[chartData.length - 1];
  const totalSteps = chartData.length;
  const isScrollable = totalSteps > 16;

  return (
    <div className="space-y-3 font-sans select-none min-w-0">
      {/* Header bar */}
      <div className="flex items-center justify-between pb-2 border-b border-white/[0.07]">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
          <h3 className="text-xs font-semibold text-[#f3f3f4] truncate">
            Distributed Training Telemetry &amp; Performance
          </h3>
          <span className="text-[11px] text-[#73737c] hidden sm:inline truncate">
            (4 Core Model &amp; Worker Synchronization Charts)
          </span>
          {isScrollable && (
            <span className="text-[10px] text-blue-400 bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 rounded shrink-0">
              {totalSteps} steps (scrollable)
            </span>
          )}
        </div>

        {onViewAllMetrics && (
          <button
            type="button"
            onClick={onViewAllMetrics}
            className="text-xs text-blue-400 hover:text-blue-300 inline-flex items-center gap-1 transition-colors shrink-0"
          >
            <span>View all metrics</span>
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* 4 PRIMARY CHARTS IN 2x2 GRID */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 min-w-0">
        {/* 1. TOP-LEFT: ONLINE EPOCH TRAINING LOSS */}
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3.5 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1.5">
                <TrendingDown className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Online Epoch Training Loss
                </h4>
              </div>
              <p className="text-[11px] text-[#73737c] truncate">
                Cross-entropy loss convergence across completed epochs
              </p>
            </div>
            <div className="text-right shrink-0">
              <span className="text-xs font-mono font-semibold text-blue-400">
                {latestEpochMetric?.loss ?? '—'}
              </span>
              <div className="text-[10px] text-[#73737c]">
                {latestEpochMetric ? latestEpochMetric.displayEpoch : 'Latest Loss'}
              </div>
            </div>
          </div>

          <div className="w-full pt-1 min-w-0">
            {epochChartData.length === 0 ? (
              <div className="h-[176px] flex flex-col items-center justify-center text-center p-4 border border-dashed border-white/[0.08] rounded bg-white/[0.02]">
                <Clock className="w-5 h-5 text-[#73737c] mb-1.5 animate-pulse" />
                <span className="text-xs text-[#a1a1a8] font-medium">Chưa có Training Metrics; chờ hoàn thành Epoch 1</span>
                <span className="text-[11px] text-[#73737c] mt-0.5">Metrics được tính và chốt chính xác khi kết thúc mỗi Epoch</span>
              </div>
            ) : (
              <ScrollableChartWrapper totalSteps={epochChartData.length} height={176}>
                <LineChart
                  data={epochChartData}
                  margin={{ top: 16, right: 18, left: -20, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                  <XAxis
                    dataKey="displayEpoch"
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 'auto']}
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#121214',
                      borderColor: '#27272a',
                      borderRadius: '4px',
                      fontSize: '11px',
                      color: '#f3f3f4',
                    }}
                    formatter={(val: any) => [val != null ? `${val}` : 'UNAVAILABLE', 'Epoch Loss']}
                    labelFormatter={(lbl) => `${lbl}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="loss"
                    name="Epoch Loss"
                    stroke="#3b82f6"
                    strokeWidth={1.25}
                    dot={{ r: 3, fill: '#3b82f6' }}
                    activeDot={{ r: 5, stroke: '#121214', strokeWidth: 1.5 }}
                    connectNulls={false}
                  />
                </LineChart>
              </ScrollableChartWrapper>
            )}
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
            <span>
              {epochChartData.length > 0 ? `Completed Epochs: ${epochChartData.length}` : 'X: Completed Epochs'}
            </span>
            <span className="text-[#a1a1a8]">
              {epochChartData.length > 0 && latestEpochMetric?.loss != null
                ? `${latestEpochMetric.displayEpoch}: ${latestEpochMetric.loss}`
                : 'Chờ Epoch 1 hoàn tất'}
            </span>
          </div>
        </div>

        {/* 2. TOP-RIGHT: WORKER STEP BREAKDOWN */}
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3.5 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Worker Step Breakdown
                </h4>
              </div>
              <p className="text-[11px] text-[#73737c] truncate">
                Training Time (compute) vs Pushing Time (network) &amp; Sync barrier
              </p>
            </div>
            <div className="text-right shrink-0">
              <span className="text-xs font-mono font-semibold text-emerald-400">
                {activeStepItem?.stepLabel ?? `Step ${selectedStepIdx + 1}`}
              </span>
              <div className="text-[10px] text-[#73737c]">Latency: {activeStepItem?.durationMs ?? 110}ms</div>
            </div>
          </div>

          <div className="pt-1 min-w-0">
            <WorkerExecutionBreakdownChart
              step={activeStepItem?.step}
              stepNumberText={activeStepItem?.stepLabel ?? `Step ${selectedStepIdx + 1}`}
              stepIndex={selectedStepIdx}
              totalSteps={totalSteps}
              onPrevStep={() => setSelectedStepIdx(prev => Math.max(0, prev - 1))}
              onNextStep={() => setSelectedStepIdx(prev => Math.min(totalSteps - 1, prev + 1))}
              onFirstStep={() => setSelectedStepIdx(0)}
              onLatestStep={() => setSelectedStepIdx(totalSteps - 1)}
              height={150}
            />
          </div>
        </div>

        {/* 3. BOTTOM-LEFT: ONLINE EPOCH TRAINING ACCURACY */}
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3.5 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1.5">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Online Epoch Training Accuracy
                </h4>
              </div>
              <p className="text-[11px] text-[#73737c] truncate">
                Reported training accuracy progression across completed epochs
              </p>
            </div>
            <div className="text-right shrink-0">
              <span className="text-xs font-mono font-semibold text-emerald-400">
                {latestEpochMetric?.accuracy != null ? `${latestEpochMetric.accuracy}%` : '—'}
              </span>
              <div className="text-[10px] text-[#73737c]">
                {latestEpochMetric ? latestEpochMetric.displayEpoch : 'Latest Accuracy'}
              </div>
            </div>
          </div>

          <div className="w-full pt-1 min-w-0">
            {epochChartData.length === 0 ? (
              <div className="h-[176px] flex flex-col items-center justify-center text-center p-4 border border-dashed border-white/[0.08] rounded bg-white/[0.02]">
                <Clock className="w-5 h-5 text-[#73737c] mb-1.5 animate-pulse" />
                <span className="text-xs text-[#a1a1a8] font-medium">Chưa có Training Metrics; chờ hoàn thành Epoch 1</span>
                <span className="text-[11px] text-[#73737c] mt-0.5">Metrics được tính và chốt chính xác khi kết thúc mỗi Epoch</span>
              </div>
            ) : (
              <ScrollableChartWrapper totalSteps={epochChartData.length} height={176}>
                <LineChart
                  data={epochChartData}
                  margin={{ top: 16, right: 18, left: -20, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                  <XAxis
                    dataKey="displayEpoch"
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 100]}
                    unit="%"
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#121214',
                      borderColor: '#27272a',
                      borderRadius: '4px',
                      fontSize: '11px',
                      color: '#f3f3f4',
                    }}
                    formatter={(val: any) => [val != null ? `${val}%` : 'UNAVAILABLE', 'Epoch Accuracy']}
                    labelFormatter={(lbl) => `${lbl}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="accuracy"
                    name="Epoch Accuracy"
                    stroke="#10b981"
                    strokeWidth={1.25}
                    dot={{ r: 3, fill: '#10b981' }}
                    activeDot={{ r: 5, stroke: '#121214', strokeWidth: 1.5 }}
                    connectNulls={false}
                  />
                </LineChart>
              </ScrollableChartWrapper>
            )}
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
            <span>
              {epochChartData.length > 0 ? `Completed Epochs: ${epochChartData.length}` : 'X: Completed Epochs'}
            </span>
            <span className="text-[#a1a1a8]">
              {epochChartData.length > 0 && latestEpochMetric?.accuracy != null
                ? `${latestEpochMetric.displayEpoch}: ${latestEpochMetric.accuracy}%`
                : 'Chờ Epoch 1 hoàn tất'}
            </span>
          </div>
        </div>

        {/* 4. BOTTOM-RIGHT: AVG SAMPLES PER SECOND */}
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3.5 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5 min-w-0">
              <div className="flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Avg Samples per second
                </h4>
              </div>
              <p className="text-[11px] text-[#73737c] truncate">
                Effective aggregate cluster throughput across timeline
              </p>
            </div>
            <div className="text-right shrink-0">
              <span className="text-xs font-mono font-semibold text-emerald-400">
                {latestItem?.avgSamplesPerSec ?? '—'} /s
              </span>
              <div className="text-[10px] text-[#73737c]">Current Rate</div>
            </div>
          </div>

          <div className="w-full pt-1 min-w-0">
            <ScrollableChartWrapper totalSteps={totalSteps} height={176}>
              <LineChart
                data={chartData}
                margin={{ top: 16, right: 18, left: -10, bottom: 4 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                <XAxis
                  dataKey="timeLabel"
                  tick={{ fill: '#73737c', fontSize: 10 }}
                  axisLine={{ stroke: '#27272a' }}
                  tickLine={false}
                  interval="preserveStartEnd"
                  minTickGap={32}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fill: '#73737c', fontSize: 10 }}
                  axisLine={{ stroke: '#27272a' }}
                  tickLine={false}
                  unit="/s"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#121214',
                    borderColor: '#27272a',
                    borderRadius: '4px',
                    fontSize: '11px',
                    color: '#f3f3f4',
                  }}
                  formatter={(val: any) => [`${val} samples/sec`, 'Throughput']}
                  labelFormatter={(lbl) => `Time: ${lbl}`}
                />
                <Line
                  type="monotone"
                  dataKey="avgSamplesPerSec"
                  name="Avg Samples/sec"
                  stroke="#10b981"
                  strokeWidth={1.25}
                  dot={getLineDot(totalSteps, '#047857', '#10b981')}
                  activeDot={{ r: 4, stroke: '#121214', strokeWidth: 1.5 }}
                  label={totalSteps <= 10 ? renderThroughputLabel : undefined}
                />
              </LineChart>
            </ScrollableChartWrapper>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
            <span>
              {isScrollable ? (
                <span className="text-[#a1a1a8]">Timeline: {totalSteps} data points</span>
              ) : (
                'X: Time'
              )}
            </span>
            <span className="text-[#a1a1a8]">Cluster Target: ~5,000 samples/sec</span>
          </div>
        </div>
      </div>
    </div>
  );
};

/* =========================================================================
   DEDICATED FULL METRICS DASHBOARD
   (Used on the "Metrics" Tab in Live Training)
   ========================================================================= */
export interface FullMetricsDashboardProps {
  steps: TrainingStep[];
  expectedWorkers?: number;
  epochMetrics?: EpochMetricData[];
}

export const FullMetricsDashboard: React.FC<FullMetricsDashboardProps> = ({
  steps,
  expectedWorkers = 0,
  epochMetrics,
}) => {
  const chartData = useMemo(() => computeStepMetrics(steps), [steps]);
  const epochChartData = useMemo(() => computeEpochMetricsData(epochMetrics), [epochMetrics]);
  const latestEpochMetric = epochChartData[epochChartData.length - 1];

  const [selectedStepIdx, setSelectedStepIdx] = useState<number>(() => {
    return chartData.length > 0 ? chartData.length - 1 : 0;
  });
  const [xAxisMode, setXAxisMode] = useState<'normalized' | 'operation'>('normalized');

  const prevChartLen = useRef(chartData.length);
  useEffect(() => {
    if (selectedStepIdx >= prevChartLen.current - 1 && chartData.length > prevChartLen.current) {
      setSelectedStepIdx(chartData.length - 1);
    }
    prevChartLen.current = chartData.length;
  }, [chartData.length, selectedStepIdx]);

  const activeStepItem = chartData[selectedStepIdx] || chartData[0];
  const latestItem = chartData[chartData.length - 1];
  const totalSteps = chartData.length;
  const isScrollable = totalSteps > 16;

  return (
    <div className="space-y-6 font-sans select-none min-w-0">
      {/* Top Banner & Control Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <h3 className="text-sm font-semibold text-[#f3f3f4] flex items-center gap-2">
            <span>Cluster Metrics &amp; Execution Telemetry</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Live Real-time
            </span>
          </h3>
          <p className="text-xs text-[#73737c] mt-0.5">
            Arranged according to standard distributed training workflow: Primary Convergence &amp; Worker Breakdown first, followed by Deep BSP Diagnostics.
          </p>
        </div>

        {/* X-Axis Step Labeling Mode Toggle */}
        <div className="flex items-center gap-2 text-xs shrink-0">
          <span className="text-[#73737c] text-[11px]">X-Axis Notation:</span>
          <div className="inline-flex rounded border border-white/[0.08] p-0.5 bg-[#121214]">
            <button
              type="button"
              onClick={() => setXAxisMode('normalized')}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${xAxisMode === 'normalized'
                ? 'bg-[#1e1e24] text-[#f3f3f4] font-medium'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
                }`}
            >
              Global Step (0, 1, 2...)
            </button>
            <button
              type="button"
              onClick={() => setXAxisMode('operation')}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${xAxisMode === 'operation'
                ? 'bg-[#1e1e24] text-[#f3f3f4] font-medium'
                : 'text-[#73737c] hover:text-[#f3f3f4]'
                }`}
            >
              Op ID (#3260...)
            </button>
          </div>
        </div>
      </div>

      {/* Top KPI Telemetry Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 min-w-0">
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3 space-y-1 min-w-0">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5 truncate">
            <TrendingDown className="w-3.5 h-3.5 text-blue-400 shrink-0" />
            <span>Online Epoch Training Loss</span>
          </div>
          <div className="text-xl font-mono font-semibold text-[#f3f3f4] truncate">
            {latestEpochMetric?.loss ?? '—'}
          </div>
          <div className="text-[10px] text-blue-400/90 font-medium truncate">
            {epochChartData.length > 0
              ? `${latestEpochMetric?.displayEpoch ?? 'Latest'}: ${latestEpochMetric?.loss ?? '—'}`
              : 'Chờ hoàn thành Epoch 1'}
          </div>
        </div>

        <div className="bg-[#121214] border border-white/[0.07] rounded p-3 space-y-1 min-w-0">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5 truncate">
            <Clock className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <span>Sync Barrier Latency</span>
          </div>
          <div className="text-xl font-mono font-semibold text-[#f3f3f4] truncate">
            {activeStepItem?.durationMs ?? 110} ms
          </div>
          <div className="text-[10px] text-amber-400/90 font-medium truncate">
            {activeStepItem ? `${activeStepItem.stepLabel} barrier latency` : 'Barrier cycle latency'}
          </div>
        </div>

        <div className="bg-[#121214] border border-white/[0.07] rounded p-3 space-y-1 min-w-0">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5 truncate">
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>Online Epoch Training Accuracy</span>
          </div>
          <div className="text-xl font-mono font-semibold text-[#f3f3f4] truncate">
            {latestEpochMetric?.accuracy != null ? `${latestEpochMetric.accuracy}%` : '—'}
          </div>
          <div className="text-[10px] text-emerald-400/90 font-medium truncate">
            {epochChartData.length > 0
              ? `${latestEpochMetric?.displayEpoch ?? 'Latest'}: ${latestEpochMetric?.accuracy != null ? `${latestEpochMetric.accuracy}%` : '—'}`
              : 'Chờ hoàn thành Epoch 1'}
          </div>
        </div>

        <div className="bg-[#121214] border border-white/[0.07] rounded p-3 space-y-1 min-w-0">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5 truncate">
            <Zap className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>Avg Samples / sec</span>
          </div>
          <div className="text-xl font-mono font-semibold text-[#f3f3f4] truncate">
            {latestItem?.avgSamplesPerSec ?? '—'}
          </div>
          <div className="text-[10px] text-emerald-400/90 font-medium truncate">
            {totalSteps > 0 ? `Step ${totalSteps} throughput` : 'Throughput rate'}
          </div>
        </div>
      </div>

      {/* SECTION 1: PRIMARY CHARTS */}
      <div className="space-y-3 min-w-0">
        <div className="flex items-center justify-between pb-1 border-b border-white/[0.04]">
          <h4 className="text-xs font-semibold text-[#f3f3f4] uppercase tracking-wider text-[11px]">
            Primary Model &amp; Synchronization Charts
          </h4>
          <span className="text-[11px] text-[#73737c]">
            Rows 1 &amp; 2 directly mapping to distributed training diagram
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-w-0">
          {/* 1. TOP-LEFT: ONLINE EPOCH TRAINING LOSS */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-2">
                  <TrendingDown className="w-4 h-4 text-blue-400 shrink-0" />
                  <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                    Online Epoch Training Loss
                  </h4>
                </div>
                <p className="text-[11px] text-[#73737c] truncate">
                  Y: Training Loss vs X: Completed Epoch
                </p>
              </div>
              <div className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-xs font-mono font-semibold shrink-0">
                Loss: {latestEpochMetric?.loss ?? '—'}
              </div>
            </div>

            <div className="w-full pt-2 min-w-0">
              {epochChartData.length === 0 ? (
                <div className="h-[208px] flex flex-col items-center justify-center text-center p-4 border border-dashed border-white/[0.08] rounded bg-white/[0.02]">
                  <Clock className="w-5 h-5 text-[#73737c] mb-1.5 animate-pulse" />
                  <span className="text-xs text-[#a1a1a8] font-medium">Chưa có Training Metrics; chờ hoàn thành Epoch 1</span>
                  <span className="text-[11px] text-[#73737c] mt-0.5">Metrics được tính và chốt chính xác khi kết thúc mỗi Epoch</span>
                </div>
              ) : (
                <ScrollableChartWrapper totalSteps={epochChartData.length} height={208}>
                  <LineChart
                    data={epochChartData}
                    margin={{ top: 18, right: 18, left: -20, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                    <XAxis
                      dataKey="displayEpoch"
                      tick={{ fill: '#73737c', fontSize: 10 }}
                      axisLine={{ stroke: '#27272a' }}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, 'auto']}
                      tick={{ fill: '#73737c', fontSize: 10 }}
                      axisLine={{ stroke: '#27272a' }}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#121214',
                        borderColor: '#27272a',
                        borderRadius: '4px',
                        fontSize: '11px',
                        color: '#f3f3f4',
                      }}
                      formatter={(val: any) => [val != null ? `${val}` : 'UNAVAILABLE', 'Epoch Loss']}
                      labelFormatter={(lbl) => `${lbl}`}
                    />
                    <Line
                      type="monotone"
                      dataKey="loss"
                      name="Epoch Loss"
                      stroke="#3b82f6"
                      strokeWidth={1.25}
                      dot={{ r: 3, fill: '#3b82f6' }}
                      activeDot={{ r: 5, stroke: '#121214', strokeWidth: 1.5 }}
                      connectNulls={false}
                    />
                  </LineChart>
                </ScrollableChartWrapper>
              )}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
              <span>
                {epochChartData.length > 0 ? `Completed Epochs: ${epochChartData.length}` : 'Axis: Completed Epochs'}
              </span>
              <span className="text-blue-400 font-mono">
                {epochChartData.length > 0 && latestEpochMetric?.loss != null
                  ? `${epochChartData[0]?.displayEpoch}: ${epochChartData[0]?.loss ?? '—'} → ${latestEpochMetric.displayEpoch}: ${latestEpochMetric.loss}`
                  : 'Chờ hoàn thành Epoch 1'}
              </span>
            </div>
          </div>

          {/* 2. TOP-RIGHT: WORKER STEP BREAKDOWN */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-amber-400 shrink-0" />
                  <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                    Worker Step Breakdown
                  </h4>
                </div>
                <p className="text-[11px] text-[#73737c] truncate">
                  Training Time (compute) vs Pushing Time (network) &amp; Sync barrier
                </p>
              </div>
              <div className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 text-xs font-mono font-semibold shrink-0">
                Sync Barrier: {activeStepItem?.durationMs ?? 110}ms
              </div>
            </div>

            <div className="pt-2 min-w-0">
              <WorkerExecutionBreakdownChart
                step={activeStepItem?.step}
                stepNumberText={activeStepItem?.stepLabel ?? `Step ${selectedStepIdx + 1}`}
                stepIndex={selectedStepIdx}
                totalSteps={totalSteps}
                onPrevStep={() => setSelectedStepIdx(prev => Math.max(0, prev - 1))}
                onNextStep={() => setSelectedStepIdx(prev => Math.min(totalSteps - 1, prev + 1))}
                onFirstStep={() => setSelectedStepIdx(0)}
                onLatestStep={() => setSelectedStepIdx(totalSteps - 1)}
                height={175}
              />
            </div>
          </div>

          {/* 3. BOTTOM-LEFT: ONLINE EPOCH TRAINING ACCURACY */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-emerald-400 shrink-0" />
                  <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                    Online Epoch Training Accuracy
                  </h4>
                </div>
                <p className="text-[11px] text-[#73737c] truncate">
                  Y: Accuracy (%) vs X: Completed Epoch
                </p>
              </div>
              <div className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-mono font-semibold shrink-0">
                Score: {latestEpochMetric?.accuracy != null ? `${latestEpochMetric.accuracy}%` : '—'}
              </div>
            </div>

            <div className="w-full pt-2 min-w-0">
              {epochChartData.length === 0 ? (
                <div className="h-[208px] flex flex-col items-center justify-center text-center p-4 border border-dashed border-white/[0.08] rounded bg-white/[0.02]">
                  <Clock className="w-5 h-5 text-[#73737c] mb-1.5 animate-pulse" />
                  <span className="text-xs text-[#a1a1a8] font-medium">Chưa có Training Metrics; chờ hoàn thành Epoch 1</span>
                  <span className="text-[11px] text-[#73737c] mt-0.5">Metrics được tính và chốt chính xác khi kết thúc mỗi Epoch</span>
                </div>
              ) : (
                <ScrollableChartWrapper totalSteps={epochChartData.length} height={208}>
                  <LineChart
                    data={epochChartData}
                    margin={{ top: 18, right: 18, left: -20, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                    <XAxis
                      dataKey="displayEpoch"
                      tick={{ fill: '#73737c', fontSize: 10 }}
                      axisLine={{ stroke: '#27272a' }}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, 100]}
                      unit="%"
                      tick={{ fill: '#73737c', fontSize: 10 }}
                      axisLine={{ stroke: '#27272a' }}
                      tickLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#121214',
                        borderColor: '#27272a',
                        borderRadius: '4px',
                        fontSize: '11px',
                        color: '#f3f3f4',
                      }}
                      formatter={(val: any) => [val != null ? `${val}%` : 'UNAVAILABLE', 'Epoch Accuracy']}
                      labelFormatter={(lbl) => `${lbl}`}
                    />
                    <Line
                      type="monotone"
                      dataKey="accuracy"
                      name="Epoch Accuracy"
                      stroke="#10b981"
                      strokeWidth={1.25}
                      dot={{ r: 3, fill: '#10b981' }}
                      activeDot={{ r: 5, stroke: '#121214', strokeWidth: 1.5 }}
                      connectNulls={false}
                    />
                  </LineChart>
                </ScrollableChartWrapper>
              )}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
              <span>
                {epochChartData.length > 0 ? `Completed Epochs: ${epochChartData.length}` : 'Axis: Completed Epochs'}
              </span>
              <span className="text-emerald-400 font-mono">
                {epochChartData.length > 0 && latestEpochMetric?.accuracy != null
                  ? `${latestEpochMetric.displayEpoch}: ${latestEpochMetric.accuracy}%`
                  : 'Chờ hoàn thành Epoch 1'}
              </span>
            </div>
          </div>

          {/* 4. BOTTOM-RIGHT: AVG SAMPLES PER SECOND */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 flex flex-col justify-between min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-emerald-400 shrink-0" />
                  <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                    Avg Samples per second
                  </h4>
                </div>
                <p className="text-[11px] text-[#73737c] truncate">
                  Y: Avg Samples per second vs X: Time
                </p>
              </div>
              <div className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs font-mono font-semibold shrink-0">
                Rate: {latestItem?.avgSamplesPerSec} /s
              </div>
            </div>

            <div className="w-full pt-2 min-w-0">
              <ScrollableChartWrapper totalSteps={totalSteps} height={208}>
                <LineChart
                  data={chartData}
                  margin={{ top: 18, right: 18, left: -10, bottom: 4 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                  <XAxis
                    dataKey="timeLabel"
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={32}
                  />
                  <YAxis
                    domain={['auto', 'auto']}
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    unit="/s"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#121214',
                      borderColor: '#27272a',
                      borderRadius: '4px',
                      fontSize: '11px',
                      color: '#f3f3f4',
                    }}
                    formatter={(val: any) => [`${val} samples/sec`, 'Throughput']}
                  />
                  <Line
                    type="monotone"
                    dataKey="avgSamplesPerSec"
                    name="Avg Samples/sec"
                    stroke="#10b981"
                    strokeWidth={1.25}
                    dot={getLineDot(totalSteps, '#047857', '#10b981')}
                    activeDot={{ r: 4, stroke: '#121214', strokeWidth: 1.5 }}
                    label={totalSteps <= 10 ? renderThroughputLabel : undefined}
                  />
                </LineChart>
              </ScrollableChartWrapper>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[11px] text-[#73737c]">
              <span>
                {isScrollable ? (
                  <span className="text-[#a1a1a8]">Timeline: {totalSteps} data points</span>
                ) : (
                  'Axis: Time timeline'
                )}
              </span>
              <span className="text-emerald-400 font-mono">{latestItem?.avgSamplesPerSec ?? '—'} samples/sec</span>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 2: SECONDARY DIAGNOSTIC CHARTS */}
      <div className="space-y-3 pt-2 min-w-0">
        <div className="flex items-center justify-between pb-1 border-b border-white/[0.04]">
          <h4 className="text-xs font-semibold text-[#73737c] uppercase tracking-wider text-[11px]">
            Secondary Cluster Timing &amp; Strict BSP Diagnostics
          </h4>
          <span className="text-[11px] text-[#73737c]">
            Per-step cycle duration &amp; gradient barrier reception
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-w-0">
          {/* 5. STEP DURATION & CYCLE LATENCY */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Step Duration &amp; Cycle Latency
                </h4>
                <p className="text-[11px] text-[#73737c] truncate">
                  Total round-trip time in milliseconds per training step
                </p>
              </div>
              <span className="text-xs font-mono text-[#a1a1a8] shrink-0">Milliseconds</span>
            </div>

            <div className="w-full pt-1 min-w-0">
              <ScrollableChartWrapper totalSteps={totalSteps} height={176}>
                <LineChart
                  data={chartData}
                  margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                  <XAxis
                    dataKey={xAxisMode === 'normalized' ? 'displayStep' : 'opNumber'}
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={28}
                  />
                  <YAxis
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    unit="ms"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#121214',
                      borderColor: '#27272a',
                      borderRadius: '4px',
                      fontSize: '11px',
                      color: '#f3f3f4',
                    }}
                    formatter={(val: any) => [`${val} ms`, 'Step Duration']}
                  />
                  <Line
                    type="monotone"
                    dataKey="durationMs"
                    name="Step Duration"
                    stroke="#3b82f6"
                    strokeWidth={1.25}
                    dot={getLineDot(totalSteps, '#1d4ed8', '#3b82f6')}
                    activeDot={{ r: 4, stroke: '#121214', strokeWidth: 1.5 }}
                  />
                </LineChart>
              </ScrollableChartWrapper>
            </div>
          </div>

          {/* 6. WORKER BARRIER CONTRIBUTIONS (STRICT BSP) */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-2 min-w-0 overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5 min-w-0">
                <h4 className="text-xs font-semibold text-[#f3f3f4] truncate">
                  Worker Barrier Contributions (Strict BSP)
                </h4>
                <p className="text-[11px] text-[#73737c] truncate">
                  Count of valid gradient tensors collected before commit
                </p>
              </div>
              <span className="text-xs font-mono text-emerald-400 shrink-0">
                {expectedWorkers}/{expectedWorkers} Required
              </span>
            </div>

            <div className="w-full pt-1 min-w-0">
              <ScrollableChartWrapper totalSteps={totalSteps} height={176}>
                <BarChart
                  data={chartData}
                  margin={{ top: 5, right: 10, left: -20, bottom: 0 }}
                  barCategoryGap={totalSteps > 16 ? 4 : '20%'}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f1f23" vertical={false} />
                  <XAxis
                    dataKey={xAxisMode === 'normalized' ? 'displayStep' : 'opNumber'}
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={28}
                  />
                  <YAxis
                    dataKey="acceptedWorkers"
                    tick={{ fill: '#73737c', fontSize: 10 }}
                    axisLine={{ stroke: '#27272a' }}
                    tickLine={false}
                    domain={[0, expectedWorkers]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#121214',
                      borderColor: '#27272a',
                      borderRadius: '4px',
                      fontSize: '11px',
                      color: '#f3f3f4',
                    }}
                    formatter={(val: any) => [`${val}/${expectedWorkers} workers`, 'Gradients Accepted']}
                  />
                  <Bar
                    dataKey="acceptedWorkers"
                    name="Gradients Accepted"
                    fill="#3b82f6"
                    radius={[2, 2, 0, 0]}
                    maxBarSize={totalSteps > 50 ? 20 : 32}
                  />
                </BarChart>
              </ScrollableChartWrapper>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

