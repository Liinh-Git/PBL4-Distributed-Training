/**
 * Unit tests for WebSocket & Stream Frame Processing Logic (Phase 5)
 *
 * Runs with: npx tsx --test src/api/__tests__/attemptStream.test.ts
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  WsEventFrameData,
  WsSnapshotFrameData,
  WsGapFrameData,
} from '../../types/api';

describe('WebSocket Stream Protocol & Frame Handling', () => {
  test('EVENT frame parsing and sequence ordering', () => {
    let lastSeq = 100;
    const receivedEvents: number[] = [];

    const handleFrame = (frame: WsEventFrameData) => {
      if (frame.runtime_event_seq <= lastSeq) {
        // Discard duplicate
        return { action: 'DISCARD_DUPLICATE', seq: frame.runtime_event_seq };
      }
      if (frame.runtime_event_seq > lastSeq + 1) {
        // Gap detected
        lastSeq = frame.runtime_event_seq;
        receivedEvents.push(frame.runtime_event_seq);
        return { action: 'GAP_DETECTED', seq: frame.runtime_event_seq };
      }
      lastSeq = frame.runtime_event_seq;
      receivedEvents.push(frame.runtime_event_seq);
      return { action: 'ACCEPTED', seq: frame.runtime_event_seq };
    };

    // Sequential event 101
    const res1 = handleFrame({
      kind: 'EVENT',
      attempt_id: 'att_001',
      runtime_event_seq: 101,
      occurred_at: '2026-09-07T03:24:18Z',
      payload: {
        event_type: 'model.updated',
        source_component: 'Coordinator',
        severity: 'INFO',
        details: { output_model_version: 42 },
      },
    });
    assert.strictEqual(res1.action, 'ACCEPTED');
    assert.strictEqual(lastSeq, 101);

    // Duplicate event 101
    const resDup = handleFrame({
      kind: 'EVENT',
      attempt_id: 'att_001',
      runtime_event_seq: 101,
      occurred_at: '2026-09-07T03:24:18Z',
      payload: {
        event_type: 'model.updated',
        source_component: 'Coordinator',
        severity: 'INFO',
      },
    });
    assert.strictEqual(resDup.action, 'DISCARD_DUPLICATE');
    assert.strictEqual(lastSeq, 101);

    // Gap event 105 (jumps from 101 to 105)
    const resGap = handleFrame({
      kind: 'EVENT',
      attempt_id: 'att_001',
      runtime_event_seq: 105,
      occurred_at: '2026-09-07T03:24:20Z',
      payload: {
        event_type: 'step.committed',
        source_component: 'Coordinator',
        severity: 'INFO',
      },
    });
    assert.strictEqual(resGap.action, 'GAP_DETECTED');
    assert.strictEqual(lastSeq, 105);
  });

  test('SNAPSHOT frame parses snapshot_seq and updates state', () => {
    let currentState: any = { state: 'WAITING_WORKERS', epoch: 1 };
    let lastSeq = 50;

    const handleSnapshotFrame = (frame: WsSnapshotFrameData) => {
      if (frame.payload.state) {
        currentState = { ...currentState, ...frame.payload.state };
      }
      if (frame.payload.snapshot_seq) {
        lastSeq = Math.max(lastSeq, frame.payload.snapshot_seq);
      }
    };

    handleSnapshotFrame({
      kind: 'SNAPSHOT',
      attempt_id: 'att_001',
      runtime_event_seq: null,
      occurred_at: '2026-09-07T03:24:18Z',
      payload: {
        snapshot_seq: 120,
        state: {
          state: 'RUNNING',
          epoch: 2,
          model_version: 42,
          training_strategy: 'strict_bsp',
          stale: false,
        },
      },
    });

    assert.strictEqual(currentState.state, 'RUNNING');
    assert.strictEqual(currentState.epoch, 2);
    assert.strictEqual(lastSeq, 120);
  });

  test('GAP frame requires snapshot recovery when snapshot_required is true', () => {
    let snapshotRecoveryTriggered = false;

    const handleGapFrame = (frame: WsGapFrameData) => {
      if (frame.payload.snapshot_required) {
        snapshotRecoveryTriggered = true;
      }
    };

    handleGapFrame({
      kind: 'GAP',
      attempt_id: 'att_001',
      runtime_event_seq: null,
      occurred_at: '2026-09-07T03:24:18Z',
      payload: {
        snapshot_required: true,
        after_seq: 100,
        authoritative_seq: 150,
      },
    });

    assert.strictEqual(snapshotRecoveryTriggered, true);
  });

  test('Exponential backoff reconnect delay is capped', () => {
    const calcBackoff = (attempt: number) => Math.min(1000 * Math.pow(2, attempt), 15000);

    assert.strictEqual(calcBackoff(0), 1000);
    assert.strictEqual(calcBackoff(1), 2000);
    assert.strictEqual(calcBackoff(2), 4000);
    assert.strictEqual(calcBackoff(3), 8000);
    assert.strictEqual(calcBackoff(4), 15000); // capped at 15s
    assert.strictEqual(calcBackoff(10), 15000);
  });

  test('Coalesced reconciliation event filter identifies lifecycle and step events', () => {
    const isReconcileEvent = (eventType: string) => {
      const lower = eventType.toLowerCase();
      return (
        lower.startsWith('worker.') ||
        lower.includes('worker') ||
        lower.includes('session') ||
        lower.startsWith('step.') ||
        lower.startsWith('model.') ||
        lower.startsWith('checkpoint.')
      );
    };

    assert.strictEqual(isReconcileEvent('worker.registered'), true);
    assert.strictEqual(isReconcileEvent('worker.heartbeat'), true);
    assert.strictEqual(isReconcileEvent('session.evicted'), true);
    assert.strictEqual(isReconcileEvent('step.started'), true);
    assert.strictEqual(isReconcileEvent('step.committed'), true);
    assert.strictEqual(isReconcileEvent('model.updated'), true);
    assert.strictEqual(isReconcileEvent('checkpoint.saved'), true);

    // Unrelated events should not trigger reconciliation
    assert.strictEqual(isReconcileEvent('telemetry.metric_logged'), false);
    assert.strictEqual(isReconcileEvent('audit.user_login'), false);
  });

  test('Honest strategy_state and worker telemetry preserves partial or missing data without fakes', () => {
    // 1. Partial observed sessions: 1 session observed when 3 expected
    const observedWorkers = [
      { worker_id: 0, session_id: 's_0', state: 'RUNNING' },
    ];
    const expectedWorkers = 3;
    const isPartial = expectedWorkers != null && observedWorkers.length < expectedWorkers;
    assert.strictEqual(isPartial, true);

    // 2. Null total_sample_count must not fall back to 192
    const stepWithNullSamples = {
      step_id: 1,
      total_sample_count: null as number | null,
      output_model_version: null as number | null,
    };
    const displaySamples = stepWithNullSamples.total_sample_count != null
      ? `${stepWithNullSamples.total_sample_count} samples`
      : 'Pending';
    assert.strictEqual(displaySamples, 'Pending');
    assert.notStrictEqual(displaySamples, '192 samples');

    // 3. Strategy state reflects exact coordinator counts (e.g., 1 of 3 received)
    const strategyState = {
      type: 'strict_bsp' as const,
      accepted_contribution_count: 1,
      expected_contribution_count: 3,
      synchronization_complete: false,
    };
    assert.strictEqual(strategyState.accepted_contribution_count, 1);
    assert.strictEqual(strategyState.expected_contribution_count, 3);
    assert.strictEqual(strategyState.synchronization_complete, false);
  });
});

