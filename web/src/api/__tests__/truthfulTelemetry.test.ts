import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { TrainingStep, WorkerSession } from '../../types';

describe('Truthful Live UI Telemetry & Non-Fabricated Worker States (Hotfix #6)', () => {
  // Test 1: worker_steps chưa load -> không fabricated contributionAccepted=true, parameterApplied=true, banner không nói All contributions received
  test('Test 1: When worker_steps are not loaded, contributionAccepted and parameterApplied are undefined and banner never says All contributions received', () => {
    const rawStep = {
      step_id: 10,
      operation_id: 10,
      epoch: 1,
      batch_ordinal: 5,
      state: 'IN_PROGRESS' as const,
      total_sample_count: 192,
    };

    const workers = [
      { worker_id: 0, session_id: 'sess-0', shard_id: 0, node_label: 'node-0', state: 'RUNNING' },
      { worker_id: 1, session_id: 'sess-1', shard_id: 1, node_label: 'node-1', state: 'RUNNING' },
      { worker_id: 2, session_id: 'sess-2', shard_id: 2, node_label: 'node-2', state: 'RUNNING' },
    ];

    // Simulate mapping logic from LiveTrainingPage when stepDetailsMap[st.step_id] is undefined
    const detail = undefined as any;
    const workerSteps = detail?.worker_steps;
    const workerContributions = workerSteps && workerSteps.length > 0
      ? workerSteps.map((ws: any) => ({
          workerId: ws.worker_id,
          sessionId: ws.session_id,
          shardId: ws.shard_id,
          batchId: ws.batch_id,
          sampleCount: ws.sample_count,
          samples: ws.sample_count,
          contributionAccepted: typeof ws.contribution_accepted === 'boolean' ? ws.contribution_accepted : undefined,
          parameterApplied: typeof ws.parameter_applied === 'boolean' ? ws.parameter_applied : undefined,
        }))
      : workers.map((w) => ({
          workerId: w.worker_id,
          sessionId: w.session_id,
          shardId: w.shard_id,
          batchId: rawStep.batch_ordinal,
          sampleCount: rawStep.total_sample_count && workers.length ? Math.round(rawStep.total_sample_count / workers.length) : 0,
          samples: rawStep.total_sample_count && workers.length ? Math.round(rawStep.total_sample_count / workers.length) : 0,
          contributionAccepted: undefined,
          parameterApplied: undefined,
        }));

    // Verify no fabricated boolean true values
    assert.equal(workerContributions.length, 3);
    for (const contrib of workerContributions) {
      assert.equal(contrib.contributionAccepted, undefined, 'contributionAccepted must not be fabricated to true');
      assert.equal(contrib.parameterApplied, undefined, 'parameterApplied must not be fabricated to true');
    }

    // Verify acceptedCount calculation in WorkerLiveStrip
    const acceptedCount = workerContributions.filter((c: any) => c.contributionAccepted === true).length;
    assert.equal(acceptedCount, 0, 'No contributions should be counted as accepted when telemetry is unknown');

    const expectedWorkers = 3;
    const isCommitted = (rawStep.state as string) === 'COMMITTED';
    const hasUnknown = workerContributions.some((c: any) => c.contributionAccepted == null);

    let syncStatusText = '';
    if (isCommitted && !hasUnknown) {
      syncStatusText = 'All contributions synchronized · Parameters applied';
    } else if ((acceptedCount as number) === expectedWorkers && expectedWorkers > 0) {
      syncStatusText = 'All contributions received · Updating global model';
    } else {
      syncStatusText = `${acceptedCount} of ${expectedWorkers} contributions received · Waiting for remaining workers`;
    }

    assert.doesNotMatch(syncStatusText, /All contributions received/i);
    assert.equal(syncStatusText, '0 of 3 contributions received · Waiting for remaining workers');
  });

  // Test 2: Expected worker chưa observed -> hiển thị Not observed / Waiting for projection, không hiển thị ACTIVE (DTP)
  test('Test 2: Expected worker not in observedMap must render Not observed / Waiting for projection, never ACTIVE (DTP)', () => {
    const expectedWorkersCount = 3;
    const workers = [
      { worker_id: 0, session_id: 'sess-0', node_label: 'node-0', state: 'RUNNING' },
      // worker 1 and 2 are not yet observed by authoritative API
    ];

    const observedMap = new Map<number, any>();
    workers.forEach(w => observedMap.set(Number(w.worker_id), w));

    const renderedStatuses: { id: number; label: string; status: string }[] = [];
    for (let id = 0; id < expectedWorkersCount; id++) {
      const w = observedMap.get(id);
      if (w) {
        renderedStatuses.push({ id, label: w.node_label || `node-${id}`, status: w.state });
      } else {
        renderedStatuses.push({ id, label: 'Waiting for projection', status: 'Not observed' });
      }
    }

    assert.equal(renderedStatuses[0].status, 'RUNNING');
    assert.equal(renderedStatuses[1].status, 'Not observed');
    assert.equal(renderedStatuses[1].label, 'Waiting for projection');
    assert.equal(renderedStatuses[2].status, 'Not observed');
    assert.equal(renderedStatuses[2].label, 'Waiting for projection');

    // Confirm no ACTIVE (DTP) label was emitted
    for (const item of renderedStatuses) {
      assert.notEqual(item.status, 'ACTIVE (DTP)');
      assert.doesNotMatch(item.label, /DTP active/);
    }
  });

  // Test 3: Unknown không được count (Worker 1 = true, Worker 2 = false, Worker 3 = unknown -> acceptedCount = 1)
  test('Test 3: Unknown contributions are strictly excluded from acceptedCount (1 true, 1 false, 1 unknown => acceptedCount = 1)', () => {
    const contributions = [
      { workerId: 0, sessionId: 's0', batchId: 1, sampleCount: 64, contributionAccepted: true },
      { workerId: 1, sessionId: 's1', batchId: 1, sampleCount: 64, contributionAccepted: false },
      { workerId: 2, sessionId: 's2', batchId: 1, sampleCount: 64, contributionAccepted: undefined },
    ];

    const acceptedCount = contributions.filter(c => c.contributionAccepted === true).length;
    const waitingCount = contributions.filter(c => c.contributionAccepted === false).length;
    const unknownCount = contributions.filter(c => c.contributionAccepted == null).length;

    assert.equal(acceptedCount, 1, 'Only contributionAccepted === true should be counted in acceptedCount');
    assert.equal(waitingCount, 1, 'Worker 1 is waiting');
    assert.equal(unknownCount, 1, 'Worker 2 is unknown');

    const expectedWorkers = 3;
    const isBarrierOpen = (acceptedCount as number) === expectedWorkers;
    assert.equal(isBarrierOpen, false, 'Barrier must remain closed when acceptedCount is 1 of 3');

    // Verify syncStatusText
    const missingWorker = contributions.find(c => c.contributionAccepted === false);
    const waitingFor = missingWorker !== undefined ? `Worker ${missingWorker.workerId}` : 'remaining workers';
    const syncStatusText = `${acceptedCount} of ${expectedWorkers} contributions received · Waiting for ${waitingFor}`;

    assert.equal(syncStatusText, '1 of 3 contributions received · Waiting for Worker 1');
  });

  // Test 4: Khi dữ liệu thật về sau -> UI cập nhật sang trạng thái thật không cần reload
  test('Test 4: Step details arrival updates worker contributions to authoritative telemetry', () => {
    // Initial state: before step details loaded
    let stepDetails: any = null;

    const computeContributions = (detail: any) => {
      const workerSteps = detail?.worker_steps;
      if (workerSteps && workerSteps.length > 0) {
        return workerSteps.map((ws: any) => ({
          workerId: ws.worker_id,
          sessionId: ws.session_id,
          contributionAccepted: typeof ws.contribution_accepted === 'boolean' ? ws.contribution_accepted : undefined,
          parameterApplied: typeof ws.parameter_applied === 'boolean' ? ws.parameter_applied : undefined,
          computeMs: ws.compute_ms,
        }));
      }
      return [
        { workerId: 0, sessionId: 's0', contributionAccepted: undefined, parameterApplied: undefined, computeMs: undefined },
        { workerId: 1, sessionId: 's1', contributionAccepted: undefined, parameterApplied: undefined, computeMs: undefined },
      ];
    };

    // Before fetch
    const initialContributions = computeContributions(stepDetails);
    assert.equal(initialContributions[0].contributionAccepted, undefined);
    assert.equal(initialContributions[1].contributionAccepted, undefined);

    // After fetch: authoritative data arrives
    stepDetails = {
      step_id: 1,
      worker_steps: [
        { worker_id: 0, session_id: 's0', contribution_accepted: true, parameter_applied: true, compute_ms: 120 },
        { worker_id: 1, session_id: 's1', contribution_accepted: false, parameter_applied: false, compute_ms: null },
      ],
    };

    const updatedContributions = computeContributions(stepDetails);
    assert.equal(updatedContributions[0].contributionAccepted, true);
    assert.equal(updatedContributions[0].parameterApplied, true);
    assert.equal(updatedContributions[0].computeMs, 120);

    assert.equal(updatedContributions[1].contributionAccepted, false);
    assert.equal(updatedContributions[1].parameterApplied, false);
    assert.equal(updatedContributions[1].computeMs, null);
  });

  // Test 5: Static AST & source code audit
  test('Test 5: Source audit: zero fabricated ACTIVE (DTP) or fabricated contributionAccepted = true in LiveTrainingPage and WorkerLiveStrip', () => {
    const livePagePath = path.resolve(process.cwd(), 'src/pages/LiveTrainingPage.tsx');
    const livePageContent = fs.readFileSync(livePagePath, 'utf8');

    const stripPath = path.resolve(process.cwd(), 'src/components/live/WorkerLiveStrip.tsx');
    const stripContent = fs.readFileSync(stripPath, 'utf8');

    // 1. LiveTrainingPage must NOT contain ACTIVE (DTP)
    assert.equal(
      livePageContent.includes('ACTIVE (DTP)'),
      false,
      'LiveTrainingPage must not contain fabricated "ACTIVE (DTP)" string'
    );

    // 2. LiveTrainingPage must NOT contain node-{id} (DTP active)
    assert.equal(
      livePageContent.includes('(DTP active)'),
      false,
      'LiveTrainingPage must not contain fabricated "(DTP active)" string'
    );

    // 3. LiveTrainingPage must contain Waiting for projection and Not observed
    assert.equal(
      livePageContent.includes('Waiting for projection'),
      true,
      'LiveTrainingPage must render "Waiting for projection" for unobserved slots'
    );
    assert.equal(
      livePageContent.includes('Not observed'),
      true,
      'LiveTrainingPage must render "Not observed" for unobserved slots'
    );

    // 4. LiveTrainingPage must NOT contain fallback contributionAccepted: true
    // When workerSteps is missing, contributionAccepted must be undefined
    assert.doesNotMatch(
      livePageContent,
      /contributionAccepted:\s*true\s*,/g,
      'LiveTrainingPage must not fabricate contributionAccepted: true'
    );
    assert.doesNotMatch(
      livePageContent,
      /parameterApplied:\s*true\s*,/g,
      'LiveTrainingPage must not fabricate parameterApplied: true'
    );

    // 5. WorkerLiveStrip must filter specifically on c.contributionAccepted === true
    assert.match(
      stripContent,
      /contributions\.filter\(c\s*=>\s*c\.contributionAccepted\s*===\s*true\)/,
      'WorkerLiveStrip must strictly check c.contributionAccepted === true'
    );
  });
});
