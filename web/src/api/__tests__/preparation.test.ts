import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getPreparationStatus } from '../../utils/preparation';
import { PreparationStatus } from '../../components/live/PreparationStatus';

const workers = (...states: string[]) => states.map(state => ({ state }));

test('DTP connection, dataset verification and readiness remain distinct for arbitrary membership', () => {
  const status = getPreparationStatus('PROVISIONING', workers('PROVISIONING', 'SHARD_READY', 'MODEL_SYNCING', 'READY', 'DISCONNECTED', 'FAILED'));
  assert.equal(status.connected, 4);
  assert.equal(status.dataReady, 3);
  assert.equal(status.ready, 1);
  assert.equal(status.label, 'Preparing dataset');
  assert.match(status.description, /downloading.*or verifying.*cache/);
});

test('preparation panel reports cache preparation without inventing progress or training activity', () => {
  const html = renderToStaticMarkup(React.createElement(PreparationStatus, {
    state: 'PROVISIONING', workers: workers('PROVISIONING', 'PROVISIONING'), expectedWorkers: 2, isStale: false,
  }));
  assert.match(html, /Preparing dataset/);
  assert.match(html, /DTP connected/);
  assert.match(html, /2\/2/);
  assert.match(html, /Dataset verified/);
  assert.match(html, /0\/2/);
  assert.doesNotMatch(html, /Awaiting Gradients|%|ETA|aria-valuenow/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /motion-reduce:animate-none/);
});

test('stale preparation is unknown; terminal and running attempts do not show a download spinner', () => {
  const render = (state: string, isStale = false) => renderToStaticMarkup(React.createElement(PreparationStatus, {
    state, workers: [], expectedWorkers: null, isStale,
  }));
  assert.match(render('PROVISIONING', true), /Last observed: Preparing dataset/);
  assert.match(render('PROVISIONING', true), /Current download and readiness status are unknown/);
  assert.doesNotMatch(render('PROVISIONING', true), /animate-spin/);
  assert.match(render('INITIALIZING'), /Initializing model/);
  assert.match(render('WAITING_WORKERS'), /Waiting for workers/);
  for (const state of ['RUNNING', 'COMPLETED', 'FAILED', 'ABORTED']) assert.equal(render(state), '');
});

const source = ts.createSourceFile('useAttemptStream.ts', fs.readFileSync('src/hooks/useAttemptStream.ts', 'utf8'), ts.ScriptTarget.Latest, true);
function callback(name: string, env: Record<string, any>) {
  let initializer: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) initializer = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(initializer);
  const expression = ts.isCallExpression(initializer) ? initializer.arguments[0] : initializer;
  const js = ts.transpileModule(`return (${expression.getText(source)});`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(...Object.keys(env), js)(...Object.values(env));
}

test('pre-training snapshots with the same event cursor update workers immediately', async () => {
  const ws = { readyState: 1, close: () => assert.fail('valid snapshot must not close socket') };
  const revision = { current: 0 };
  let current: any = null;
  const handler = callback('handleMessage', {
    isMountedRef: { current: true }, wsRef: { current: ws }, ws, WebSocket: { OPEN: 1 }, attemptId: 'attempt',
    lastSeqRef: { current: 0 }, snapshotRevisionRef: revision,
    setWorkers: (value: any) => { current = value; }, setSnapshot: () => {}, setAttempt: () => {},
    setIsStale: () => {}, updateSeq: (seq: number) => assert.equal(seq, 0), triggerCoalescedRefresh: () => {},
  });
  for (const state of ['PROVISIONING', 'SHARD_READY']) {
    const value = [{ worker_id: 0, session_id: '100', state }];
    await handler({ data: JSON.stringify({ kind: 'SNAPSHOT', attempt_id: 'attempt', payload: {
      snapshot_seq: 0, state: { state: 'PROVISIONING', workers: value, stale: false },
    } }) });
    assert.deepEqual(current, value);
  }
  assert.equal(revision.current, 2);
});

