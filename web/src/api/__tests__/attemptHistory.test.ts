import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { SharedReads } from '../sharedReads';
import { ApiClient } from '../client';
import { attemptsService } from '../attempts';
import { workersService } from '../workers';
import { stepsService, StepsService } from '../steps';
import { loadAttemptBaseline, loadEpochHistory, HISTORY_CACHE_MS } from '../attemptHistory';
import { StepHistoryControls } from '../../components/training/StepHistoryControls';
import { computeStepMetrics, reconcileStepSelection } from '../../components/charts/LiveTrainingCharts';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test('shared GETs deduplicate without one subscriber cancelling the other', async () => {
  const reads = new SharedReads();
  const pending = deferred<number>();
  const first = new AbortController();
  let calls = 0;
  let sharedSignal!: AbortSignal;
  const load = (signal: AbortSignal) => { calls++; sharedSignal = signal; return pending.promise; };
  const a = reads.read('run-a', load, first.signal);
  const b = reads.read('run-a', load);
  const cancelled = assert.rejects(a, { name: 'AbortError' });
  first.abort();
  await cancelled;
  assert.equal(calls, 1);
  assert.equal(sharedSignal.aborted, false);
  pending.resolve(42);
  assert.equal(await b, 42);
});

test('StrictMode cleanup/remount reuses the pending read', async () => {
  const reads = new SharedReads();
  const pending = deferred<number>();
  const first = new AbortController();
  let calls = 0;
  const load = async () => { calls++; return pending.promise; };
  const a = reads.read('run', load, first.signal);
  const cancelled = assert.rejects(a, { name: 'AbortError' });
  first.abort();
  const b = reads.read('run', load);
  await cancelled;
  pending.resolve(1);
  assert.equal(await b, 1);
  assert.equal(calls, 1);
});

test('leaving a view aborts the underlying read once the final subscriber leaves', async () => {
  const reads = new SharedReads();
  const subscriber = new AbortController();
  const aborted = deferred<void>();
  const request = reads.read('run', signal => new Promise<void>((_, reject) => {
    signal.addEventListener('abort', () => { aborted.resolve(); reject(signal.reason); }, { once: true });
  }), subscriber.signal);
  // Allow the actual loader to subscribe to its signal.
  await Promise.resolve();
  const rejected = assert.rejects(request, { name: 'AbortError' });
  subscriber.abort();
  await Promise.all([rejected, aborted.promise]);
});

test('terminal cache has TTL, bounded capacity, explicit invalidation and attempt isolation', async t => {
  let now = 100;
  t.mock.method(Date, 'now', () => now);
  const reads = new SharedReads(2);
  let calls = 0;
  const load = async () => ++calls;
  assert.equal(await reads.read('a', load, undefined, 60), 1);
  assert.equal(await reads.read('b', load, undefined, 60), 2);
  assert.equal(await reads.read('a', load, undefined, 60), 1);
  assert.equal(await reads.read('c', load, undefined, 60), 3);
  assert.equal(await reads.read('b', load, undefined, 60), 4); // b was evicted
  now = 161;
  assert.equal(await reads.read('b', load, undefined, 60), 5);
  reads.invalidate('b');
  assert.equal(await reads.read('b', load, undefined, 60), 6);
});

test('failed and active reads are retried; an already aborted subscriber starts no work', async () => {
  const reads = new SharedReads();
  await assert.rejects(reads.read('a', async () => { throw new Error('offline'); }, undefined, 60));
  assert.equal(await reads.read('a', async () => 1), 1);
  assert.equal(await reads.read('a', async () => 2), 2);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(reads.read('b', async () => assert.fail('must not fetch'), controller.signal));
});

test('HTTP client shares matching GETs, isolates query/header keys, and never shares mutations', async t => {
  let calls = 0;
  const gate = deferred<void>();
  t.mock.method(globalThis, 'fetch', async () => {
    calls++;
    await gate.promise;
    return new Response(JSON.stringify({ data: calls }), { headers: { 'Content-Type': 'application/json' } });
  });
  const client = new ApiClient('http://localhost');
  const requests = [client.get('/runs'), client.get('/runs'), client.get('/runs', { params: { cursor: 200 } }),
    client.get('/runs', { headers: { Authorization: 'separate-test-context' } }),
    client.post('/runs', {}), client.post('/runs', {})];
  await Promise.resolve();
  assert.equal(calls, 5);
  gate.resolve();
  await Promise.all(requests);
});

