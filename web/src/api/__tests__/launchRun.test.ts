import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AttemptsService, isActiveAttempt } from '../attempts';
import { JobsService } from '../jobs';
import { ApiClient } from '../client';
import type { AttemptListItemData, AttemptState } from '../../types/api';

const activeStates = ['CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING', 'RUNNING', 'COMPLETING'];
const attempt = (state: string, jobId = 'job-1'): AttemptListItemData => ({
  attempt_id: 'attempt/a b', job_id: jobId, state: state as AttemptState,
  execution_mode: 'FRESH', created_at: '2026-10-21T00:00:00Z',
});
const pages = Object.fromEntries(['JobDetailPage', 'JobsPage', 'NewTrainingFlowPage'].map(name => [
  name, ts.createSourceFile(`${name}.tsx`, fs.readFileSync(`src/pages/${name}.tsx`, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX),
]));

// Execute the actual page expressions/handlers using the existing TypeScript compiler.
// No DOM framework or duplicate implementation of the launch flow is required.
function evaluate(text: string, env: Record<string, any>) {
  const js = ts.transpileModule(`return (${text});`, {
    fileName: 'page.tsx', compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText;
  return new Function(...Object.keys(env), js)(...Object.values(env));
}
function declaration(page: string, name: string, env: Record<string, any>) {
  let expression: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(pages[page]) === name) expression = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(pages[page]);
  assert.ok(expression, `${page}.${name} exists`);
  return evaluate(expression.getText(pages[page]), env);
}
function controls(page: string, env: Record<string, any>, select: (text: string) => boolean) {
  const expressions: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isJsxExpression(node) && node.expression && select(node.expression.getText(pages[page]))) {
      expressions.push(node.expression.getText(pages[page]));
      return;
    }
    ts.forEachChild(node, visit);
  }
  visit(pages[page]);
  return expressions.map(text => renderToStaticMarkup(evaluate(text, {
    React, Link: ({ to, children }: any) => React.createElement('a', { href: to }, children),
    Activity: () => null, Play: () => null, Square: () => null, ...env,
  }))).join('');
}
function handlerEnv(overrides: Record<string, any> = {}) {
  const navigations: string[] = [], errors: string[] = [];
  return {
    job: { job_id: 'job-1', state: 'READY' }, jobId: 'job-1', createdJob: { job_id: 'job-1' },
    canLaunch: true, activeAttempt: null, loading: false, actionLoading: null, launching: { current: false },
    selectedNodeIds: [], selectedBuild: { shard_count: 2 },
    jobsService: { startJob: async () => ({ data: attempt('CREATED') }), retryJob: async () => ({ data: attempt('CREATED') }) },
    attemptsService: { assertNoActiveAttempt: async () => {}, getActiveAttempt: async () => null },
    navigate: (url: string) => navigations.push(url), alert: (message: string) => errors.push(message),
    setFormError: (message: string) => { if (message) errors.push(message); },
    setActionLoading: () => {}, setActiveAttempt: () => {}, loadJobData: async () => {}, fetchJobs: async () => {},
    navigations, errors, ...overrides,
  };
}

