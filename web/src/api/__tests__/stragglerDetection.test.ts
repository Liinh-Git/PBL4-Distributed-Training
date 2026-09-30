import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  detectSlowWorkers,
  calculateMedian,
  SLOW_WORKER_RATIO,
  MIN_COMPUTE_SAMPLES,
} from '../../utils/stragglerDetection';

describe('Presentation Heuristic: Worker Compute Straggler Detection (Hotfix #5)', () => {
  test('Constants: SLOW_WORKER_RATIO is 1.5 and MIN_COMPUTE_SAMPLES is 3', () => {
    assert.strictEqual(SLOW_WORKER_RATIO, 1.5);
    assert.strictEqual(MIN_COMPUTE_SAMPLES, 3);
  });

  test('calculateMedian calculates correct median for odd and even length arrays', () => {
    assert.strictEqual(calculateMedian([]), 0);
    assert.strictEqual(calculateMedian([42]), 42);
    assert.strictEqual(calculateMedian([10, 30, 20]), 20);
    assert.strictEqual(calculateMedian([10, 20, 30, 40]), 25);
  });

  test('Test 1: Worker with fewer than 3 committed samples is NOT labeled Slow', () => {
    // Only 2 steps available
    const steps = [
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 50, uploadMs: 5 },
          { workerId: 1, computeMs: 50, uploadMs: 5 },
          { workerId: 2, computeMs: 200, uploadMs: 5 }, // 4x slower, but only 2 samples!
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 55, uploadMs: 5 },
          { workerId: 1, computeMs: 52, uploadMs: 5 },
          { workerId: 2, computeMs: 210, uploadMs: 5 },
        ],
      },
    ];

    const result = detectSlowWorkers(steps);

    assert.strictEqual(result.get(0)?.isSlow, false);
    assert.strictEqual(result.get(1)?.isSlow, false);
    assert.strictEqual(result.get(2)?.isSlow, false); // Insufficient samples (2 < 3)
    assert.strictEqual(result.get(2)?.hasEnoughSamples, false);
    assert.strictEqual(result.get(2)?.sampleCount, 2);
  });

  test('undefined and non-COMMITTED steps cannot supply compute samples', () => {
    const contributions = [
      { workerId: 0, computeMs: 50, uploadMs: 5 },
      { workerId: 1, computeMs: 50, uploadMs: 5 },
      { workerId: 2, computeMs: 200, uploadMs: 5000 },
    ];
    const steps = [
      { workerContributions: contributions },
      ...['COLLECTING_GRADIENTS', 'AGGREGATING', 'UPDATING', 'CHECKPOINTING'].map(state => ({
        state, workerContributions: contributions,
      })),
      { state: 'COMMITTED', workerContributions: contributions },
      { state: 'COMMITTED', workerContributions: contributions },
    ];
    const twoSamples = detectSlowWorkers(steps);
    assert.equal(twoSamples.get(2)?.sampleCount, 2);
    assert.equal(twoSamples.get(2)?.isSlow, false);

    const threeSamples = detectSlowWorkers([
      ...steps,
      { state: 'COMMITTED', workerContributions: contributions },
    ]);
    assert.equal(threeSamples.get(2)?.sampleCount, 3);
    assert.equal(threeSamples.get(2)?.isSlow, true);
  });

  test('Test 2: Worker with median compute_ms > 1.5x group median (>= 3 samples) IS labeled Slow', () => {
    // 3 committed steps: Worker 0 & 1 around 50ms, Worker 2 around 120ms (2.4x > 1.5x)
    const steps = [
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 48, uploadMs: 10 },
          { workerId: 1, computeMs: 52, uploadMs: 10 },
          { workerId: 2, computeMs: 120, uploadMs: 10 },
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 50, uploadMs: 10 },
          { workerId: 1, computeMs: 50, uploadMs: 10 },
          { workerId: 2, computeMs: 125, uploadMs: 10 },
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 52, uploadMs: 10 },
          { workerId: 1, computeMs: 48, uploadMs: 10 },
          { workerId: 2, computeMs: 115, uploadMs: 10 },
        ],
      },
    ];

    const result = detectSlowWorkers(steps);

    // Group medians: Worker 0 = 50ms, Worker 1 = 50ms, Worker 2 = 120ms
    // Group median = 50ms. Ratio threshold: 1.5 * 50 = 75ms.
    // Worker 2 median = 120ms > 75ms -> isSlow: true.
    assert.strictEqual(result.get(0)?.isSlow, false);
    assert.strictEqual(result.get(1)?.isSlow, false);
    assert.strictEqual(result.get(2)?.isSlow, true);
    assert.strictEqual(result.get(2)?.hasEnoughSamples, true);
    assert.strictEqual(result.get(2)?.medianComputeMs, 120);
  });

  test('Test 3: Worker with high upload_ms but normal compute_ms is NOT labeled Slow', () => {
    // Worker 2 has massive upload latency (5000ms), but compute time is identical to group (50ms)
    const steps = [
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 50, uploadMs: 5 },
          { workerId: 1, computeMs: 50, uploadMs: 5 },
          { workerId: 2, computeMs: 50, uploadMs: 5000 }, // Upload bottleneck, NOT compute straggler!
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 50, uploadMs: 5 },
          { workerId: 1, computeMs: 50, uploadMs: 5 },
          { workerId: 2, computeMs: 52, uploadMs: 4800 },
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 48, uploadMs: 5 },
          { workerId: 1, computeMs: 50, uploadMs: 5 },
          { workerId: 2, computeMs: 50, uploadMs: 5200 },
        ],
      },
    ];

    const result = detectSlowWorkers(steps);

    assert.strictEqual(result.get(0)?.isSlow, false);
    assert.strictEqual(result.get(1)?.isSlow, false);
    assert.strictEqual(result.get(2)?.isSlow, false); // NOT slow because compute_ms is 50ms!
  });

  test('Test 4: Normal workers with balanced compute are all NOT Slow', () => {
    const steps = [
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 100 },
          { workerId: 1, computeMs: 105 },
          { workerId: 2, computeMs: 98 },
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 102 },
          { workerId: 1, computeMs: 100 },
          { workerId: 2, computeMs: 104 },
        ],
      },
      {
        state: 'COMMITTED',
        workerContributions: [
          { workerId: 0, computeMs: 99 },
          { workerId: 1, computeMs: 101 },
          { workerId: 2, computeMs: 102 },
        ],
      },
    ];

    const result = detectSlowWorkers(steps);

    assert.strictEqual(result.get(0)?.isSlow, false);
    assert.strictEqual(result.get(1)?.isSlow, false);
    assert.strictEqual(result.get(2)?.isSlow, false);
  });

  test('Static AST/Source inspection: WorkerLiveStrip and LiveTrainingPage render compute time and Slow badge', () => {
    const stripPath = path.resolve(process.cwd(), 'src/components/live/WorkerLiveStrip.tsx');
    const stripContent = fs.readFileSync(stripPath, 'utf-8');

    // 1. WorkerLiveStrip must import and call detectSlowWorkers
    assert.match(stripContent, /detectSlowWorkers/);

    // 2. WorkerLiveStrip must render Slow badge
    assert.match(stripContent, /data-testid=\{`slow-badge-worker-\$\{worker\.workerId\}`\}/);
    assert.match(stripContent, />\s*Slow\s*<\/span>/);

    // 3. WorkerLiveStrip must render compute time
    assert.match(stripContent, /computeMs/);
    assert.match(stripContent, /ms/);

    const pagePath = path.resolve(process.cwd(), 'src/pages/LiveTrainingPage.tsx');
    const pageContent = fs.readFileSync(pagePath, 'utf-8');

    // 4. LiveTrainingPage must import detectSlowWorkers
    assert.match(pageContent, /import \{ detectSlowWorkers \} from '\.\.\/utils\/stragglerDetection'/);

    // 5. LiveTrainingPage must render Slow badge in worker status list
    assert.match(pageContent, /data-testid=\{`slow-badge-worker-\$\{id\}`\}/);
    assert.match(pageContent, />\s*Slow\s*<\/span>/);
  });
});
