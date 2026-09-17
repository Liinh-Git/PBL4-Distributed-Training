import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeStepMetrics,
  computeWorkerBreakdown,
  getChartContentWidth,
} from '../../components/charts/LiveTrainingCharts';
import { TrainingStep } from '../../types';

test('Large Step Charts Usability & Metrics Calculation', async (t) => {
  await t.test('getChartContentWidth behavior for small vs large step counts', () => {
    // 0 to threshold (16) steps should return '100%'
    assert.equal(getChartContentWidth(0, 16), '100%');
    assert.equal(getChartContentWidth(1, 16), '100%');
    assert.equal(getChartContentWidth(10, 16), '100%');
    assert.equal(getChartContentWidth(16, 16), '100%');

    // > 16 steps should calculate width dynamically and be >= 600px
    const width20 = getChartContentWidth(20, 16);
    assert.equal(typeof width20, 'number');
    assert.equal(width20, 20 * 32); // 640px

    const width50 = getChartContentWidth(50, 16);
    assert.equal(width50, 50 * 32); // 1600px

    const width150 = getChartContentWidth(150, 16);
    assert.equal(width150, 150 * 28); // 4200px

    const width500 = getChartContentWidth(500, 16);
    assert.equal(width500, 500 * 24); // 12000px
  });

  await t.test('computeStepMetrics correctly generates complete dataset without dropping data', () => {
    // 1. Empty steps
    const emptyMetrics = computeStepMetrics([]);
    assert.equal(emptyMetrics.length, 0);

    // 2. Small step series (2 steps from design baseline)
    const twoSteps: TrainingStep[] = [
      {
        operationId: 2,
        attemptId: 'att_01',
        state: 'COMMITTED',
        epoch: 1,
        batchOrdinal: 2,
        inputModelVersion: '1',
        outputModelVersion: '2',
        totalSampleCount: 192,
        timings: { startedAt: 'T-2s', committedAt: 'T-1s', totalDurationMs: 110 },
        workerContributions: [
          { workerId: 0, sessionId: 's0', batchId: 'b0', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
          { workerId: 1, sessionId: 's1', batchId: 'b1', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
          { workerId: 2, sessionId: 's2', batchId: 'b2', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
        ],
      },
      {
        operationId: 1,
        attemptId: 'att_01',
        state: 'COMMITTED',
        epoch: 1,
        batchOrdinal: 1,
        inputModelVersion: '0',
        outputModelVersion: '1',
        totalSampleCount: 192,
        timings: { startedAt: 'T-4s', committedAt: 'T-3s', totalDurationMs: 116 },
        workerContributions: [
          { workerId: 0, sessionId: 's0', batchId: 'b0', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
          { workerId: 1, sessionId: 's1', batchId: 'b1', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
          { workerId: 2, sessionId: 's2', batchId: 'b2', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
        ],
      },
    ];

    const result2 = computeStepMetrics(twoSteps);
    assert.equal(result2.length, 2);
    // Chronological order: step 1 first, then step 2
    assert.equal(result2[0].displayStep, '1');
    assert.equal(result2[0].loss, 0.45);
    assert.equal(result2[0].accuracy, 72.0);
    assert.equal(result2[1].displayStep, '2');
    assert.equal(result2[1].loss, 0.21);
    assert.equal(result2[1].accuracy, 89.0);

    // 3. Large step series (500 steps)
    const largeSteps: TrainingStep[] = Array.from({ length: 500 }, (_, i) => ({
      operationId: 500 - i,
      attemptId: 'att_01',
      state: 'COMMITTED',
      epoch: Math.floor(i / 100) + 1,
      batchOrdinal: (500 - i) % 100,
      inputModelVersion: `${500 - i}`,
      outputModelVersion: `${501 - i}`,
      totalSampleCount: 192,
      timings: { startedAt: 'T-10s', committedAt: 'T-1s', totalDurationMs: 120 },
      workerContributions: [
        { workerId: 0, sessionId: 's0', batchId: 'b0', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
        { workerId: 1, sessionId: 's1', batchId: 'b1', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
        { workerId: 2, sessionId: 's2', batchId: 'b2', sampleCount: 64, contributionAccepted: true, parameterApplied: true },
      ],
    }));

    const result500 = computeStepMetrics(largeSteps);
    // Every single step must be preserved — zero data loss
    assert.equal(result500.length, 500);
    assert.equal(result500[0].displayStep, '1');
    assert.equal(result500[499].displayStep, '500');
    assert.equal(typeof result500[499].loss, 'number');
    assert.equal(typeof result500[499].accuracy, 'number');
    assert.equal(typeof result500[499].avgSamplesPerSec, 'number');
  });

  await t.test('computeWorkerBreakdown produces valid stacked bar timings', () => {
    // With undefined step (fallback safe)
    const fallbackBreakdown = computeWorkerBreakdown(undefined, 0);
    assert.equal(fallbackBreakdown.workers.length, 3);
    assert.ok(fallbackBreakdown.syncMaxTime > 0);

    // With explicit duration
    const customStep: TrainingStep = {
      operationId: 10,
      attemptId: 'att_01',
      state: 'COMMITTED',
      epoch: 1,
      batchOrdinal: 10,
      inputModelVersion: '9',
      outputModelVersion: '10',
      totalSampleCount: 192,
      timings: { startedAt: 'T-1s', committedAt: 'T-0s', totalDurationMs: 200 },
      workerContributions: [],
    };

    const breakdown = computeWorkerBreakdown(customStep, 9);
    assert.equal(breakdown.workers.length, 3);
    assert.equal(breakdown.syncMaxTime, 200);
    // Worker 02 is straggler hitting sync barrier
    assert.equal(breakdown.workers[1].syncWait, 0);
    assert.equal(breakdown.workers[1].totalTime, 200);
  });
});
