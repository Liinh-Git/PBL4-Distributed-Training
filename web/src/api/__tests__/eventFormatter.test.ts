import test from 'node:test';
import assert from 'node:assert/strict';
import { formatDiagnosticEvent } from '../../utils/eventFormatter';

test('formatDiagnosticEvent categorization and normalization', async (t) => {
  await t.test('correctly categorizes checkpoint events', () => {
    const cpStarted = formatDiagnosticEvent({
      event_type: 'Checkpoint.started',
      severity: 'INFO',
      details: { checkpoint_id: 'cp_123' },
    });
    assert.equal(cpStarted.category, 'checkpoints');
    assert.equal(cpStarted.iconType, 'normal');

    const cpSaved = formatDiagnosticEvent({
      event_type: 'checkpoint.saved',
      severity: 'INFO',
      details: { checkpoint_id: 'cp_abc_456' },
    });
    assert.equal(cpSaved.category, 'checkpoints');
    assert.equal(cpSaved.iconType, 'success');
  });

  await t.test('correctly categorizes worker and parameter events', () => {
    const paramApplied = formatDiagnosticEvent({
      event_type: 'Parameter.applied',
      severity: 'INFO',
      details: { worker_id: 1 },
    });
    assert.equal(paramApplied.category, 'workers');
    assert.match(paramApplied.humanText, /Worker 1/);

    const gradContrib = formatDiagnosticEvent({
      event_type: 'gradient.contribution_accepted',
      severity: 'INFO',
      details: { worker_id: 0, batch_id: 'b_1' },
    });
    assert.equal(gradContrib.category, 'workers');
  });

  await t.test('correctly categorizes training step and model events', () => {
    const stepStarted = formatDiagnosticEvent({
      event_type: 'Step.started',
      severity: 'INFO',
      details: { step_id: 294 },
    });
    assert.equal(stepStarted.category, 'training');
    assert.match(stepStarted.humanText, /Step #294/);

    const modelUpdated = formatDiagnosticEvent({
      event_type: 'Model.updated',
      severity: 'INFO',
      details: { output_model_version: 295 },
    });
    assert.equal(modelUpdated.category, 'training');
    assert.match(modelUpdated.humanText, /v295/);
  });

  await t.test('correctly categorizes warnings and errors', () => {
    const warning = formatDiagnosticEvent({
      event_type: 'WorkerHeartbeatWarning',
      severity: 'WARN',
      details: { worker_id: 2 },
    });
    assert.equal(warning.category, 'warnings');
    assert.equal(warning.iconType, 'warning');

    const error = formatDiagnosticEvent({
      event_type: 'AttemptFailed',
      severity: 'ERROR',
      details: { error: 'Worker dropped' },
    });
    assert.equal(error.category, 'warnings');
    assert.equal(error.iconType, 'error');
  });
});
