import test from 'node:test';
import assert from 'node:assert/strict';
import {
  computeEpochMetricsData,
  EpochMetricData,
  computeStepMetrics,
} from '../../components/charts/LiveTrainingCharts';
import { TrainingStep } from '../../types';

test('Epoch Training Metrics Computation and UI Rendering (Plan V3 Minimal)', async (t) => {
  await t.test('computeEpochMetricsData returns empty array for empty or undefined input', () => {
    assert.deepEqual(computeEpochMetricsData(undefined), []);
    assert.deepEqual(computeEpochMetricsData([]), []);
  });

  await t.test('computeEpochMetricsData correctly processes 4-field finalized epoch metrics', () => {
    const input: EpochMetricData[] = [
      {
        epoch_index: 1,
        sample_count: 60,
        training_loss: 0.8251234,
        training_accuracy: 80.0,
      },
      {
        epoch_index: 0,
        sample_count: 60,
        training_loss: 0.9500123,
        training_accuracy: 71.66667,
      },
      {
        epoch_index: 2,
        sample_count: 0,
        training_loss: null,
        training_accuracy: null,
      },
    ];

    const result = computeEpochMetricsData(input);
    assert.equal(result.length, 3);

    // Epoch 0 sorted first
    assert.equal(result[0].epochIndex, 0);
    assert.equal(result[0].displayEpoch, 'Epoch 1');
    assert.equal(result[0].epochNum, 1);
    assert.equal(result[0].loss, 0.95);
    assert.equal(result[0].accuracy, 71.67);
    assert.equal(result[0].sampleCount, 60);

    // Epoch 1 sorted second
    assert.equal(result[1].epochIndex, 1);
    assert.equal(result[1].displayEpoch, 'Epoch 2');
    assert.equal(result[1].loss, 0.8251);
    assert.equal(result[1].accuracy, 80.0);
    assert.equal(result[1].sampleCount, 60);

    // Epoch 2 with nulls -> loss & accuracy are null, NOT 0
    assert.equal(result[2].epochIndex, 2);
    assert.equal(result[2].displayEpoch, 'Epoch 3');
    assert.equal(result[2].loss, null);
    assert.equal(result[2].accuracy, null);
    assert.equal(result[2].sampleCount, 0);
  });

  await t.test('computeStepMetrics preserves nulls and does not fabricate step metrics', () => {
    const steps: TrainingStep[] = [
      {
        operationId: 1,
        attemptId: 'att-1',
        state: 'COMMITTED',
        epoch: 0,
        batchOrdinal: 0,
        inputModelVersion: 0,
        outputModelVersion: 1,
        totalSampleCount: 16,
        timings: { startedAt: '2026-10-19T10:00:00Z', committedAt: '2026-10-19T10:00:01Z' },
        workerContributions: [],
        metrics: null,
      },
    ];

    const result = computeStepMetrics(steps);
    assert.equal(result.length, 1);
    assert.equal(result[0].loss, null);
    assert.equal(result[0].accuracy, null);
    assert.equal(result[0].operationId, 1);
  });
});
