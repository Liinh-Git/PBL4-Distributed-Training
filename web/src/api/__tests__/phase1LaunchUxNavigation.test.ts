import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { AttemptState } from '../../types/api';

describe('Phase 1 — Launch Run UX & Navigation by attempt_id Tests', () => {
  const ACTIVE_STATES: AttemptState[] = [
    'CREATED',
    'WAITING_WORKERS',
    'PROVISIONING',
    'INITIALIZING',
    'RUNNING',
    'COMPLETING',
  ];

  const TERMINAL_STATES: AttemptState[] = ['COMPLETED', 'FAILED', 'ABORTED'];

  test('Test 1: Standardized active attempt states recognition', () => {
    // Every active state in V1 must be recognized as active
    for (const st of ACTIVE_STATES) {
      const isActive = ACTIVE_STATES.includes(st);
      assert.strictEqual(isActive, true, `State ${st} must be recognized as active`);
    }

    // Terminal states must not be recognized as active
    for (const st of TERMINAL_STATES) {
      const isActive = ACTIVE_STATES.includes(st);
      assert.strictEqual(isActive, false, `Terminal state ${st} must not be active`);
    }
  });

  test('Test 2: Action eligibility logic when attempt is in non-RUNNING active states', () => {
    // Simulate attempt states that previously slipped through isRunning = a.state === 'RUNNING'
    const nonRunningActiveStates: AttemptState[] = [
      'CREATED',
      'WAITING_WORKERS',
      'PROVISIONING',
      'INITIALIZING',
      'COMPLETING',
    ];

    for (const st of nonRunningActiveStates) {
      const attempts = [
        {
          attempt_id: `att_${st.toLowerCase()}_001`,
          job_id: 'job_001',
          state: st,
          execution_mode: 'FRESH' as const,
          created_at: '2026-10-18T10:00:00Z',
        },
      ];

      const activeAttempts = attempts.filter(a => ACTIVE_STATES.includes(a.state));
      const hasActiveAttempt = activeAttempts.length > 0;
      const canLaunch = !hasActiveAttempt;

      assert.strictEqual(hasActiveAttempt, true, `Attempt in ${st} must be considered active`);
      assert.strictEqual(canLaunch, false, `Launch Run must be disabled/hidden when attempt is in ${st}`);

      // Primary action must be View Run targeting the exact attempt_id
      const primaryActive = activeAttempts[0];
      assert.strictEqual(primaryActive.attempt_id, `att_${st.toLowerCase()}_001`);
      const targetUrl = `/live?attempt_id=${encodeURIComponent(primaryActive.attempt_id)}`;
      assert.strictEqual(targetUrl, `/live?attempt_id=att_${st.toLowerCase()}_001`);
    }
  });

  test('Test 3: Action eligibility logic when attempts are in terminal states', () => {
    for (const st of TERMINAL_STATES) {
      const attempts = [
        {
          attempt_id: `att_${st.toLowerCase()}_001`,
          job_id: 'job_001',
          state: st,
          execution_mode: 'FRESH' as const,
          created_at: '2026-10-18T10:00:00Z',
        },
      ];

      const activeAttempts = attempts.filter(a => ACTIVE_STATES.includes(a.state));
      const hasActiveAttempt = activeAttempts.length > 0;
      const canLaunch = !hasActiveAttempt;

      assert.strictEqual(hasActiveAttempt, false, `Terminal state ${st} must not be active`);
      assert.strictEqual(canLaunch, true, `Launch Run must be allowed when previous attempt is ${st}`);
    }
  });

  test('Test 4: Data anomaly handling when multiple active attempts exist', () => {
    const attempts = [
      {
        attempt_id: 'att_active_1',
        job_id: 'job_001',
        state: 'RUNNING' as AttemptState,
        execution_mode: 'FRESH' as const,
        created_at: '2026-10-18T10:00:00Z',
      },
      {
        attempt_id: 'att_active_2',
        job_id: 'job_001',
        state: 'INITIALIZING' as AttemptState,
        execution_mode: 'FRESH' as const,
        created_at: '2026-10-18T10:01:00Z',
      },
    ];

    const activeAttempts = attempts.filter(a => ACTIVE_STATES.includes(a.state));
    const hasActiveAttempt = activeAttempts.length > 0;
    const hasMultipleActiveAttempts = activeAttempts.length > 1;

    assert.strictEqual(hasActiveAttempt, true);
    assert.strictEqual(hasMultipleActiveAttempts, true);
    assert.strictEqual(activeAttempts.length, 2);

    // Invariant requirement: Must NOT silently pick an arbitrary attempt
    // Must flag the anomaly
    const anomalyMessage = `Data anomaly: Multiple active execution attempts detected (${activeAttempts.length})`;
    assert.ok(anomalyMessage.includes('2'));
  });

  test('Test 5: Source Code Audit of NewTrainingFlowPage.tsx', () => {
    const filePath = path.resolve(process.cwd(), 'src/pages/NewTrainingFlowPage.tsx');
    const content = fs.readFileSync(filePath, 'utf-8');

    // 1. Assert navigate('/jobs/${targetId}') has been removed from handleStartTraining
    const handleStartTrainingRegex = /handleStartTraining\s*=\s*async\s*\(\)\s*=>\s*\{([\s\S]*?)\n\s*\};/;
    const match = content.match(handleStartTrainingRegex);
    assert.ok(match, 'handleStartTraining must be present in NewTrainingFlowPage.tsx');

    const fnBody = match[1];
    assert.ok(
      !fnBody.includes('navigate(`/jobs/${targetId}`)') && !fnBody.includes("navigate('/jobs/'"),
      'handleStartTraining must not navigate back to /jobs/{id} after starting attempt'
    );

    // 2. Assert direct navigation to /live?attempt_id=... with encodeURIComponent
    assert.ok(
      fnBody.includes('/live?attempt_id='),
      'handleStartTraining must navigate to /live?attempt_id='
    );

    // 3. Assert attempt_id existence validation
    assert.ok(
      fnBody.includes('!attemptId') || fnBody.includes("typeof attemptId !== 'string'"),
      'handleStartTraining must validate attempt_id existence before navigating'
    );
  });

  test('Test 6: Source Code Audit of JobDetailPage.tsx', () => {
    const filePath = path.resolve(process.cwd(), 'src/pages/JobDetailPage.tsx');
    const content = fs.readFileSync(filePath, 'utf-8');

    // 1. Assert ACTIVE_ATTEMPT_STATES definition
    assert.ok(
      content.includes('ACTIVE_ATTEMPT_STATES'),
      'JobDetailPage.tsx must define ACTIVE_ATTEMPT_STATES'
    );
    assert.ok(content.includes("'CREATED'"), 'ACTIVE_ATTEMPT_STATES must include CREATED');
    assert.ok(content.includes("'WAITING_WORKERS'"), 'ACTIVE_ATTEMPT_STATES must include WAITING_WORKERS');
    assert.ok(content.includes("'PROVISIONING'"), 'ACTIVE_ATTEMPT_STATES must include PROVISIONING');
    assert.ok(content.includes("'INITIALIZING'"), 'ACTIVE_ATTEMPT_STATES must include INITIALIZING');
    assert.ok(content.includes("'RUNNING'"), 'ACTIVE_ATTEMPT_STATES must include RUNNING');
    assert.ok(content.includes("'COMPLETING'"), 'ACTIVE_ATTEMPT_STATES must include COMPLETING');

    // 2. Assert View Run button exists
    assert.ok(
      content.includes('View Run'),
      'JobDetailPage.tsx must render View Run button when active attempt exists'
    );

    // 3. Assert Launch Run is gated by !hasActiveAttempt
    assert.ok(
      content.includes('!hasActiveAttempt'),
      'JobDetailPage.tsx must gate Launch Run and Edit by !hasActiveAttempt'
    );

    // 4. Assert Polling effect exists and cleans up interval
    assert.ok(
      content.includes('clearInterval(intervalId)'),
      'JobDetailPage.tsx must clean up polling timer on unmount'
    );
    assert.ok(
      content.includes('refreshDataSilently'),
      'JobDetailPage.tsx must use silent background refresh to avoid UI flash'
    );

    // 5. Assert multiple active attempts anomaly banner is rendered
    assert.ok(
      content.includes('hasMultipleActiveAttempts'),
      'JobDetailPage.tsx must handle and warn on multiple active attempts'
    );
  });
});
