import { test, describe } from 'node:test';
import assert from 'node:assert';
import { ApiClient } from '../client';
import { JobsService } from '../jobs';
import { JobDetailData, JobState } from '../../types/api';

describe('Phase 7C.1 — Draft Job Editing & Draft Launch Service Tests', () => {
  const originalFetch = globalThis.fetch;

  test('PATCH /api/v1/jobs/{job_id} successfully updates DRAFT job parameters and remains DRAFT', async () => {
    let capturedMethod = '';
    let capturedUrl = '';
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || '';
      capturedBody = init?.body ? JSON.parse(String(init.body)) : null;

      const responseData: JobDetailData = {
        job_id: 'job_draft_123',
        display_name: 'Updated ResNet18 Training',
        description: 'Updated description for CIFAR-10',
        state: 'DRAFT',
        requested_contract: {
          dataset_build_id: 'dsb_cifar10_002',
          model_id: 'resnet18_groupnorm',
          epochs: 35,
          learning_rate: 0.005,
          training_seed: 2026,
          training_strategy: 'strict_bsp',
        },
        resolved_contract: null,
        contract_hash: null,
        created_at: '2026-09-15T12:00:00Z',
        frozen_at: null,
        archived_at: null,
      };

      return new Response(
        JSON.stringify({ data: responseData, meta: { request_id: 'req_patch_001' } }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const res = await service.patchJob('job_draft_123', {
      display_name: 'Updated ResNet18 Training',
      description: 'Updated description for CIFAR-10',
      requested_contract: {
        dataset_build_id: 'dsb_cifar10_002',
        model_id: 'resnet18_groupnorm',
        epochs: 35,
        learning_rate: 0.005,
        training_seed: 2026,
        training_strategy: 'strict_bsp',
      },
    });

    assert.strictEqual(capturedMethod, 'PATCH');
    assert.strictEqual(capturedUrl, 'http://localhost:8000/api/v1/jobs/job_draft_123');
    assert.strictEqual(capturedBody.display_name, 'Updated ResNet18 Training');
    assert.strictEqual(capturedBody.requested_contract.epochs, 35);
    assert.strictEqual(capturedBody.requested_contract.learning_rate, 0.005);

    assert.strictEqual(res.data.job_id, 'job_draft_123');
    assert.strictEqual(res.data.state, 'DRAFT');
    assert.strictEqual(res.data.frozen_at, null);

    globalThis.fetch = originalFetch;
  });

  test('POST /api/v1/jobs/{job_id}/start on DRAFT job sends Idempotency-Key and receives 202 Accepted', async () => {
    let capturedMethod = '';
    let capturedUrl = '';
    let capturedIdempotencyKey = '';

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || '';
      const headers = (init?.headers as Record<string, string>) || {};
      capturedIdempotencyKey = headers['Idempotency-Key'] || headers['idempotency-key'] || '';

      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_start_001',
            command_type: 'START_ATTEMPT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_demo_001',
            job_id: 'job_draft_123',
            attempt_id: 'att_demo_001',
            execution_mode: 'FRESH',
          },
          meta: { request_id: 'req_start_001' },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const res = await service.startJob('job_draft_123', { note: 'Launch from DRAFT' });

    assert.strictEqual(capturedMethod, 'POST');
    assert.strictEqual(capturedUrl, 'http://localhost:8000/api/v1/jobs/job_draft_123/start');
    assert.ok(capturedIdempotencyKey.length > 0, 'Idempotency-Key header must be present');
    assert.strictEqual(res.data.job_id, 'job_draft_123');
    assert.strictEqual(res.data.command_type, 'START_ATTEMPT');
    assert.strictEqual(res.data.attempt_id, 'att_demo_001');

    globalThis.fetch = originalFetch;
  });

  test('PATCH /api/v1/jobs/{job_id} on frozen READY job throws 409 JOB_FROZEN conflict', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          error: {
            code: 'JOB_FROZEN',
            message: 'Job contract đã được freeze',
            details: { field: 'requested_contract.learning_rate' },
            request_id: 'req_err_001',
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    await assert.rejects(
      async () => {
        await service.patchJob('job_ready_456', {
          requested_contract: { learning_rate: 0.001 },
        });
      },
      (err: any) => {
        assert.strictEqual(err.status, 409);
        assert.strictEqual(err.code, 'JOB_FROZEN');
        return true;
      }
    );

    globalThis.fetch = originalFetch;
  });

  test('Action eligibility rules per JobState', () => {
    const getActions = (state: JobState, isRunning = false) => ({
      canEdit: state === 'DRAFT',
      canRun: (state === 'DRAFT' || state === 'READY') && !isRunning,
      canClone: true,
      canArchive: state !== 'ARCHIVED',
    });

    const draftActions = getActions('DRAFT');
    assert.strictEqual(draftActions.canEdit, true, 'DRAFT jobs can be edited');
    assert.strictEqual(draftActions.canRun, true, 'DRAFT jobs can be run');
    assert.strictEqual(draftActions.canClone, true);
    assert.strictEqual(draftActions.canArchive, true);

    const readyActions = getActions('READY');
    assert.strictEqual(readyActions.canEdit, false, 'READY jobs cannot edit hyperparameters');
    assert.strictEqual(readyActions.canRun, true, 'READY jobs can be run');
    assert.strictEqual(readyActions.canClone, true);
    assert.strictEqual(readyActions.canArchive, true);

    const archivedActions = getActions('ARCHIVED');
    assert.strictEqual(archivedActions.canEdit, false, 'ARCHIVED jobs cannot be edited');
    assert.strictEqual(archivedActions.canRun, false, 'ARCHIVED jobs cannot be run');
    assert.strictEqual(archivedActions.canClone, true, 'ARCHIVED jobs can be cloned');
    assert.strictEqual(archivedActions.canArchive, false);
  });
});