test('slow REST at cursor zero cannot replace newer WebSocket preparation data', async () => {
  let release!: (value: unknown) => void;
  const pending = new Promise(resolve => { release = resolve; });
  const revision = { current: 0 };
  const refresh = callback('refreshSnapshot', {
    attemptId: 'attempt', refreshInFlightRef: { current: null }, lastSeqRef: { current: 0 }, snapshotRevisionRef: revision,
    lifecycleRef: { current: null }, historyReads: { invalidate: () => {} },
    isMountedRef: { current: true }, currentAttemptRef: { current: 'attempt' }, stepsRef: { current: [] },
    attemptsService: { getSnapshot: () => pending }, workersService: { listWorkers: () => pending },
    stepsService: { listStepUpdates: async () => ({ data: [] }) },
    setStepsError: () => {}, setNextStepsCursor: () => {},
    setSnapshot: () => assert.fail('old snapshot overwrote live snapshot'),
    setWorkers: () => assert.fail('old workers overwrote live workers'),
    setIsStale: () => {}, setAttempt: () => {}, setSteps: () => {},
  });
  const request = refresh();
  revision.current += 1;
  release({ data: { runtime_event_seq: 0, stale: false } });
  await request;
});

test('training events update barrier, timing and worker metrics without REST requests', async () => {
  const ws = { readyState: 1, close: () => assert.fail('valid event must not close socket') };
  const cursor = { current: 0 };
  let snapshot: any = { model_version: 0, epoch: 0 };
  let steps: any[] = [];
  let workers: any[] = [{ worker_id: 0, session_id: '101', local_model_version: 0 }];
  const handler = callback('handleMessage', {
    isMountedRef: { current: true }, wsRef: { current: ws }, ws, WebSocket: { OPEN: 1 },
    attemptId: 'attempt', lastSeqRef: cursor, snapshotRevisionRef: { current: 0 },
    pendingEventsRef: { current: [] }, EVENT_WINDOW: 1024,
    updateSeq: (seq: number) => { cursor.current = seq; },
    setSnapshot: (update: any) => { snapshot = update(snapshot); },
    setSteps: (update: any) => { steps = update(steps); },
    setWorkers: (update: any) => { workers = update(workers); },
    setAttempt: () => {}, setIsStale: () => {},
    triggerCoalescedRefresh: () => assert.fail('ordinary training events must not fetch REST'),
  });
  const send = (event_type: string, details: any) => handler({ data: JSON.stringify({
    kind: 'EVENT', attempt_id: 'attempt', runtime_event_seq: cursor.current + 1,
    occurred_at: '2026-10-31T05:00:00Z', payload: { event_type, details },
  }) });
  const started_at = '2026-10-31T05:00:00Z';
  const committed_at = '2026-10-31T05:00:02Z';
  await send('step.started', {
    step_id: 0, operation_id: 0, input_model_version: 0, epoch: 0, batch_ordinal: 0, started_at,
  });
  await send('gradient.accepted', {
    step_id: 0, strategy_state: { type: 'strict_bsp', accepted_contribution_count: 1 },
  });
  assert.equal(snapshot.strategy_state.accepted_contribution_count, 1);
  await send('model.updated', {
    step_id: 0, output_model_version: 1, total_sample_count: 8,
    update_completed_at: '2026-10-31T05:00:01Z',
    contributions: [{ worker_id: 0, session_id: 101, sample_count: 8, loss: 0.75, compute_ms: 120 }],
  });
  assert.equal(snapshot.model_version, 1);
  assert.equal(steps[0].worker_steps[0].loss, 0.75);
  assert.equal(steps[0].worker_steps[0].compute_ms, 120);
  await send('parameter.applied', { step_id: 0, worker_id: 0, session_id: 101, model_version: 1 });
  assert.equal(workers[0].local_model_version, 1);
  assert.equal(steps[0].worker_steps[0].parameter_applied, true);
  await send('step.committed', {
    step_id: 0, output_model_version: 1, total_sample_count: 8, started_at, committed_at,
    recovery_cursor: { epoch: 1, next_batch_ordinal: 0 },
    strategy_state: { type: 'strict_bsp', state: 'COMMITTED', synchronization_complete: true },
  });
  assert.equal(snapshot.epoch, 1);
  assert.equal(snapshot.current_batch_ordinal, 0);
  assert.equal(snapshot.strategy_state.synchronization_complete, true);
  assert.equal(steps[0].state, 'COMMITTED');
  assert.equal(Date.parse(steps[0].timing.committed_at) - Date.parse(steps[0].timing.started_at), 2000);
  assert.equal(steps[0].worker_steps[0].loss, 0.75);
  assert.equal(cursor.current, 5);
});
