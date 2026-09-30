/**
 * Presentation Heuristic for Worker Compute Straggler Detection (Hotfix #5)
 *
 * CANONICAL CONSTRAINTS:
 * 1. Strictly presentation/UI heuristic — NEVER fed back into DBS or workload scheduling.
 * 2. Strictly evaluates compute_ms (ignoring upload_ms, network latency, parameter application, or barrier arrival).
 * 3. Requires at least MIN_COMPUTE_SAMPLES (>= 3) committed samples to prevent false straggler alerts on startup.
 * 4. Flags a worker as slow when worker median compute_ms > SLOW_WORKER_RATIO (1.5x) group median.
 */

export const SLOW_WORKER_RATIO = 1.5;
export const MIN_COMPUTE_SAMPLES = 3;

export interface WorkerComputeTelemetry {
  workerId: number;
  sampleCount: number;
  currentComputeMs?: number;
  medianComputeMs?: number;
  isSlow: boolean;
  hasEnoughSamples: boolean;
}

export interface WorkerStepContributionLike {
  workerId: number;
  computeMs?: number | null;
  uploadMs?: number | null;
  parameterApplyMs?: number | null;
  sampleCount?: number | null;
  samples?: number | null;
  contributionAccepted?: boolean;
}

export interface StepTelemetryLike {
  state?: string;
  workerContributions?: WorkerStepContributionLike[];
}

/**
 * Calculates the statistical median of a numeric array.
 */
export function calculateMedian(values: number[]): number {
  if (!values || values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 !== 0) {
    return sorted[mid];
  }
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Detects compute stragglers across workers using rolling compute_ms telemetry.
 *
 * @param steps List of training steps (ordered newest to oldest or vice-versa)
 * @param options Optional tuning overrides for threshold ratio or minimum sample count
 * @returns Map of workerId -> WorkerComputeTelemetry
 */
export function detectSlowWorkers(
  steps: StepTelemetryLike[],
  options?: {
    ratioThreshold?: number;
    minSamples?: number;
  }
): Map<number, WorkerComputeTelemetry> {
  const ratioThreshold = options?.ratioThreshold ?? SLOW_WORKER_RATIO;
  const minSamples = options?.minSamples ?? MIN_COMPUTE_SAMPLES;

  // 1. Collect valid positive compute_ms samples strictly from committed steps.
  const samplesByWorker = new Map<number, number[]>();
  const latestComputeByWorker = new Map<number, number>();

  for (const st of steps) {
    if (st.state !== 'COMMITTED') {
      continue;
    }

    const contributions = st.workerContributions || [];
    for (const c of contributions) {
      if (c.workerId === undefined || c.workerId === null) continue;
      const workerId = Number(c.workerId);

      // CRITICAL: Strictly inspect computeMs, NEVER uploadMs or parameterApplyMs!
      if (typeof c.computeMs === 'number' && Number.isFinite(c.computeMs) && c.computeMs > 0) {
        if (!samplesByWorker.has(workerId)) {
          samplesByWorker.set(workerId, []);
        }
        samplesByWorker.get(workerId)!.push(c.computeMs);

        if (!latestComputeByWorker.has(workerId)) {
          latestComputeByWorker.set(workerId, c.computeMs);
        }
      }
    }
  }

  // 2. Compute median compute time for each worker with samples
  const workerMedians = new Map<number, number>();
  for (const [wId, samples] of samplesByWorker.entries()) {
    if (samples.length > 0) {
      workerMedians.set(wId, calculateMedian(samples));
    }
  }

  // 3. Compute group median across all workers that have compute samples
  const mediansList = Array.from(workerMedians.values());
  const groupMedian = mediansList.length > 0 ? calculateMedian(mediansList) : 0;

  // 4. Construct telemetry evaluation per worker
  const result = new Map<number, WorkerComputeTelemetry>();

  for (const [wId, samples] of samplesByWorker.entries()) {
    const sampleCount = samples.length;
    const hasEnoughSamples = sampleCount >= minSamples;
    const workerMedian = workerMedians.get(wId) ?? 0;
    const currentComputeMs = latestComputeByWorker.get(wId);

    // Straggler condition:
    // - Must have >= minSamples (>= 3)
    // - Group median must be positive
    // - Worker's median compute time must strictly exceed ratioThreshold * groupMedian
    const isSlow =
      hasEnoughSamples &&
      groupMedian > 0 &&
      workerMedian > ratioThreshold * groupMedian;

    result.set(wId, {
      workerId: wId,
      sampleCount,
      currentComputeMs,
      medianComputeMs: workerMedian,
      isSlow,
      hasEnoughSamples,
    });
  }

  return result;
}
