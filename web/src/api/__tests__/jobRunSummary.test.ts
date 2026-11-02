import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import fs from 'node:fs';
import ts from 'typescript';
import { JobRunSummary, formatExecutionMode } from '../../components/training/JobRunSummary';
import type { AttemptListItemData } from '../../types/api';

const attempt: AttemptListItemData = {
  attempt_id: 'attempt/a b', job_id: 'job-1', state: 'RUNNING', execution_mode: 'RESUME',
  created_at: '2026-11-01T01:00:00Z',
};

function render(props: React.ComponentProps<typeof JobRunSummary>) {
  return renderToStaticMarkup(React.createElement(MemoryRouter, {}, React.createElement(JobRunSummary, props)));
}

test('current execution is distinct from the READY configuration and preserves the exact attempt link', () => {
  const html = render({ attempt, jobState: 'READY', historyAvailable: true });
  assert.match(html, /Current run|Tiến trình đang chạy/);
  assert.match(html, /Running|Đang chạy/);
  assert.match(html, /Resumed from checkpoint|Tiếp tục từ checkpoint/);
  assert.match(html, /href="\/live\?attempt_id=attempt%2Fa%20b"/);
  assert.match(html, /Monitor training|Xem trực tiếp/);
  assert.doesNotMatch(html, />Ready<|>Sẵn sàng</);
});

test('all preparation phases remain current runs', () => {
  for (const state of ['CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING'] as const) {
    const html = render({ attempt: { ...attempt, state }, jobState: 'READY', historyAvailable: true });
    assert.match(html, /Current run|Tiến trình đang chạy/);
    assert.match(html, /Monitor training|Xem trực tiếp/);
  }
});

test('terminal executions remain inspectable without presenting them as live', () => {
  for (const state of ['COMPLETED', 'FAILED', 'ABORTED'] as const) {
    const html = render({ attempt: { ...attempt, state }, jobState: 'ARCHIVED', historyAvailable: true });
    assert.match(html, /Latest run|Lần chạy gần nhất/);
    assert.match(html, /View run details|Xem chi tiết/);
    assert.doesNotMatch(html, /Monitor training|Current run|Tiến trình đang chạy/);
  }
});

test('unavailable history never appears as no executions or a previous successful result', () => {
  for (const value of [undefined, { ...attempt, state: 'COMPLETED' as const }]) {
    const html = render({ attempt: value, jobState: 'READY', historyAvailable: false });
    assert.match(html, /Run status is unavailable|Trạng thái lần chạy không khả dụng/);
    assert.doesNotMatch(html, /No runs yet|Completed|Chưa có lần chạy|Hoàn tất/);
  }
});

test('first-run guidance reflects draft and archived job eligibility', () => {
  assert.match(render({ jobState: 'DRAFT', historyAvailable: true }), /No runs yet.*Review your configuration|Chưa có lần chạy nào.*Xem lại cấu hình/s);
  const archived = render({ jobState: 'ARCHIVED', historyAvailable: true });
  assert.match(archived, /Clone it to create a new job|Clone để tạo nhiệm vụ mới/);
  assert.doesNotMatch(archived, /Launch training|Khởi chạy huấn luyện/);
});

test('fresh, retry and resume are explicit and missing modes stay unknown', () => {
  assert.equal(formatExecutionMode('FRESH'), 'Bắt đầu từ đầu');
  assert.equal(formatExecutionMode('RETRY_FROM_START'), 'Thử lại từ đầu');
  assert.equal(formatExecutionMode('RESUME'), 'Tiếp tục từ checkpoint');
  assert.equal(formatExecutionMode(null), 'Không khả dụng');
});

test('failure codes are escaped and missing timestamps stay absent', () => {
  const html = render({
    attempt: { ...attempt, state: 'FAILED', failure_code: '<worker-failure>', ended_at: 'invalid' },
    jobState: 'READY', historyAvailable: true,
  });
  assert.match(html, /&lt;worker-failure&gt;/);
  assert.match(html, /Open run details to investigate|Mở chi tiết lần chạy để kiểm tra/);
  assert.doesNotMatch(html, /Invalid Date|NaN|undefined/);
});