for (const state of activeStates) {
  test(`${state}: Job Detail shows View Run and no Launch; Jobs preserves Abort eligibility`, () => {
    assert.equal(isActiveAttempt(state), true);
    const active = declaration('JobDetailPage', 'activeAttempt', {
      attempts: [attempt(state)], isActiveAttempt, jobId: 'job-1', systemActiveAttempt: null,
    });
    assert.equal(active.attempt_id, 'attempt/a b');
    const env = handlerEnv({ activeAttempt: active,
      hasActiveAttempt: declaration('JobDetailPage', 'hasActiveAttempt', { activeAttempt: active }), isActiveAttempt,
      isAttemptAbortable: declaration('JobsPage', 'isAttemptAbortable', {}),
      job: { job_id: 'job-1', state: 'READY', latest_attempt: active },
    });
    const detail = controls('JobDetailPage', env, text => text.startsWith('activeAttempt &&') || text.includes("'Launch Run'"));
    assert.match(detail, /View Run/);
    assert.match(detail, /href="\/live\?attempt_id=attempt%2Fa%20b"/);
    assert.doesNotMatch(detail, /Launch Run|<button/);
    const jobs = controls('JobsPage', env, text => text.startsWith('(activeAttempt?.job_id') || text.startsWith('isAttemptAbortable('));
    assert.match(jobs, /View Run/);
    assert.doesNotMatch(jobs, />Run</);
    assert.equal(jobs.includes('>Abort<'), ['CREATED', 'INITIALIZING', 'RUNNING'].includes(state));
    assert.deepEqual(env.navigations, []); // Rendering links has no Start side effect.
  });
}

test('terminal attempts do not block Launch; unknown/loading/other-job states disable it', () => {
  for (const state of ['COMPLETED', 'FAILED', 'ABORTED']) {
    assert.equal(isActiveAttempt(state), false);
    assert.equal(declaration('JobDetailPage', 'activeAttempt', {
      attempts: [attempt(state)], isActiveAttempt, jobId: 'job-1', systemActiveAttempt: null,
    }), null);
  }
  for (const systemActiveAttempt of [undefined, attempt('RUNNING', 'other-job'), null]) {
    const env = handlerEnv({ systemActiveAttempt, activeAttempt: null });
    const allowed = declaration('JobDetailPage', 'canLaunch', env);
    assert.equal(allowed, systemActiveAttempt === null);
    const html = controls('JobDetailPage', { ...env, hasActiveAttempt: false, canLaunch: allowed }, text => text.includes("'Launch Run'"));
    assert.match(html, /Launch Run/);
    assert.equal(html.includes('disabled=""'), !allowed);
  }
  assert.equal(declaration('JobDetailPage', 'canLaunch', handlerEnv({ systemActiveAttempt: null, loading: true })), false);
});

test('global lookup follows all history pages and blocks an active attempt belonging to another job', async t => {
  const service = new AttemptsService();
  const calls: any[] = [];
  t.mock.method(service, 'listAttempts', async (params: any) => {
    calls.push(params);
    return params.cursor ? { data: [attempt('PROVISIONING', 'other-job')], page: { next_cursor: null } }
      : { data: [attempt('COMPLETED')], page: { next_cursor: 'older-page' } };
  });
  assert.equal((await service.getActiveAttempt())?.job_id, 'other-job');
  assert.equal(calls[1].cursor, 'older-page');
  await assert.rejects(service.assertNoActiveAttempt(), /other-job.*still active/);
});

test('global lookup fails closed for API failures and unknown states; terminal-only history is clear', async t => {
  const service = new AttemptsService();
  const mock = t.mock.method(service, 'listAttempts', async () => { throw new Error('offline'); });
  await assert.rejects(service.assertNoActiveAttempt(), /offline/);
  mock.mock.mockImplementation(async () => ({ data: [attempt('UNKNOWN')], page: { next_cursor: null } }));
  await assert.rejects(service.assertNoActiveAttempt(), /Unable to verify/);
  mock.mock.mockImplementation(async () => ({ data: ['COMPLETED', 'FAILED', 'ABORTED'].map(state => attempt(state)), page: { next_cursor: null } }));
  await service.assertNoActiveAttempt();
});

