import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { asyncProgressPercent, computeAsyncMetrics, selectAsyncProgress } from '../../utils/asyncMetrics';
import { AsyncProgressPanel } from '../../components/training/AsyncProgressPanel';
import { AsyncMetricsDashboard } from '../../components/charts/AsyncMetricsDashboard';
import { AsyncTrainingConsole } from '../../components/training/AsyncTrainingConsole';
import type { AttemptDetailData, RuntimeEventItemData, AttemptSnapshotData } from '../../types/api';

const attempt = { attempt_id: 'a', training_strategy: 'async_sgd' } as AttemptDetailData;
function event(seq: number, details: Record<string, unknown>, time = '2026-11-06T01:00:00Z'): RuntimeEventItemData {
  return { attempt_id: 'a', runtime_event_seq: seq, event_type: 'async.progress', occurred_at: time,
    source_component: 'Coordinator', severity: 'INFO', details };
}

test('async charts consume real progress before epoch 1 and retain stale drops at the same model version', () => {
  const first = event(10, { processed_units: 3, applied_units: 3, dropped_units: 0, processed_samples: 30, model_version: 1, loss: 2.3, staleness: 0 });
  const dropped = event(12, { processed_units: 6, applied_units: 3, dropped_units: 3, processed_samples: 60, model_version: 1, loss: 0, staleness: 7 }, '2026-11-06T01:00:02Z');
  const points = computeAsyncMetrics([dropped, first, first, { ...first, attempt_id: 'other' }, { ...first, event_type: 'step.committed' }], 'a');
  assert.equal(points.length, 2);
  assert.deepEqual(points.map(point => point.processedUnits), [3, 6]);
  assert.deepEqual(points.map(point => point.modelVersion), [1, 1]);
  assert.equal(points[1].loss, 0);
  assert.equal(points[1].droppedUnits, 3);
  assert.equal(points[0].samplesPerSecond, null);
  assert.equal(points[1].samplesPerSecond, 15);
});

test('missing, simultaneous or invalid telemetry never manufactures zero loss or infinite throughput', () => {
  const points = computeAsyncMetrics([
    event(1, { processed_units: 1, processed_samples: 10 }),
    event(2, { processed_units: 2, processed_samples: 20, loss: NaN }),
    event(3, { processed_units: 3, processed_samples: 30 }, 'invalid'),
    event(4, { processed_units: -1 }), event(5, {}),
  ], 'a');
  assert.equal(points.length, 3);
  assert(points.every(point => point.loss === null && point.samplesPerSecond === null));
  assert.equal(points[0].appliedUnits, null);
});

test('replayed async progress restores a missing baseline without waiting for a new contribution', () => {
  const progress = selectAsyncProgress(attempt, null, [event(8, { processed_units: 72, target_units: 3900, completed_epochs: 0, loss: 2.2926 })]);
  assert.equal(progress?.processed_units, 72);
  assert.equal(progress?.completed_epochs, 0);
  assert.equal(asyncProgressPercent(progress), 72 / 3900 * 100);
  assert.equal(selectAsyncProgress(attempt, null, [{ ...event(99, { processed_units: 999 }), attempt_id: 'old' }]), null);
});

test('older replay cannot roll back newer snapshot counters; latest snapshot wins equal-count observations', () => {
  const snapshot = { attempt_id: 'a', runtime_event_seq: 20, strategy_state: {
    type: 'async_sgd', processed_units: 80, target_units: 100, active_workers: 2,
  } } as AttemptSnapshotData;
  assert.equal(selectAsyncProgress(attempt, snapshot, [event(10, { processed_units: 70 })])?.processed_units, 80);
  assert.equal(selectAsyncProgress(attempt, snapshot, [event(19, { processed_units: 80, active_workers: 3 })])?.active_workers, 2);
  assert.equal(selectAsyncProgress({ ...attempt, strategy_state: snapshot.strategy_state }, null, [])?.processed_units, 80);
});

test('unknown totals stay unknown while a measured zero is displayed as zero', () => {
  assert.equal(asyncProgressPercent(null), null);
  assert.equal(asyncProgressPercent({ type: 'async_sgd', processed_units: 0, target_units: 0 }), null);
  assert.equal(asyncProgressPercent({ type: 'async_sgd', processed_units: 0, target_units: 10 }), 0);
  const waiting = renderToStaticMarkup(createElement(AsyncProgressPanel, { workers: [] }));
  assert(waiting.includes('Chờ số liệu'));
  assert(waiting.includes('Chưa nhận được bộ đếm'));
  assert(!waiting.includes('<progress'));
});