function mockBaseline(t: any, attemptId: string, state = 'COMPLETED', stale = false) {
  const detail = t.mock.method(attemptsService, 'getAttempt', async () => ({ data: { attempt_id: attemptId, state } }));
  t.mock.method(attemptsService, 'getSnapshot', async () => ({ data: { state, runtime_event_seq: 10, stale } }));
  t.mock.method(workersService, 'listWorkers', async () => ({ data: [] }));
  const steps = t.mock.method(stepsService, 'listSteps', async (_id: string, params: any) => {
    assert.equal(params.limit, 200);
    assert.equal(params.cursor, undefined);
    return { data: Array.from({ length: 200 }, (_, i) => ({ step_id: 10_000 - i })), page: { next_cursor: '9801' } };
  });
  const events = t.mock.method(attemptsService, 'getCatchUpEvents', async () => ({ data: [], meta: { complete: true } }));
  return { detail, steps, events };
}

test('a 10,000-step attempt opens with one step page and a cached terminal baseline', async t => {
  const mocks = mockBaseline(t, 'terminal-10k');
  const signal = new AbortController().signal;
  const first = await loadAttemptBaseline('terminal-10k', signal);
  const cached = await loadAttemptBaseline('terminal-10k', signal);
  assert.equal(first[3].status, 'fulfilled');
  assert.equal(cached, first);
  assert.equal(mocks.steps.mock.callCount(), 1);
  assert.equal(mocks.detail.mock.callCount(), 1);
  assert.equal(mocks.events.mock.callCount(), 0, 'diagnostic history must not block the overview');
});

test('active baselines remain fresh', async t => {
  const mocks = mockBaseline(t, 'active-10k', 'RUNNING');
  const signal = new AbortController().signal;
  await loadAttemptBaseline('active-10k', signal);
  await loadAttemptBaseline('active-10k', signal);
  assert.equal(mocks.steps.mock.callCount(), 2);
});

test('stale terminal data is never reused as a fresh baseline', async t => {
  const mocks = mockBaseline(t, 'stale-10k', 'COMPLETED', true);
  const signal = new AbortController().signal;
  await loadAttemptBaseline('stale-10k', signal);
  await loadAttemptBaseline('stale-10k', signal);
  assert.equal(mocks.steps.mock.callCount(), 2);
});

test('epoch overview follows filtered pages independently of step pagination and caches terminal history', async t => {
  const cursors: number[] = [];
  t.mock.method(attemptsService, 'getCatchUpEvents', async (_id: string, params: any) => {
    assert.equal(params.event_type, 'epoch.metrics.finalized');
    cursors.push(params.after_seq);
    return { data: params.after_seq === 0
      ? Array.from({ length: 100 }, (_, i) => ({ runtime_event_seq: (i + 1) * 100 }))
      : [{ runtime_event_seq: 11_000 }], meta: {} } as any;
  });
  const signal = new AbortController().signal;
  const result = await loadEpochHistory('epochs-test', 0, signal, true);
  assert.equal(result.events.length, 101);
  assert.equal(result.cursor, 11_000);
  await loadEpochHistory('epochs-test', 0, signal, true);
  assert.deepEqual(cursors, [0, 10_000]);
});

test('refresh without a known step stays bounded; reconnect fetches only until the known range', async t => {
  const client = new ApiClient();
  const cursors: unknown[] = [];
  t.mock.method(client, 'getPaginated', async (_path: string, options: any) => {
    cursors.push(options.params.cursor);
    return { data: [{ step_id: options.params.cursor ? 9999 : 10001 }], page: { next_cursor: options.params.cursor ? '9999' : '10001' } } as any;
  });
  const service = new StepsService(client);
  await service.listStepUpdates('run', 0);
  assert.deepEqual(cursors, [undefined]);
  cursors.length = 0;
  const result = await service.listStepUpdates('run', 10000);
  assert.deepEqual(cursors, [undefined, '10001']);
  assert.deepEqual(result.data.map(step => step.step_id), [10001, 9999]);
});

