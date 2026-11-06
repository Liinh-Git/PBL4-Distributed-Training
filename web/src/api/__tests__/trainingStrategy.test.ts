import assert from 'node:assert/strict';
import test from 'node:test';
import { defaultAsyncSettings, trainingStrategyFields } from '../trainingStrategy';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { TrainingStrategySettings } from '../../components/training/TrainingStrategySettings';
import { AsyncProgressPanel } from '../../components/training/AsyncProgressPanel';

test('switching modes never leaks hidden settings into a training contract', () => {
  const async = trainingStrategyFields('async_sgd', 'dbs', 9, defaultAsyncSettings);
  assert.equal(async.workload_policy, 'equal');
  assert.equal('work_units_per_step' in async, false);
  const sync = trainingStrategyFields('strict_bsp', 'dbs', 9, defaultAsyncSettings);
  assert(sync.training_strategy === 'strict_bsp');
  assert.equal('async_training' in sync, false);
  assert.equal(sync.work_units_per_step, 9);
  assert.equal('work_units_per_step' in trainingStrategyFields('strict_bsp', 'equal', undefined, defaultAsyncSettings), false);
});

test('async inputs reject empty, fractional and out-of-range values; zero staleness is valid', () => {
  for (const value of [NaN, -1, 1.5, 1000001]) {
    assert.throws(() => trainingStrategyFields('async_sgd', 'equal', undefined,
      { ...defaultAsyncSettings, staleness_threshold: value }));
  }
  assert.doesNotThrow(() => trainingStrategyFields('async_sgd', 'equal', undefined,
    { ...defaultAsyncSettings, staleness_threshold: 0 }));
});

test('strategy controls render mode-specific inputs and async progress without a BSP barrier', () => {
  const props = { settings: defaultAsyncSettings, onStrategyChange: () => {}, onSettingsChange: () => {} };
  const sync = renderToStaticMarkup(createElement(TrainingStrategySettings, { ...props, strategy: 'strict_bsp' }));
  assert(!sync.includes('name="staleness_threshold"'));
  const async = renderToStaticMarkup(createElement(TrainingStrategySettings, { ...props, strategy: 'async_sgd' }));
  assert(async.includes('name="staleness_threshold"'));
  assert(async.includes('min="0"'));
  const panel = renderToStaticMarkup(createElement(AsyncProgressPanel, {
    progress: { type: 'async_sgd', processed_units: 7, applied_units: 5, dropped_units: 2, target_units: 10 },
    workers: [],
  }));
  assert(panel.includes('value="7" max="10"'));
  assert(panel.includes('Bỏ do quá trễ'));
  assert(!panel.includes('barrier'));
});