for (const [page, handler, method] of [
  ['NewTrainingFlowPage', 'handleStartTraining', 'startJob'],
  ['JobDetailPage', 'handleLaunch', 'startJob'],
  ['JobDetailPage', 'handleRetry', 'retryJob'],
  ['JobsPage', 'handleLaunch', 'startJob'],
]) {
  test(`${page}.${handler}: one POST, exact attempt route, no new Job, duplicate clicks ignored`, async t => {
    let posts = 0;
    const client = new ApiClient('http://backend');
    t.mock.method(globalThis, 'fetch', async (input: any, init: any) => {
      posts++;
      assert.equal(String(input), `http://backend/api/v1/jobs/job-1/${method === 'retryJob' ? 'retry' : 'start'}`);
      assert.equal(init.method, 'POST');
      return new Response(JSON.stringify({ data: attempt('CREATED') }), { status: 202, headers: { 'Content-Type': 'application/json' } });
    });
    const env = handlerEnv({ jobsService: new JobsService(client) });
    const run = declaration(page, handler, env);
    await Promise.all([run('job-1'), run('job-1')]);
    assert.equal(posts, 1);
    assert.deepEqual(env.navigations, ['/live?attempt_id=attempt%2Fa%20b']);
  });

  test(`${page}.${handler}: backend 409 is shown once without retrying Start`, async t => {
    let posts = 0;
    t.mock.method(globalThis, 'fetch', async () => {
      posts++;
      return new Response(JSON.stringify({ error: { code: 'ACTIVE_ATTEMPT_EXISTS', message: 'Another attempt is active' } }),
        { status: 409, headers: { 'Content-Type': 'application/json' } });
    });
    const env = handlerEnv({ jobsService: new JobsService(new ApiClient('http://backend')) });
    await declaration(page, handler, env)('job-1');
    assert.equal(posts, 1);
    assert.equal(env.errors.length, 1);
    assert.match(env.errors[0], /Another attempt is active/);
    assert.deepEqual(env.navigations, []);
  });

  test(`${page}.${handler}: preflight failure sends no Start or Retry`, async () => {
    const env = handlerEnv({ jobsService: {
      startJob: () => assert.fail('Start must not be called'), retryJob: () => assert.fail('Retry must not be called'),
    }, attemptsService: { assertNoActiveAttempt: async () => { throw new Error('Unable to verify attempts'); }, getActiveAttempt: async () => null } });
    await declaration(page, handler, env)('job-1');
    assert.match(env.errors[0], /Unable to verify attempts/);
    assert.deepEqual(env.navigations, []);
  });
}

test('Create saves exactly one Draft; Save as Draft never sends Start', async () => {
  let creates = 0;
  const env = handlerEnv({
    createdJob: null, isEditMode: false, selectedModel: 'model', supportedModels: [{ model_id: 'model' }],
    workloadPolicy: 'equal', existingWups: undefined, everyNEpochs: 5, jobName: 'Training', jobDescription: '',
    selectedBuildId: 'build', epochs: 2, learningRate: 0.1, seed: 42,
    setValidating: () => {}, setCreatedJob: () => {}, setValidationResult: () => {}, setStep: () => {},
    jobsService: {
      createJob: async () => { creates++; return { data: { job_id: 'job-1', state: 'DRAFT' } }; },
      validateJob: async () => ({ data: { errors: [] } }),
      startJob: () => assert.fail('Saving a Draft must not Start'),
    },
  });
  await declaration('NewTrainingFlowPage', 'handleProceedToReview', env)();
  assert.equal(creates, 1);
  assert.deepEqual(env.errors, []);
  assert.deepEqual(env.navigations, []);
  let saveClick: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isJsxElement(node) && node.getText(pages.NewTrainingFlowPage).includes("'Save as Draft'") && node.openingElement.tagName.getText() === 'button') {
      const attr = node.openingElement.attributes.properties.find(p => ts.isJsxAttribute(p) && p.name.getText() === 'onClick') as ts.JsxAttribute;
      saveClick = (attr.initializer as ts.JsxExpression).expression;
    }
    ts.forEachChild(node, visit);
  }
  visit(pages.NewTrainingFlowPage);
  assert.ok(saveClick);
  let savedStep = 0;
  evaluate(saveClick.getText(pages.NewTrainingFlowPage), { setStep: (step: number) => { savedStep = step; } })();
  assert.equal(savedStep, 5);
  assert.equal(creates, 1);
});
