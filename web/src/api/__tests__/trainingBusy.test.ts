import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ConfirmationModal } from '../../components/common/ConfirmationModal';

function source(path: string) {
  return ts.createSourceFile(path, fs.readFileSync(`src/${path}`, 'utf8'),
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}
function evaluate(expression: string, env: Record<string, any>) {
  const js = ts.transpileModule(`return (${expression});`, {
    fileName: 'busy.tsx', compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText;
  return new Function(...Object.keys(env), js)(...Object.values(env));
}
function buttons(path: string, match: string, env: Record<string, any>) {
  const file = source(path), results: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(file) === 'button'
      && node.getText(file).includes(match)) {
      results.push(renderToStaticMarkup(evaluate(node.getText(file), {
        React, Play: () => null, RotateCcw: () => null,
        RefreshCw: (props: any) => React.createElement('svg', props), ...env,
      })));
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(results.length > 0);
  return results;
}

test('Launch, Run, wizard Start and Resume keep their labels and show spinners while pending', () => {
  const cases: Array<[string, string, Record<string, any>, string]> = [
    ['pages/JobDetailPage.tsx', 'Launch Run',
      { canLaunch: false, actionLoading: 'launch', job: { state: 'READY' } }, 'Launch Run'],
    ['pages/JobsPage.tsx', 'handleLaunch(job.job_id)',
      { loading: false, activeAttempt: null, actionLoading: 'launch_job-1', job: { job_id: 'job-1', state: 'READY' } }, 'Run'],
    ['pages/NewTrainingFlowPage.tsx', 'onClick={handleStartTraining}',
      { hasValidationErrors: false, activeAttempt: null, actionLoading: 'start', isEditMode: false,
        handleStartTraining: () => {} }, 'Start'],
    ['components/common/ResumeCheckpointModal.tsx', 'onClick={() => void handleResume()}',
      { submitting: true, canResume: true, loading: false, selectedCheckpoint: {}, handleResume: () => {} }, 'Resume training'],
  ];
  for (const [path, match, env, label] of cases) {
    for (const html of buttons(path, match, env)) {
      assert.match(html, /disabled=""/);
      assert.match(html, /aria-busy="true"/);
      assert.match(html, /animate-spin/);
      assert.ok(html.includes(label));
      assert.doesNotMatch(html, /Starting|Resuming|cleanup|Preparing/);
    }
  }
});

test('confirmation remains visible with the original label and blocks dismissal while loading', () => {
  const html = renderToStaticMarkup(React.createElement(ConfirmationModal, {
    isOpen: true, isLoading: true, closeOnConfirm: false, title: 'Resume', message: 'Select checkpoint',
    confirmLabel: 'Confirm & Resume', onClose: () => {}, onConfirm: () => {},
  }));
  assert.match(html, /Confirm &amp; Resume/);
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /animate-spin/);
  assert.equal((html.match(/disabled=""/g) || []).length, 3);
});

test('confirmation executes once and stays open until its controlled request completes', async () => {
  const file = source('components/common/ConfirmationModal.tsx');
  let handlerText = '';
  function visit(node: ts.Node) {
    if (ts.isJsxAttribute(node) && node.name.getText(file) === 'onClick'
      && node.initializer?.getText(file).includes('const result = onConfirm()')) {
      handlerText = (node.initializer as ts.JsxExpression).expression!.getText(file);
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(handlerText);
  let finish!: () => void, calls = 0, closes = 0;
  const pending = new Promise<void>(resolve => { finish = resolve; });
  const run = evaluate(handlerText, {
    isLoading: false, confirmingRef: { current: false }, closeOnConfirm: false,
    onConfirm: async () => { calls++; await pending; }, onClose: () => { closes++; },
  });
  const first = run();
  await run();
  assert.equal(calls, 1);
  assert.equal(closes, 0);
  finish();
  await first;
  assert.equal(closes, 0);
});
