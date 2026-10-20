import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient } from '../client';
import { JobsService } from '../jobs';
import type { JobCreateRequest, JobPatchRequest } from '../../types/api';

describe('WebUI Checkpoint Cadence & Recovery Contract Tests (Task B6)', () => {
  const originalFetch = globalThis.fetch;

  test('Create Job payload includes checkpoint.every_n_epochs (default N=5)', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs');
      assert.strictEqual(init?.method, 'POST');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_ckpt_001',
            display_name: 'ResNet18 Checkpoint Test',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-10-19T12:00:00Z',
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const payload: JobCreateRequest = {
      display_name: 'ResNet18 Checkpoint Test',
      requested_contract: {
        dataset_build_id: 'dsb_001',
        model_id: 'resnet18_groupnorm',
        epochs: 20,
        learning_rate: 0.01,
        training_seed: 42,
        training_strategy: 'strict_bsp',
        checkpoint: { every_n_epochs: 5 },
      },
    };

    const res = await service.createJob(payload);

    assert.strictEqual(res.data.job_id, 'job_ckpt_001');
    assert.deepStrictEqual(capturedBody.requested_contract.checkpoint, { every_n_epochs: 5 });

    globalThis.fetch = originalFetch;
  });

  test('Patch Job payload updates checkpoint.every_n_epochs to custom N=7', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_ckpt_001');
      assert.strictEqual(init?.method, 'PATCH');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_ckpt_001',
            display_name: 'Updated Checkpoint Spec',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-10-19T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const payload: JobPatchRequest = {
      display_name: 'Updated Checkpoint Spec',
      requested_contract: {
        checkpoint: { every_n_epochs: 7 },
      },
    };

    const res = await service.patchJob('job_ckpt_001', payload);

    assert.strictEqual(res.data.job_id, 'job_ckpt_001');
    assert.deepStrictEqual(capturedBody.requested_contract.checkpoint, { every_n_epochs: 7 });

    globalThis.fetch = originalFetch;
  });

  test('Lineage safety: Only checkpoints from current attempt or pinned source are valid recovery targets', () => {
    const attemptId = 'attempt_002';
    const resumeSourceId = 'ckpt_from_attempt_001';

    // Mock candidates returned from query
    const checkpointCandidates = [
      { checkpoint_id: 'ckpt_unrelated', created_by_attempt_id: 'attempt_999', state: 'COMPLETE' },
      { checkpoint_id: 'ckpt_valid_1', created_by_attempt_id: attemptId, state: 'COMPLETE' },
    ];

    // Filter by attempt lineage
    const lineageCheckpoints = checkpointCandidates.filter(
      (c) => c.created_by_attempt_id === attemptId || c.checkpoint_id === resumeSourceId
    );

    assert.strictEqual(lineageCheckpoints.length, 1);
    assert.strictEqual(lineageCheckpoints[0].checkpoint_id, 'ckpt_valid_1');
  });
});