// Execute the production hook callback with controlled network/React state.
function hookCallback(name: string, env: Record<string, any>) {
  const source = ts.createSourceFile('useAttemptStream.ts', fs.readFileSync('src/hooks/useAttemptStream.ts', 'utf8'), ts.ScriptTarget.Latest, true);
  let expression: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) expression = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(expression && ts.isCallExpression(expression));
  const js = ts.transpileModule(`return (${expression.arguments[0].getText(source)});`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(...Object.keys(env), js)(...Object.values(env));
}

function pagingHarness() {
  const controller = new AbortController();
  const pending = deferred<any>();
  let steps: any[] = [{ step_id: 1000, state: 'COMMITTED' }];
  let error: string | null = null;
  let calls = 0;
  const cursor = { current: '801' };
  const seq = { current: 10 };
  const loading = { current: false };
  const load = hookCallback('loadMoreSteps', {
    attemptId: 'paging', lifecycleRef: { current: controller }, isMountedRef: { current: true },
    currentAttemptRef: { current: 'paging' }, loadingMoreRef: loading, nextStepsCursor: cursor.current,
    stepPageCursorsRef: { current: new Set<string>() },
    lastSeqRef: seq, attemptRef: { current: { state: 'RUNNING' } }, HISTORY_CACHE_MS,
    isTerminalAttempt: () => false,
    historyReads: { read: (_key: string, loader: any) => loader(controller.signal) },
    stepsService: { listSteps: async (_id: string, params: any) => { calls++; assert.equal(params.cursor, '801'); return pending.promise; } },
    setLoadingMoreSteps: () => {}, setNextStepsCursor: (value: string | null) => { cursor.current = value; },
    setStepsError: (value: any) => { error = value; },
    setSteps: (update: any) => { steps = update(steps); },
  });
  return { load, pending, controller, seq, cursor, loading,
    steps: () => steps, error: () => error, calls: () => calls };
}

test('terminal overview becomes ready before diagnostic history and ignores background results after disposal', async () => {
  const controller = new AbortController();
  const background = deferred<any[]>();
  const loading: boolean[] = [];
  let eventUpdates = 0;
  let shownAttempt: any;
  const initialize = hookCallback('loadInitialRestState', {
    attemptId: 'background', currentAttemptRef: { current: 'background' }, isMountedRef: { current: true },
    loadAttemptBaseline: async () => [
      { status: 'fulfilled', value: { data: { state: 'COMPLETED' } } },
      { status: 'fulfilled', value: { data: { state: 'COMPLETED', stale: false, runtime_event_seq: 10 } } },
      { status: 'fulfilled', value: { data: [] } },
      { status: 'fulfilled', value: { data: [{ step_id: 10000 }], page: { next_cursor: '9801' } } },
    ],
    loadRecentHistory: () => background.promise,
    isTerminalAttempt: () => true,
    setLoading: (value: boolean) => loading.push(value), setError: () => {},
    setAttempt: (value: any) => { shownAttempt = value; }, setSnapshot: () => {}, setIsStale: () => {},
    updateSeq: () => {}, setWorkers: () => {}, setSteps: () => {}, setStepsError: () => {},
    setNextStepsCursor: () => {},
    setEvents: () => { eventUpdates++; }, mergeRuntimeEvents: () => [],
  });
  assert.equal(await initialize(controller.signal), false, 'confirmed terminal history needs no WebSocket');
  assert.equal(shownAttempt.state, 'COMPLETED');
  assert.deepEqual(loading, [true, false]);
  controller.abort();
  background.resolve([]);
  await Promise.resolve();
  assert.equal(eventUpdates, 0);
});

test('load more coalesces repeated clicks and preserves a newer live step', async () => {
  const h = pagingHarness();
  const request = h.load();
  await h.load();
  h.seq.current = 11;
  h.pending.resolve({ data: [{ step_id: 1000, state: 'COLLECTING_GRADIENTS' }, { step_id: 800, state: 'COMMITTED' }], page: { next_cursor: '601' } });
  await request;
  assert.equal(h.calls(), 1);
  assert.deepEqual(h.steps(), [{ step_id: 1000, state: 'COMMITTED' }, { step_id: 800, state: 'COMMITTED' }]);
  assert.equal(h.cursor.current, '601');
  assert.equal(h.loading.current, false);
});

