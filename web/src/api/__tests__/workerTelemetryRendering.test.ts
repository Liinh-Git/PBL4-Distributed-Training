import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { WorkerLiveStrip } from '../../components/live/WorkerLiveStrip';
import { CompactSyncViz } from '../../components/training/CompactSyncViz';
import type { TrainingStep, WorkerSession } from '../../types';

const workers = [0, 1].map(workerId => ({
  workerId,
  sessionId: `session-${workerId}`,
  state: 'READY',
})) as WorkerSession[];

function step(state: TrainingStep['state'], values: (boolean | null | undefined)[]): TrainingStep {
  return {
    state,
    workerContributions: values.map((contributionAccepted, workerId) => ({
      workerId,
      sessionId: `session-${workerId}`,
      batchId: 1,
      sampleCount: 64,
      contributionAccepted,
    })),
  } as TrainingStep;
}

function strip(currentStep: TrainingStep): string {
  return renderToStaticMarkup(React.createElement(WorkerLiveStrip, {
    currentStep,
    workers,
    expectedWorkers: 3,
    onSelectWorker: () => {},
    onViewDetails: () => {},
  }));
}

function compact(currentStep: TrainingStep): string {
  return renderToStaticMarkup(React.createElement(CompactSyncViz, {
    currentStep,
    workers,
    expectedWorkers: 3,
    strategyState: { type: 'strict_bsp', accepted_contribution_count: 2, expected_contribution_count: 3 },
    onOpenDetails: () => {},
  }));
}

test('missing telemetry and unobserved slots remain unknown in both views', () => {
  const empty = step('COLLECTING_GRADIENTS', []);
  const live = strip(empty);
  const sync = compact(empty);
  assert.match(live, /Waiting for step telemetry/);
  assert.match(live, /Worker 2 · Waiting for projection/);
  assert.doesNotMatch(live, /All contributions synchronized/);
  assert.match(sync, /Worker 2/);
  assert.match(sync, /Waiting for projection/);
  assert.doesNotMatch(sync, />Received</);
});

test('false stays pending, true is received, and late telemetry updates the views', () => {
  const before = step('COMMITTED', [undefined, false]);
  assert.doesNotMatch(strip(before), /All contributions synchronized/);
  assert.doesNotMatch(compact(before), />Received</);
  assert.match(compact(before), />Pending</);

  const after = step('COMMITTED', [true, false]);
  const live = strip(after);
  const sync = compact(after);
  assert.match(live, />Received</);
  assert.match(live, />Waiting</);
  assert.match(sync, />Received</);
  assert.match(sync, />Pending</);
  assert.match(sync, />Unknown</);
});

test('committed step does not invent parameter application', () => {
  const current = step('COMMITTED', [true, true, true]);
  assert.match(strip(current), /Waiting for worker telemetry projection/);
  current.workerContributions.forEach(contribution => { contribution.parameterApplied = true; });
  assert.match(strip(current), /Parameters applied/);
});