// Exercise the page's actual history handler, as the launch tests do.
function historyHandler(env: Record<string, unknown>) {
  const source = ts.createSourceFile('JobDetailPage.tsx', fs.readFileSync('src/pages/JobDetailPage.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let expression: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'loadMoreHistory') expression = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(expression);
  const code = ts.transpileModule(`return (${expression.getText(source)});`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(...Object.keys(env), code)(...Object.values(env));
}

test('older history uses the job cursor, deduplicates overlap and keeps latest execution first', async () => {
  const older = { ...attempt, attempt_id: 'older' };
  let rows = [attempt];
  let cursor: string | null = 'page-2';
  const busy: boolean[] = [];
  await historyHandler({
    jobId: 'job-1', historyNextCursor: cursor, historyLoading: false,
    setHistoryLoading: (value: boolean) => busy.push(value), setHistoryError: () => {},
    setAttempts: (update: (previous: AttemptListItemData[]) => AttemptListItemData[]) => { rows = update(rows); },
    setHistoryNextCursor: (value: string | null) => { cursor = value; },
    attemptsService: { listAttempts: async (params: unknown) => {
      assert.deepEqual(params, { job_id: 'job-1', cursor: 'page-2', limit: 50 });
      return { data: [attempt, older], page: { next_cursor: null } };
    } },
  })();
  assert.deepEqual(rows.map(row => row.attempt_id), [attempt.attempt_id, 'older']);
  assert.equal(cursor, null);
  assert.deepEqual(busy, [true, false]);
});

test('failed history pagination preserves existing rows and cursor for retry', async () => {
  const errors: Array<string | null> = [];
  const busy: boolean[] = [];
  await historyHandler({
    jobId: 'job-1', historyNextCursor: 'page-2', historyLoading: false,
    setHistoryLoading: (value: boolean) => busy.push(value),
    setHistoryError: (value: string | null) => errors.push(value),
    setAttempts: () => assert.fail('Existing history must stay visible'),
    setHistoryNextCursor: () => assert.fail('Cursor must remain retryable'),
    attemptsService: { listAttempts: async () => { throw new Error('Backend unavailable'); } },
  })();
  assert.deepEqual(errors, [null, 'Backend unavailable']);
  assert.deepEqual(busy, [true, false]);
});

function runsCallback(name: string, env: Record<string, any>) {
  const file = ts.createSourceFile('TrainingRunsPage.tsx', fs.readFileSync('src/pages/TrainingRunsPage.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let expression: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(file) === name) expression = node.initializer;
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(expression);
  if (ts.isCallExpression(expression)) expression = expression.arguments[0];
  const code = ts.transpileModule(`return (${expression.getText(file)});`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(...Object.keys(env), code)(...Object.values(env));
}

function runMetadata(overrides: Record<string, any> = {}) {
  return {
    attempts: [attempt],
    jobMap: new Map([['job-1', { display_name: 'Job', dataset_build_id: 'build-2', attempt_count: 205, latest_attempt: attempt }]]),
    datasets: [{ dataset_id: 'dataset-1', name: 'Wrong dataset', build_count: 1 }, { dataset_id: 'dataset-2', name: 'Correct dataset' }],
    buildDatasetIds: { 'build-2': 'dataset-2' },
    formatModel: () => 'Model', formatDuration: () => 'Duration',
    ...overrides,
  };
}

test('run rows use the pinned Build dataset and official count instead of the first dataset or loaded-row count', () => {
  const [run] = runsCallback('enrichedRuns', runMetadata())();
  assert.equal(run.datasetId, 'dataset-2');
  assert.equal(run.datasetName, 'Correct dataset');
  assert.equal(run.runNumber, 205);
});

test('missing Build metadata and inconsistent Job snapshots remain unknown', () => {
  const [run] = runsCallback('enrichedRuns', runMetadata({
    buildDatasetIds: {},
    jobMap: new Map([['job-1', { dataset_build_id: 'missing', attempt_count: 205, latest_attempt: { attempt_id: 'different' } }]]),
  }))();
  assert.equal(run.datasetId, undefined);
  assert.equal(run.datasetName, 'Không khả dụng');
  assert.equal(run.runNumber, null);
});

function runPaging() {
  const controller = new AbortController();
  let finish!: (value: any) => void;
  let reject!: (reason: Error) => void;
  const pending = new Promise((yes, no) => { finish = yes; reject = no; });
  let rows = [attempt];
  let cursor: string | null = 'older-runs';
  let error: string | null = null;
  let calls = 0;
  const busy: boolean[] = [];
  const load = runsCallback('loadMoreRuns', {
    historyControllerRef: { current: controller }, loadingMoreRef: { current: false }, nextRunsCursor: cursor,
    setLoadingMore: (value: boolean) => busy.push(value), setHistoryError: (value: string | null) => { error = value; },
    setAttempts: (update: any) => { rows = update(rows); }, setNextRunsCursor: (value: string | null) => { cursor = value; },
    attemptsService: { listAttempts: (params: any, options: any) => {
      assert.deepEqual(params, { limit: 200, cursor: 'older-runs' });
      assert.equal(options.signal, controller.signal);
      calls++;
      return pending;
    } },
  });
  return { load, finish, reject, controller, rows: () => rows, cursor: () => cursor, error: () => error, busy, calls: () => calls };
}

test('run pagination follows the server cursor, deduplicates overlap and coalesces repeated clicks', async () => {
  const h = runPaging();
  const loading = h.load();
  await h.load();
  h.finish({ data: [attempt, { ...attempt, attempt_id: 'older' }], page: { next_cursor: null } });
  await loading;
  assert.equal(h.calls(), 1);
  assert.deepEqual(h.rows().map(row => row.attempt_id), [attempt.attempt_id, 'older']);
  assert.equal(h.cursor(), null);
  assert.deepEqual(h.busy, [true, false]);
});

test('run pagination failures keep loaded rows and retry cursor; disposed views ignore late responses', async () => {
  const failed = runPaging();
  const loading = failed.load();
  failed.reject(new Error('offline'));
  await loading;
  assert.equal(failed.rows().length, 1);
  assert.equal(failed.cursor(), 'older-runs');
  assert.equal(failed.error(), 'offline');
  const disposed = runPaging();
  const late = disposed.load();
  disposed.controller.abort();
  disposed.finish({ data: [{ ...attempt, attempt_id: 'old-response' }], page: { next_cursor: null } });
  await late;
  assert.equal(disposed.rows().length, 1);
  assert.equal(disposed.cursor(), 'older-runs');
});

test('invalid or missing terminal timings do not display NaN or an active duration', () => {
  const duration = runsCallback('formatDuration', {});
  assert.equal(duration('invalid', null, 'COMPLETED'), 'Không khả dụng');
  assert.equal(duration('2026-11-01T00:00:00Z', null, 'FAILED'), 'Không khả dụng');
  assert.equal(duration('2026-11-01T00:00:00Z', 'invalid', 'COMPLETED'), 'Không khả dụng');
  assert.equal(duration('2026-11-01T00:00:00Z', '2026-11-01T00:01:01Z', 'COMPLETED'), '1m 1s');
});
