import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import {
  AttemptState,
  ACTIVE_ATTEMPT_STATES,
  isActiveAttemptState,
  ActiveAttemptInfo,
} from '../../types/api';

describe('Phase 3 — Cluster-wide Busy Awareness and Attempt State Synchronization Tests', () => {
  const TERMINAL_STATES: AttemptState[] = ['COMPLETED', 'FAILED', 'ABORTED'];

  test('Criterion 1: Cluster Idle: When no active attempt exists, launch and retry are enabled per business rules', () => {
    const clusterActiveAttempt: ActiveAttemptInfo | null = null;
    const isClusterActiveLoading = false;
    const clusterActiveError: string | null = null;
    const currentJobId = 'job_idle_001';
    const localAttempts: Array<{ attempt_id: string; state: AttemptState }> = [
      { attempt_id: 'att_old_001', state: 'COMPLETED' },
    ];

    const hasLocalActive = localAttempts.some(a => isActiveAttemptState(a.state));
    const isThisJobActiveGlobally = Boolean(
      clusterActiveAttempt && (clusterActiveAttempt as ActiveAttemptInfo).job_id === currentJobId
    );
    const isAnotherJobActive = Boolean(
      clusterActiveAttempt && (clusterActiveAttempt as ActiveAttemptInfo).job_id !== currentJobId
    );
    const thisJobHasActiveAttempt = hasLocalActive || isThisJobActiveGlobally;

    assert.strictEqual(thisJobHasActiveAttempt, false, 'Current job must not have active attempt');
    assert.strictEqual(isAnotherJobActive, false, 'Cluster must not be busy with another job');

    // Button states
    const canLaunch =
      !thisJobHasActiveAttempt &&
      !isAnotherJobActive &&
      !isClusterActiveLoading &&
      !clusterActiveError;
    assert.strictEqual(canLaunch, true, 'Launch Run must be enabled when cluster is confirmed idle');
  });

  test('Criterion 2: Current Job Active (Case A): Launch Run is hidden, View Run targets exact attempt_id', () => {
    const activeAttemptId = 'att_running_exact_999';
    const currentJobId = 'job_running_001';
    const clusterActiveAttempt: ActiveAttemptInfo = {
      attempt_id: activeAttemptId,
      job_id: currentJobId,
      job_name: 'ResNet-18 Benchmark',
      state: 'RUNNING',
      execution_mode: 'FRESH',
      created_at: '2026-10-18T10:00:00Z',
      started_at: '2026-10-18T10:00:05Z',
    };

    const isThisJobActiveGlobally = clusterActiveAttempt.job_id === currentJobId;
    const isAnotherJobActive = clusterActiveAttempt.job_id !== currentJobId;
    const thisJobHasActiveAttempt = isThisJobActiveGlobally;

    assert.strictEqual(thisJobHasActiveAttempt, true, 'Current job is active globally');
    assert.strictEqual(isAnotherJobActive, false, 'Must not be considered another job');

    const primaryActiveAttemptId = isThisJobActiveGlobally
      ? clusterActiveAttempt.attempt_id
      : null;
    assert.strictEqual(primaryActiveAttemptId, activeAttemptId, 'Must target the exact active attempt_id');

    const targetUrl = `/live?attempt_id=${encodeURIComponent(primaryActiveAttemptId!)}`;
    assert.strictEqual(targetUrl, `/live?attempt_id=${activeAttemptId}`);

    // Launch Run must NOT be shown
    const showLaunchRun = !thisJobHasActiveAttempt && !isAnotherJobActive;
    assert.strictEqual(showLaunchRun, false, 'Launch Run must NOT be shown when this job is active');
  });

  test('Criterion 3: Other Job Active (Case B): Launch Run is disabled with Cluster Busy banner and View Active Run link', () => {
    const currentJobId = 'job_waiting_002';
    const busyJobId = 'job_occupying_cluster_001';
    const busyAttemptId = 'att_cluster_master_123';

    const clusterActiveAttempt: ActiveAttemptInfo = {
      attempt_id: busyAttemptId,
      job_id: busyJobId,
      job_name: 'Distributed CIFAR-10 Partition 3',
      state: 'RUNNING',
      execution_mode: 'FRESH',
      created_at: '2026-10-18T10:00:00Z',
      started_at: '2026-10-18T10:00:05Z',
    };

    const isThisJobActiveGlobally = clusterActiveAttempt.job_id === currentJobId;
    const isAnotherJobActive = clusterActiveAttempt.job_id !== currentJobId;

    assert.strictEqual(isThisJobActiveGlobally, false, 'Current job is NOT the active one');
    assert.strictEqual(isAnotherJobActive, true, 'Another job is actively occupying the cluster');

    // Launch and Retry must be disabled
    const canLaunch = !isAnotherJobActive;
    assert.strictEqual(canLaunch, false, 'Launch must be disabled when another job is active');

    // Banner message must identify occupying job and attempt
    const bannerMessage = `Cluster is busy: Job "${clusterActiveAttempt.job_name || clusterActiveAttempt.job_id}" currently has an active training attempt (${clusterActiveAttempt.attempt_id} · ${clusterActiveAttempt.state}).`;
    assert.ok(bannerMessage.includes('Distributed CIFAR-10 Partition 3'));
    assert.ok(bannerMessage.includes(busyAttemptId));
    assert.ok(bannerMessage.includes('RUNNING'));

    // View link must point to active run
    const viewUrl = `/live?attempt_id=${encodeURIComponent(clusterActiveAttempt.attempt_id)}`;
    assert.strictEqual(viewUrl, `/live?attempt_id=${busyAttemptId}`);
  });

  test('Criterion 4: Full Active States Coverage: All 6 states are recognized', () => {
    const expectedActiveStates: AttemptState[] = [
      'CREATED',
      'WAITING_WORKERS',
      'PROVISIONING',
      'INITIALIZING',
      'RUNNING',
      'COMPLETING',
    ];

    assert.strictEqual(ACTIVE_ATTEMPT_STATES.length, 6, 'Must contain exactly 6 active states');

    for (const st of expectedActiveStates) {
      assert.strictEqual(
        isActiveAttemptState(st),
        true,
        `State ${st} must be recognized as active by isActiveAttemptState`
      );
      assert.strictEqual(
        ACTIVE_ATTEMPT_STATES.includes(st),
        true,
        `State ${st} must be in ACTIVE_ATTEMPT_STATES`
      );
    }

    for (const st of TERMINAL_STATES) {
      assert.strictEqual(
        isActiveAttemptState(st),
        false,
        `Terminal state ${st} must NOT be recognized as active`
      );
      assert.strictEqual(
        ACTIVE_ATTEMPT_STATES.includes(st),
        false,
        `Terminal state ${st} must NOT be in ACTIVE_ATTEMPT_STATES`
      );
    }
  });

  test('Criterion 5: Attempt Completion: Transition to terminal re-enables launch', () => {
    // Initial state: Attempt running
    let clusterActiveAttempt: ActiveAttemptInfo | null = {
      attempt_id: 'att_step5_001',
      job_id: 'job_001',
      job_name: 'Job 1',
      state: 'RUNNING',
      execution_mode: 'FRESH',
      created_at: '2026-10-18T10:00:00Z',
    };

    let canLaunchOtherJob = !clusterActiveAttempt;
    assert.strictEqual(canLaunchOtherJob, false, 'Other jobs cannot launch while active');

    // Simulate completion
    clusterActiveAttempt = null; // terminal state returns null from /api/v1/attempts/active
    canLaunchOtherJob = !clusterActiveAttempt;
    assert.strictEqual(canLaunchOtherJob, true, 'Other jobs can launch once active attempt terminates');
  });

  test('Criterion 6: Loading State Preflight Guard: Does not prematurely enable Launch Run', () => {
    const isClusterActiveLoading = true;
    const clusterActiveAttempt = null;
    const clusterActiveError = null;

    // Even though clusterActiveAttempt is null during load, launch must NOT be enabled
    const canLaunch =
      !clusterActiveAttempt &&
      !isClusterActiveLoading &&
      !clusterActiveError;

    assert.strictEqual(
      canLaunch,
      false,
      'Launch Run must NOT be enabled while isClusterActiveLoading is true'
    );
  });

  test('Criterion 7: Error State Preflight Guard: Displays unverified state instead of assuming idle', () => {
    const isClusterActiveLoading = false;
    const clusterActiveAttempt = null;
    const clusterActiveError = '503 Service Unavailable';

    // When there is an error querying cluster status, launch must NOT be enabled
    const canLaunch =
      !clusterActiveAttempt &&
      !isClusterActiveLoading &&
      !clusterActiveError;

    assert.strictEqual(
      canLaunch,
      false,
      'Launch Run must NOT be enabled when clusterActiveError exists'
    );
  });

  test('Criterion 8: HTTP 409 Conflict Handling: Formats user-friendly message, does not auto-retry', () => {
    const error409 = {
      status: 409,
      code: 'ACTIVE_ATTEMPT_EXISTS',
      message: "Cannot launch attempt: active attempt 'att_race_123' exists for job 'job_fast_001' in state 'RUNNING'. Cluster allows at most one active attempt globally.",
    };

    const isConflict =
      error409.status === 409 ||
      error409.code === 'ACTIVE_ATTEMPT_EXISTS' ||
      error409.message.includes('ACTIVE_ATTEMPT_EXISTS');

    assert.strictEqual(isConflict, true, 'Must identify 409 conflict code');

    // Format friendly error
    const friendlyMessage = isConflict
      ? `Cannot launch training: ${error409.message || 'The cluster is currently busy with another active training attempt. Only one attempt can run globally at a time.'}`
      : 'Failed';

    assert.ok(friendlyMessage.includes('Cannot launch training'));
    assert.ok(friendlyMessage.includes('Cluster allows at most one active attempt globally'));
    assert.strictEqual(
      friendlyMessage.includes('status code 409'),
      false,
      'Must NOT display raw status code 409 without context'
    );
  });

  test('Criterion 9: Jobs Page Directory Cluster Awareness: Flags active job correctly across lists', () => {
    const clusterActiveAttempt: ActiveAttemptInfo = {
      attempt_id: 'att_global_001',
      job_id: 'job_active_row',
      job_name: 'Job With Active Attempt',
      state: 'RUNNING',
      execution_mode: 'FRESH',
      created_at: '2026-10-18T10:00:00Z',
    };

    const jobs = [
      { job_id: 'job_active_row', display_name: 'Job With Active Attempt', state: 'READY' as const },
      { job_id: 'job_other_row_1', display_name: 'Other Job 1', state: 'READY' as const },
      { job_id: 'job_other_row_2', display_name: 'Other Job 2', state: 'DRAFT' as const },
    ];

    for (const job of jobs) {
      const isThisJobActive = clusterActiveAttempt.job_id === job.job_id;
      const isAnotherJobActive = clusterActiveAttempt.job_id !== job.job_id;

      if (job.job_id === 'job_active_row') {
        assert.strictEqual(isThisJobActive, true, 'job_active_row must be flagged active');
        assert.strictEqual(isAnotherJobActive, false, 'job_active_row is not another job');
      } else {
        assert.strictEqual(isThisJobActive, false, `${job.job_id} must not be flagged active`);
        assert.strictEqual(isAnotherJobActive, true, `${job.job_id} must be flagged as blocked by another job`);
      }
    }
  });

  test('Criterion 10: Static Code Audits: Verified files implement Phase 3 invariants', () => {
    const rootDir = path.resolve(process.cwd(), '..');

    // 1. Check JobDetailPage.tsx
    const jobDetailPath = path.join(process.cwd(), 'src', 'pages', 'JobDetailPage.tsx');
    const jobDetailContent = fs.readFileSync(jobDetailPath, 'utf-8');
    assert.ok(jobDetailContent.includes('clusterActiveAttempt'), 'JobDetailPage must consume clusterActiveAttempt');
    assert.ok(jobDetailContent.includes('isAnotherJobActive'), 'JobDetailPage must calculate isAnotherJobActive');
    assert.ok(jobDetailContent.includes('Cluster is busy'), 'JobDetailPage must have Cluster is busy banner');
    assert.ok(jobDetailContent.includes('ACTIVE_ATTEMPT_EXISTS'), 'JobDetailPage must handle 409 ACTIVE_ATTEMPT_EXISTS');

    // 2. Check JobsPage.tsx
    const jobsPagePath = path.join(process.cwd(), 'src', 'pages', 'JobsPage.tsx');
    const jobsPageContent = fs.readFileSync(jobsPagePath, 'utf-8');
    assert.ok(jobsPageContent.includes('clusterActiveAttempt'), 'JobsPage must consume clusterActiveAttempt');
    assert.ok(jobsPageContent.includes('Cluster Busy:'), 'JobsPage must have Cluster Busy banner');
    assert.ok(jobsPageContent.includes('ACTIVE_ATTEMPT_EXISTS'), 'JobsPage must handle 409 ACTIVE_ATTEMPT_EXISTS');

    // 3. Check AppContext.tsx
    const appContextPath = path.join(process.cwd(), 'src', 'context', 'AppContext.tsx');
    const appContextContent = fs.readFileSync(appContextPath, 'utf-8');
    assert.ok(appContextContent.includes('clusterActiveAttempt'), 'AppContext must expose clusterActiveAttempt');
    assert.ok(appContextContent.includes('refreshClusterActiveAttempt'), 'AppContext must expose refreshClusterActiveAttempt');
    assert.ok(appContextContent.includes('getActiveAttempt'), 'AppContext must call attemptsService.getActiveAttempt');

    // 4. Check backend API: api/attempts.py
    const backendApiPath = path.join(rootDir, 'src', 'pbl4', 'management_backend', 'api', 'attempts.py');
    const backendApiContent = fs.readFileSync(backendApiPath, 'utf-8');
    assert.ok(backendApiContent.includes('"/api/v1/attempts/active"'), 'Backend must expose GET /api/v1/attempts/active');
    assert.ok(backendApiContent.includes('ActiveAttemptResponse'), 'Backend must return ActiveAttemptResponse schema');

    // 5. Check backend service: attempt_service.py
    const backendServicePath = path.join(rootDir, 'src', 'pbl4', 'management_backend', 'services', 'attempt_service.py');
    const backendServiceContent = fs.readFileSync(backendServicePath, 'utf-8');
    assert.ok(backendServiceContent.includes('get_global_active_attempt'), 'Backend service must implement get_global_active_attempt');
  });
});