test('overview shows overall percentage and completed epochs without equating processed units to completed epochs', () => {
  const panel = renderToStaticMarkup(createElement(AsyncProgressPanel, { workers: [], totalEpochs: 20, attemptState: 'RUNNING',
    progress: { type: 'async_sgd', processed_units: 72, target_units: 3900, completed_epochs: 0, applied_units: 72, dropped_units: 0, loss: 2.2926 },
  }));
  assert(panel.includes('1,8%'));
  assert(panel.includes('0 / 20'));
  assert(panel.includes('Đang hoàn tất epoch 1'));
  assert(panel.includes('value="72" max="3900"'));
  const done = renderToStaticMarkup(createElement(AsyncProgressPanel, { workers: [], totalEpochs: 20, attemptState: 'COMPLETED',
    progress: { type: 'async_sgd', processed_units: 3900, target_units: 3900, completed_epochs: 20 },
  }));
  assert(done.includes('100%'));
  assert(done.includes('Đã hoàn tất huấn luyện'));
  assert(!done.includes('Đang hoàn tất epoch'));
});

test('async metrics render measured charts and explain unavailable accuracy instead of promising BSP epoch metrics', () => {
  const chart = renderToStaticMarkup(createElement(AsyncMetricsDashboard, { attemptId: 'a', stalenessThreshold: 6,
    events: [event(1, { processed_units: 3, loss: 2.3, staleness: 0, applied_units: 3, dropped_units: 0, processed_samples: 30 })],
  }));
  assert(chart.includes('Loss từng lượt: 1 kết quả gần nhất'));
  assert(chart.includes('Độ trễ gradient: 1 kết quả gần nhất'));
  assert(chart.includes('Cần ít nhất hai kết quả'));
  assert(chart.includes('Loss theo epoch'));
  assert(chart.includes('Accuracy theo epoch'));
  assert(!chart.includes('Worker Step Breakdown'));
  assert(!chart.includes('Chờ Epoch 1'));
});

test('async terminal presents measured epoch progress and frozen summaries in the sync terminal style', () => {
  const output = renderToStaticMarkup(createElement(AsyncTrainingConsole, {
    attemptState: 'RUNNING', totalEpochs: 20,
    epochMetrics: [{ epoch_index: 0, sample_count: 49920, training_loss: 2.1, training_accuracy: 0.5 }],
    progress: { type: 'async_sgd', completed_epochs: 1, epoch_progress: {
      epoch_index: 1, processed_units: 39, target_units: 195, sample_count: 9984, training_loss: 1.9, training_accuracy: 40,
    } },
  }));
  assert(output.includes('Training Output'));
  assert(output.includes('Epoch 01/20: hoàn tất'));
  assert(output.includes('2.1000'));
  assert(output.includes('0.50%'));
  assert(output.includes('Epoch 02/20:'));
  assert(output.includes('20%'));
  assert(output.includes('39/195'));
  assert(output.includes('loss tạm tính = 1.9000'));
  assert(!output.includes('barrier'));
});

test('old Runtime telemetry stays unknown per epoch, rather than dividing global work into artificial epoch metrics', () => {
  const output = renderToStaticMarkup(createElement(AsyncTrainingConsole, {
    attemptState: 'RUNNING', totalEpochs: 20, epochMetrics: [],
    progress: { type: 'async_sgd', completed_epochs: 1, processed_units: 250, target_units: 3900 },
  }));
  assert(output.includes('Epoch 01/20: hoàn tất'));
  assert(output.includes('phiên Runtime này chưa ghi metrics epoch'));
  assert(output.includes('Đang chờ bộ đếm riêng theo epoch'));
  assert(!output.includes('loss = 0'));
});

test('epoch charts use finalized epoch history even when recent contribution history is empty', () => {
  const output = renderToStaticMarkup(createElement(AsyncMetricsDashboard, {
    attemptId: 'a', events: [], epochMetrics: [{ epoch_index: 5, sample_count: 49920, training_loss: 1.8, training_accuracy: 65 }],
  }));
  assert(output.includes('Loss theo epoch: 1 kết quả gần nhất'));
  assert(output.includes('Accuracy theo epoch: 1 kết quả gần nhất'));
  assert(!output.includes('Chưa có loss epoch đã chốt'));
});
