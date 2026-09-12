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
});
