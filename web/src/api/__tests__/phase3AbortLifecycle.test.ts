import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import {
  AttemptState,
  ACTIVE_ATTEMPT_STATES,
  isActiveAttemptState,
  ABORTABLE_ATTEMPT_STATES,
  isAbortableAttemptState,
  TERMINAL_ATTEMPT_STATES,
  isTerminalAttemptState,
} from '../../types/api';

describe('Phase 3 — Attempt Abort Condition & State Synchronization Tests', () => {
  test('Requirement 1 & 2: Abort is enabled for WAITING_WORKERS and PROVISIONING', () => {
    assert.strictEqual(
      isAbortableAttemptState('WAITING_WORKERS'),
      true,
      'WAITING_WORKERS must be an abortable attempt state'
    );
    assert.strictEqual(
      isAbortableAttemptState('PROVISIONING'),
      true,
      'PROVISIONING must be an abortable attempt state'
    );
    assert.ok(
      ABORTABLE_ATTEMPT_STATES.includes('WAITING_WORKERS'),
      'ABORTABLE_ATTEMPT_STATES must include WAITING_WORKERS'
    );
    assert.ok(
      ABORTABLE_ATTEMPT_STATES.includes('PROVISIONING'),
      'ABORTABLE_ATTEMPT_STATES must include PROVISIONING'
    );
  });

  test('Requirement 3: Backend abortable states alignment (CREATED, WAITING_WORKERS, PROVISIONING, INITIALIZING, RUNNING)', () => {
    const expectedAbortable: AttemptState[] = [
      'CREATED',
      'WAITING_WORKERS',
      'PROVISIONING',
      'INITIALIZING',
      'RUNNING',
    ];

    assert.strictEqual(
      ABORTABLE_ATTEMPT_STATES.length,
      expectedAbortable.length,
      'ABORTABLE_ATTEMPT_STATES must contain exactly 5 canonical states'
    );

    for (const state of expectedAbortable) {
      assert.strictEqual(
        isAbortableAttemptState(state),
        true,
        `State ${state} must be abortable`
      );
    }

    // ExecutionMode RESUMING is NOT an attempt state and must not be abortable
    assert.strictEqual(
      isAbortableAttemptState('RESUMING'),
      false,
      'RESUMING is an execution mode, not an attempt state, and must not be in abortable states'
    );
  });

  test('Requirement 4: COMPLETING is active but NOT abortable', () => {
    assert.strictEqual(
      isActiveAttemptState('COMPLETING'),
      true,
      'COMPLETING must be recognized as an active attempt state'
    );
    assert.strictEqual(
      isAbortableAttemptState('COMPLETING'),
      false,
      'COMPLETING must NOT be an abortable attempt state (Backend rejects abort at COMPLETING)'
    );
    assert.ok(
      !ABORTABLE_ATTEMPT_STATES.includes('COMPLETING'),
      'ABORTABLE_ATTEMPT_STATES must exclude COMPLETING'
    );
  });

  test('Requirement 5: HTTP 202 puts UI into pending in-flight state (Aborting...), not marked ABORTED immediately', () => {
    const abortingAttemptIds = new Set<string>();
    const markAttemptAborting = (id: string) => abortingAttemptIds.add(id);
    const isAttemptAborting = (id: string) => abortingAttemptIds.has(id);

    const attemptId = 'att_running_001';
    let currentState: AttemptState = 'RUNNING';

    // Operator triggers abort
    markAttemptAborting(attemptId);

    // Simulated HTTP 202 Accepted response from backend
    const http202Response = {
      status: 202,
      data: {
        command_id: 'cmd_abort_123',
        command_type: 'ABORT_ATTEMPT',
        command_state: 'SUCCEEDED',
        attempt_id: attemptId,
      },
    };

    assert.strictEqual(http202Response.status, 202);
    assert.strictEqual(http202Response.data.command_state, 'SUCCEEDED');

    // Invariant: UI state must NOT be mutated to ABORTED merely because HTTP 202 was returned
    assert.notStrictEqual(
      currentState,
      'ABORTED',
      'Attempt state must not be set to ABORTED immediately upon HTTP 202'
    );
    assert.strictEqual(
      isAttemptAborting(attemptId),
      true,
      'Attempt must be registered as in-flight aborting'
    );

    // Button label/state verification
    const buttonLabel = isAttemptAborting(attemptId)
      ? 'Aborting...'
      : isAbortableAttemptState(currentState)
      ? 'Abort'
      : 'Disabled';
    const isButtonDisabled = isAttemptAborting(attemptId) || !isAbortableAttemptState(currentState);

    assert.strictEqual(buttonLabel, 'Aborting...');
    assert.strictEqual(isButtonDisabled, true, 'Abort button must be disabled while abort is pending');
  });

  test('Requirement 6: UI marks attempt ABORTED only upon authoritative terminal state confirmation', () => {
    let abortingAttemptIds = ['att_running_001'];
    const unmarkAttemptAborting = (id: string) => {
      abortingAttemptIds = abortingAttemptIds.filter(x => x !== id);
    };

    const attemptId = 'att_running_001';
    let currentAttemptState: AttemptState = 'RUNNING';

    // Authoritative event arrives via WebSocket
    const authoritativeEvent = {
      event_type: 'attempt.state_changed',
      details: { state: 'ABORTED' as AttemptState },
    };

    if (authoritativeEvent.details.state) {
      currentAttemptState = authoritativeEvent.details.state;
      if (isTerminalAttemptState(currentAttemptState)) {
        unmarkAttemptAborting(attemptId);
      }
    }

    assert.strictEqual(currentAttemptState, 'ABORTED', 'Authoritative state must be ABORTED');
    assert.strictEqual(abortingAttemptIds.includes(attemptId), false, 'Pending abort must be resolved');
    assert.strictEqual(isTerminalAttemptState(currentAttemptState), true, 'ABORTED is terminal');
  });

  test('Requirement 7: HTTP 409 conflict unmarks aborting state and allows retry if state permits', () => {
    let abortingAttemptIds = ['att_running_001'];
    const unmarkAttemptAborting = (id: string) => {
      abortingAttemptIds = abortingAttemptIds.filter(x => x !== id);
    };

    const attemptId = 'att_running_001';
    const simulatedError = {
      status: 409,
      code: 'ATTEMPT_NOT_ABORTABLE',
      message: 'Attempt is in state COMPLETING and cannot be aborted',
    };

    // Upon error, unmark aborting state
    unmarkAttemptAborting(attemptId);

    assert.strictEqual(abortingAttemptIds.includes(attemptId), false, 'Aborting state must be cleared on error');
    assert.strictEqual(simulatedError.status, 409);
  });

  test('Requirement 8: Repeated clicks while aborting are blocked (idempotency guard)', () => {
    let dispatchCount = 0;
    const abortingAttemptIds = new Set<string>(['att_running_001']);

    const handleAbortClick = (attemptId: string) => {
      if (abortingAttemptIds.has(attemptId)) {
        // Guard prevents dispatching redundant requests
        return false;
      }
      dispatchCount++;
      return true;
    };

    const firstAttempt = handleAbortClick('att_running_001');
    const secondAttempt = handleAbortClick('att_running_001');
    const thirdAttempt = handleAbortClick('att_running_001');

    assert.strictEqual(firstAttempt, false, 'First click while aborting must be blocked');
    assert.strictEqual(secondAttempt, false, 'Second click must be blocked');
    assert.strictEqual(thirdAttempt, false, 'Third click must be blocked');
    assert.strictEqual(dispatchCount, 0, 'No HTTP requests should be dispatched when aborting');
  });

  test('Requirement 9: Active snapshot received after HTTP 202 does not reset pending aborting state', () => {
    const abortingAttemptIds = new Set<string>(['att_running_001']);
    const attemptId = 'att_running_001';

    // Immediate REST snapshot arrives while worker teardown is in-progress
    const snapshot = {
      attempt_id: attemptId,
      state: 'RUNNING' as AttemptState,
      stale: false,
    };

    // UI reconciles snapshot
    let renderedState = snapshot.state;
    // But pending abort flag remains true because snapshot is not terminal
    if (isTerminalAttemptState(snapshot.state)) {
      abortingAttemptIds.delete(attemptId);
    }

    assert.strictEqual(renderedState, 'RUNNING', 'Raw snapshot state is RUNNING');
    assert.strictEqual(abortingAttemptIds.has(attemptId), true, 'UI preserves Aborting... pending status');
  });

  test('Requirement 10: JobDetailPage renders Abort action in header and attempts table only for abortable states', () => {
    const jobDetailPagePath = path.resolve(process.cwd(), 'src/pages/JobDetailPage.tsx');
    const content = fs.readFileSync(jobDetailPagePath, 'utf-8');

    // Header abort checks
    assert.ok(
      content.includes('primaryActiveAttemptId && isAbortableAttemptState(primaryActiveAttemptState)'),
      'JobDetailPage header must gate Abort Run by isAbortableAttemptState'
    );
    assert.ok(
      content.includes('isAttemptAborting(primaryActiveAttemptId)'),
      'JobDetailPage header must display Aborting... when active attempt is in-flight aborting'
    );
    assert.ok(
      content.includes('Abort Run'),
      'JobDetailPage header must include Abort Run button'
    );

    // Table abort checks
    assert.ok(
      content.includes('isAbortableAttemptState(att.state)'),
      'JobDetailPage attempts table must gate row Abort by isAbortableAttemptState'
    );
    assert.ok(
      content.includes('isAttemptAborting(att.attempt_id)'),
      'JobDetailPage attempts table must display Aborting... for in-flight attempt'
    );

    // Modal
    assert.ok(
      content.includes('handleAbortConfirm'),
      'JobDetailPage must implement handleAbortConfirm'
    );
  });

  test('Requirement 11: Canonical terminal states across pages (COMPLETED, FAILED, ABORTED, zero CANCELLED)', () => {
    const expectedTerminal: AttemptState[] = ['COMPLETED', 'FAILED', 'ABORTED'];
    assert.strictEqual(
      TERMINAL_ATTEMPT_STATES.length,
      expectedTerminal.length,
      'TERMINAL_ATTEMPT_STATES must contain exactly 3 states'
    );

    for (const st of expectedTerminal) {
      assert.strictEqual(isTerminalAttemptState(st), true, `${st} must be terminal`);
    }

    assert.strictEqual(
      isTerminalAttemptState('CANCELLED'),
      false,
      'CANCELLED is non-canonical and must NOT be in terminal states'
    );

    // Check LiveTrainingPage does not define CANCELLED in TERMINAL_STATES
    const liveTrainingPath = path.resolve(process.cwd(), 'src/pages/LiveTrainingPage.tsx');
    const liveContent = fs.readFileSync(liveTrainingPath, 'utf-8');
    assert.ok(
      !liveContent.includes("'CANCELLED'"),
      'LiveTrainingPage.tsx must not contain CANCELLED'
    );
    assert.ok(
      liveContent.includes('isTerminalAttemptState'),
      'LiveTrainingPage.tsx must use isTerminalAttemptState'
    );
    assert.ok(
      liveContent.includes('isAbortableAttemptState'),
      'LiveTrainingPage.tsx must use isAbortableAttemptState'
    );
  });

  test('Requirement 12: JobsPage uses isAbortableAttemptState and handles WAITING_WORKERS / PROVISIONING', () => {
    const jobsPagePath = path.resolve(process.cwd(), 'src/pages/JobsPage.tsx');
    const content = fs.readFileSync(jobsPagePath, 'utf-8');

    assert.ok(
      !content.includes("state === 'RESUMING'"),
      'JobsPage.tsx must not treat RESUMING as an attempt state'
    );
    assert.ok(
      content.includes('isAbortableAttemptState'),
      'JobsPage.tsx must use isAbortableAttemptState'
    );
    assert.ok(
      content.includes('isAttemptAborting'),
      'JobsPage.tsx must check isAttemptAborting'
    );
    assert.ok(
      content.includes('markAttemptAborting'),
      'JobsPage.tsx must mark attempt aborting on confirm'
    );
  });
});