test('page failure keeps loaded rows and the retry cursor', async () => {
  const h = pagingHarness();
  const request = h.load();
  h.pending.reject(new Error('offline'));
  await request;
  assert.equal(h.cursor.current, '801');
  assert.equal(h.steps().length, 1);
  assert.match(h.error()!, /Không thể tải/);
  assert.equal(h.loading.current, false);
});

test('a response from a disposed attempt cannot alter current rows or pagination', async () => {
  const h = pagingHarness();
  const request = h.load();
  h.controller.abort();
  h.pending.resolve({ data: [{ step_id: 800 }], page: { next_cursor: '601' } });
  await request;
  assert.equal(h.steps().length, 1);
  assert.equal(h.cursor.current, '801');
});

test('remaining history loads automatically after the baseline, one page at a time, and pauses on errors', () => {
  const source = ts.createSourceFile('useAttemptStream.ts', fs.readFileSync('src/hooks/useAttemptStream.ts', 'utf8'), ts.ScriptTarget.Latest, true);
  let effect: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect'
      && node.arguments[0]?.getText(source).includes('void loadMoreSteps()')) effect = node.arguments[0];
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(effect);
  const js = ts.transpileModule(`return (${effect.getText(source)});`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  let queued: (() => void) | undefined;
  let loads = 0;
  let cancelled = false;
  const env = {
    attemptId: 'automatic', loading: false, loadingMoreSteps: false, stepsError: null, nextStepsCursor: '801',
    loadMoreSteps: () => { loads++; },
    setTimeout: (callback: () => void) => { queued = callback; return 1; },
    clearTimeout: () => { cancelled = true; },
  };
  const schedule = (overrides = {}) => {
    queued = undefined;
    const values = { ...env, ...overrides };
    return new Function(...Object.keys(values), js)(...Object.values(values))();
  };
  for (const override of [{ loading: true }, { loadingMoreSteps: true }, { stepsError: 'offline' }, { nextStepsCursor: null }, { attemptId: null }]) {
    assert.equal(schedule(override), undefined);
    assert.equal(queued, undefined);
  }
  const cleanup = schedule();
  assert.equal(loads, 0, 'first render must not wait for older pages');
  assert.ok(queued);
  queued();
  assert.equal(loads, 1);
  cleanup();
  assert.equal(cancelled, true, 'switching attempts cancels the scheduled page');
});

test('background loading renders no technical status panel; only failures expose a retry action', () => {
  const render = (error: string | null) => renderToStaticMarkup(React.createElement(StepHistoryControls, { error, onRetry: () => {} }));
  assert.equal(render(null), '');
  assert.match(render('Không thể tải đầy đủ lịch sử.'), /role="alert"/);
  assert.match(render('Không thể tải đầy đủ lịch sử.'), /Thử lại/);
  assert.doesNotMatch(render('Không thể tải đầy đủ lịch sử.'), /Đã tải|200 step|Biểu đồ step/);
});

test('equal sized step pages from different attempts never reuse old chart values', () => {
  const step = { stepId: 10000, operationId: 10000, attemptId: 'old', state: 'COMMITTED', metrics: { loss: 1 } } as any;
  assert.equal(computeStepMetrics([step])[0].loss, 1);
  const updated = { ...step, attemptId: 'new', metrics: { loss: 2 } };
  assert.equal(computeStepMetrics([updated])[0].loss, 2);
  assert.equal(computeStepMetrics([{ ...updated, metrics: { loss: 3 } }])[0].loss, 3);
});

test('loading older pages keeps the selected step identity while live followers stay at the newest step', () => {
  assert.equal(reconcileStepSelection([9801, 9802, 9803], [9799, 9800, 9801, 9802, 9803], 1), 3);
  assert.equal(reconcileStepSelection([9801, 9802, 9803], [9801, 9802, 9803, 9804], 2), 3);
  assert.equal(reconcileStepSelection([9801], [], 0), 0);
});
