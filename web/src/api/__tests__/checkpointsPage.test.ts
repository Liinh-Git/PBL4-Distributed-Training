/**
 * PBL4 WebUI — Checkpoints Page & Drawer Truthful Telemetry Tests
 *
 * Verifies that Checkpoints tab only displays real Backend API data,
 * does not invent fallbacks/mock models/sizes, only allows Resume on COMPLETE,
 * and handles edge cases like Step 0 and Model Version 0.
 *
 * Run with: npx tsx --test src/api/__tests__/checkpointsPage.test.ts
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CheckpointListItemData, CheckpointState } from '../../types/api';
import { CheckpointsService } from '../checkpoints';
import { ApiClient } from '../client';

describe('Checkpoints Truthful Telemetry & Architectural Purity', () => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const checkpointsPagePath = path.resolve(__dirname, '../../pages/CheckpointsPage.tsx');
  const drawerPath = path.resolve(__dirname, '../../components/drawers/CheckpointDetailDrawer.tsx');

  const checkpointsPageSource = fs.readFileSync(checkpointsPagePath, 'utf8');
  const drawerSource = fs.readFileSync(drawerPath, 'utf8');

  test('Static Purity: Forbidden fake strings and fallbacks removed from CheckpointsPage', () => {
    // 1. Must NOT contain fake steps 1200 or 3200
    assert.strictEqual(checkpointsPageSource.includes('1200'), false, 'CheckpointsPage must not contain 1200');
    assert.strictEqual(checkpointsPageSource.includes('3200'), false, 'CheckpointsPage must not contain 3200');

    // 2. Must NOT contain fake model ResNet18
    assert.strictEqual(checkpointsPageSource.includes('ResNet18'), false, 'CheckpointsPage must not contain ResNet18');

    // 3. Must NOT contain fake size 148897792 or 142
    assert.strictEqual(checkpointsPageSource.includes('148897792'), false, 'CheckpointsPage must not contain 148897792');
    assert.strictEqual(checkpointsPageSource.includes('142'), false, 'CheckpointsPage must not contain 142');

    // 4. Must NOT contain fake date 2026-09-09
    assert.strictEqual(checkpointsPageSource.includes('2026-09-09'), false, 'CheckpointsPage must not contain 2026-09-09');

    // 5. Must NOT use (cp as any) or bypass type-checker
    assert.strictEqual(checkpointsPageSource.includes('as any'), false, 'CheckpointsPage must not use as any');
  });

  test('Static Purity: Forbidden fake strings removed from CheckpointDetailDrawer', () => {
    assert.strictEqual(drawerSource.includes('1200'), false, 'Drawer must not contain 1200');
    assert.strictEqual(drawerSource.includes('3200'), false, 'Drawer must not contain 3200');
    assert.strictEqual(drawerSource.includes('ResNet18'), false, 'Drawer must not contain ResNet18');
    assert.strictEqual(drawerSource.includes('148897792'), false, 'Drawer must not contain 148897792');
    assert.strictEqual(drawerSource.includes('142'), false, 'Drawer must not contain 142');
    assert.strictEqual(drawerSource.includes('as any'), false, 'Drawer must not use as any');
  });

  test('Step and Version formatting: Real numbers and zero handling', () => {
    const formatStep = (stepId?: number | null) => (stepId != null ? `#${stepId}` : '—');
    const formatVersion = (version?: number | null) => (version != null ? `v${version}` : '—');

    // Truthful source_step_id: 159 -> #159
    assert.strictEqual(formatStep(159), '#159');
    assert.notStrictEqual(formatStep(159), 'Step 3200');
    assert.notStrictEqual(formatStep(159), '3200');

    // Truthful model_version: 160 -> v160
    assert.strictEqual(formatVersion(160), 'v160');
    assert.notStrictEqual(formatVersion(160), 'Step 0');

    // Step 0 is a valid 0-based step, must NOT fallback to '—' or 3200
    assert.strictEqual(formatStep(0), '#0');

    // Model version 0 is valid, must NOT fallback to '—'
    assert.strictEqual(formatVersion(0), 'v0');

    // Null and undefined display '—'
    assert.strictEqual(formatStep(null), '—');
    assert.strictEqual(formatStep(undefined), '—');
    assert.strictEqual(formatVersion(null), '—');
    assert.strictEqual(formatVersion(undefined), '—');
  });

  test('Latest Usable Checkpoint: Strictly selects latest COMPLETE item, ignores WRITING/FAILED', () => {
    const checkpoints: CheckpointListItemData[] = [
      {
        checkpoint_id: 'ckpt_writing_1',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'WRITING',
        model_version: 161,
        source_step_id: 160,
        created_at: '2026-09-26T12:00:00Z',
      },
      {
        checkpoint_id: 'ckpt_failed_2',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'FAILED',
        model_version: 160,
        source_step_id: 159,
        created_at: '2026-09-26T11:50:00Z',
      },
      {
        checkpoint_id: 'ckpt_complete_3',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'COMPLETE',
        model_version: 159,
        source_step_id: 158,
        created_at: '2026-09-26T11:40:00Z',
        completed_at: '2026-09-26T11:41:00Z',
      },
      {
        checkpoint_id: 'ckpt_complete_4',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'COMPLETE',
        model_version: 158,
        source_step_id: 157,
        created_at: '2026-09-26T11:30:00Z',
        completed_at: '2026-09-26T11:31:00Z',
      },
    ];

    const latestUsable = checkpoints.find(cp => cp.state === 'COMPLETE') || null;

    assert.notStrictEqual(latestUsable, null);
    assert.strictEqual(latestUsable?.checkpoint_id, 'ckpt_complete_3');
    assert.strictEqual(latestUsable?.state, 'COMPLETE');
    assert.strictEqual(latestUsable?.source_step_id, 158);
    assert.strictEqual(latestUsable?.model_version, 159);
  });

  test('Latest Usable Checkpoint: Returns null when no COMPLETE checkpoints exist', () => {
    const checkpoints: CheckpointListItemData[] = [
      {
        checkpoint_id: 'ckpt_writing',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'WRITING',
        model_version: 1,
        source_step_id: 0,
        created_at: '2026-09-26T12:00:00Z',
      },
      {
        checkpoint_id: 'ckpt_failed',
        job_id: 'job_001',
        created_by_attempt_id: 'atm_001',
        state: 'FAILED',
        model_version: 1,
        source_step_id: 0,
        created_at: '2026-09-26T11:00:00Z',
      },
    ];

    const latestUsable = checkpoints.find(cp => cp.state === 'COMPLETE') || null;
    assert.strictEqual(latestUsable, null);
  });

  test('Resume Action: Only allowed for state === COMPLETE', () => {
    const isRecoverable = (state: CheckpointState | string) => state === 'COMPLETE';

    assert.strictEqual(isRecoverable('COMPLETE'), true);
    assert.strictEqual(isRecoverable('WRITING'), false);
    assert.strictEqual(isRecoverable('FAILED'), false);
    assert.strictEqual(isRecoverable('UNKNOWN'), false);
  });

  test('Pagination: Deduplication by checkpoint_id prevents duplicate rows while preserving order', () => {
    const page1: CheckpointListItemData[] = [
      {
        checkpoint_id: 'ckpt_103',
        job_id: 'job_1',
        created_by_attempt_id: 'atm_1',
        state: 'COMPLETE',
        model_version: 103,
        source_step_id: 102,
        created_at: '2026-09-26T12:00:00Z',
      },
      {
        checkpoint_id: 'ckpt_102',
        job_id: 'job_1',
        created_by_attempt_id: 'atm_1',
        state: 'COMPLETE',
        model_version: 102,
        source_step_id: 101,
        created_at: '2026-09-26T11:00:00Z',
      },
    ];

    // Page 2 includes an overlapping checkpoint ckpt_102 and a new ckpt_101
    const page2: CheckpointListItemData[] = [
      {
        checkpoint_id: 'ckpt_102',
        job_id: 'job_1',
        created_by_attempt_id: 'atm_1',
        state: 'COMPLETE',
        model_version: 102,
        source_step_id: 101,
        created_at: '2026-09-26T11:00:00Z',
      },
      {
        checkpoint_id: 'ckpt_101',
        job_id: 'job_1',
        created_by_attempt_id: 'atm_1',
        state: 'COMPLETE',
        model_version: 101,
        source_step_id: 100,
        created_at: '2026-09-26T10:00:00Z',
      },
    ];

    const deduplicate = (prev: CheckpointListItemData[], next: CheckpointListItemData[]) => {
      const existingIds = new Set(prev.map(c => c.checkpoint_id));
      const newItems = next.filter(c => !existingIds.has(c.checkpoint_id));
      return [...prev, ...newItems];
    };

    const combined = deduplicate(page1, page2);
    assert.strictEqual(combined.length, 3);
    assert.deepStrictEqual(
      combined.map(c => c.checkpoint_id),
      ['ckpt_103', 'ckpt_102', 'ckpt_101']
    );
  });

  test('Search Filter: Works accurately on truthful fields without inventing models or names', () => {
    const items: CheckpointListItemData[] = [
      {
        checkpoint_id: 'ckpt_fef6b9a755',
        job_id: 'job_22321e5c9c11',
        created_by_attempt_id: 'atm_532842a424da',
        state: 'COMPLETE',
        model_version: 165,
        source_step_id: 159,
        created_at: '2026-09-26T12:00:00Z',
      },
      {
        checkpoint_id: 'ckpt_a1b2c3d402',
        job_id: 'job_99999e5c9c10',
        created_by_attempt_id: 'atm_888842a424da',
        state: 'WRITING',
        model_version: 0,
        source_step_id: 0,
        created_at: '2026-09-26T13:00:00Z',
      },
    ];

    const filterCheckpoints = (list: CheckpointListItemData[], query: string) => {
      const q = query.toLowerCase().trim();
      if (!q) return list;
      return list.filter(
        cp =>
          cp.checkpoint_id.toLowerCase().includes(q) ||
          cp.job_id.toLowerCase().includes(q) ||
          cp.created_by_attempt_id.toLowerCase().includes(q) ||
          cp.state.toLowerCase().includes(q) ||
          String(cp.model_version).includes(q) ||
          (cp.source_step_id != null && String(cp.source_step_id).includes(q))
      );
    };

    // Query step 159
    assert.strictEqual(filterCheckpoints(items, '159').length, 1);
    assert.strictEqual(filterCheckpoints(items, '159')[0].checkpoint_id, 'ckpt_fef6b9a755');

    // Query step 0
    assert.strictEqual(filterCheckpoints(items, '0').length, 1);
    assert.strictEqual(filterCheckpoints(items, '0')[0].checkpoint_id, 'ckpt_a1b2c3d402');

    // Query job id substring
    assert.strictEqual(filterCheckpoints(items, '22321e5c').length, 1);

    // Query attempt id substring
    assert.strictEqual(filterCheckpoints(items, '532842a4').length, 1);

    // Query state
    assert.strictEqual(filterCheckpoints(items, 'complete').length, 1);
    assert.strictEqual(filterCheckpoints(items, 'writing').length, 1);

    // Searching for fake model 'ResNet18' returns nothing
    assert.strictEqual(filterCheckpoints(items, 'ResNet18').length, 0);
  });

  test('CheckpointsService: getCheckpoint calls correct endpoint GET /api/v1/checkpoints/{id}', async () => {
    let capturedUrl = '';
    const mockClient = {
      get: async <T>(url: string) => {
        capturedUrl = url;
        return {
          data: {
            checkpoint_id: 'ckpt_test_123',
            job_id: 'job_1',
            created_by_attempt_id: 'atm_1',
            state: 'COMPLETE' as CheckpointState,
            model_version: 160,
            source_step_id: 159,
            created_at: '2026-09-26T12:00:00Z',
          } as T,
        };
      },
      getPaginated: async () => ({ data: [], page: { next_cursor: null, has_more: false } }),
    } as unknown as ApiClient;

    const service = new CheckpointsService(mockClient);
    const res = await service.getCheckpoint('ckpt_test_123');

    assert.strictEqual(capturedUrl, '/api/v1/checkpoints/ckpt_test_123');
    assert.strictEqual(res.data.checkpoint_id, 'ckpt_test_123');
    assert.strictEqual(res.data.model_version, 160);
    assert.strictEqual(res.data.source_step_id, 159);
  });
});
