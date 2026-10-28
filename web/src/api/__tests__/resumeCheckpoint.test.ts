import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const source = ts.createSourceFile('ResumeCheckpointModal.tsx',
  fs.readFileSync('src/components/common/ResumeCheckpointModal.tsx', 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function evaluate(expression: string, env: Record<string, any>) {
  const js = ts.transpileModule(`return (${expression});`, {
    fileName: 'modal.tsx', compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText;
  return new Function(...Object.keys(env), js)(...Object.values(env));
}

function declaration(name: string, env: Record<string, any>) {
  let expression: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) expression = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(expression, `${name} exists`);
  return evaluate(expression.getText(source), { useCallback: (callback: unknown) => callback, ...env });
}

const checkpoint = (id = 'checkpoint-1', job = 'job-1', state = 'COMPLETE') => ({
  checkpoint_id: id, job_id: job, state, model_version: 8,
  created_by_attempt_id: 'attempt-old', created_at: '2026-10-26T07:00:00Z',
});

test('checkpoint picker scopes requests to the job and COMPLETE state; pages deduplicate', async () => {
  let rows: any[] = [], selectedId = '', next: string | null = null;
  const calls: any[] = [];
  const env = {
    jobId: 'job-1', requestRef: { current: null as AbortController | null },
    setLoading: () => {}, setError: (err: any) => assert.equal(err, null),
    setCheckpoints: (update: any) => { rows = update(rows); },
    setSelectedId: (id: string) => { selectedId = id; },
    setNextCursor: (cursor: string) => { next = cursor; },
    checkpointsService: { listCheckpoints: async (params: any, options: any) => {
      calls.push(params);
      assert.ok(options.signal instanceof AbortSignal);
      return params.cursor
        ? { data: [checkpoint(), checkpoint('older')], page: { next_cursor: null } }
        : { data: [checkpoint(), checkpoint('writing', 'job-1', 'WRITING'), checkpoint('other', 'job-2')],
          page: { next_cursor: 'page-2' } };
    } },
  };
  const load = declaration('loadCheckpoints', env);
  await load();
  assert.deepEqual(calls[0], { job_id: 'job-1', state: 'COMPLETE', limit: 50, cursor: null });
  assert.deepEqual(rows.map(cp => cp.checkpoint_id), ['checkpoint-1']);
  assert.equal(selectedId, 'checkpoint-1');
  assert.equal(next, 'page-2');
  await load(next);
  assert.deepEqual(rows.map(cp => cp.checkpoint_id), ['checkpoint-1', 'older']);
  assert.equal(selectedId, 'checkpoint-1');
});

function resumeEnvironment(overrides: Record<string, any> = {}) {
  const resumed: string[] = [], requests: any[] = [], errors: any[] = [];
  return {
    canResume: true, loading: false, submittingRef: { current: false },
    selectedCheckpoint: checkpoint(), jobId: 'job-1',
    setSubmitting: () => {}, setError: (error: any) => errors.push(error),
    attemptsService: { assertNoActiveAttempt: async () => {} },
    jobsService: { resumeJob: async (...args: any[]) => {
      requests.push(args);
      return { data: { attempt_id: 'attempt-new' } };
    }, startJob: () => assert.fail('Resume must not launch from scratch') },
    onResumed: (id: string) => resumed.push(id), requests, resumed, errors, ...overrides,
  };
}

test('resume sends the selected checkpoint once and uses the returned new attempt', async () => {
  const env = resumeEnvironment();
  const resume = declaration('handleResume', env);
  await Promise.all([resume(), resume()]);
  assert.deepEqual(env.requests, [['job-1', { checkpoint_id: 'checkpoint-1' }]]);
  assert.deepEqual(env.resumed, ['attempt-new']);
});

test('invalid, absent, loading, and unavailable selections cannot submit resume', async () => {
  for (const overrides of [
    { selectedCheckpoint: undefined }, { selectedCheckpoint: checkpoint('other', 'job-2') },
    { selectedCheckpoint: checkpoint('incomplete', 'job-1', 'WRITING') },
    { loading: true }, { canResume: false },
  ]) {
    const env = resumeEnvironment(overrides);
    await declaration('handleResume', env)();
    assert.deepEqual(env.requests, []);
    assert.deepEqual(env.resumed, []);
  }
});

test('an active attempt blocks resume; backend rejection stays visible without navigation', async () => {
  for (const overrides of [
    { attemptsService: { assertNoActiveAttempt: async () => { throw new Error('Another attempt is active'); } } },
    { jobsService: { resumeJob: async () => { throw new Error('Checkpoint is unavailable'); } } },
  ]) {
    const env = resumeEnvironment(overrides);
    await declaration('handleResume', env)();
    assert.equal(env.errors.filter(Boolean).length, 1);
    assert.deepEqual(env.resumed, []);
    assert.equal(env.submittingRef.current, false);
  }
});

test('empty checkpoint picker explains Launch Run and disables confirmation', () => {
  let markup = '';
  function visit(node: ts.Node) {
    if (ts.isReturnStatement(node) && node.expression?.getText(source).includes('<dialog')) {
      markup = node.expression.getText(source);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  const html = renderToStaticMarkup(evaluate(markup, {
    React, X: () => null, RotateCcw: () => null, dialogRef: { current: null },
    close: () => {}, submitting: false, error: null, loading: false, checkpoints: [],
    nextCursor: null, canResume: true, selectedCheckpoint: undefined, handleResume: () => {},
  }));
  assert.match(html, /No complete checkpoints/);
  assert.match(html, /Use Launch Run/);
  assert.match(html, /disabled=""[^>]*>.*Resume training/s);
});
