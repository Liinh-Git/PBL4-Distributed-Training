import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { ApiClient } from '../client';
import { JobsService } from '../jobs';
import type { JobCreateRequest, JobPatchRequest } from '../../types/api';

describe('WebUI Workload Policy Contract & Integration Tests (Bug #3)', () => {
  const originalFetch = globalThis.fetch;

  test('Create Job payload includes workload_policy="equal" and strict_bsp without work_units_per_step input', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs');
      assert.strictEqual(init?.method, 'POST');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_equal_001',
            display_name: 'ResNet18 on CIFAR-10 Equal',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-09-29T12:00:00Z',
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const payload: JobCreateRequest = {
      display_name: 'ResNet18 on CIFAR-10 Equal',
      requested_contract: {
        dataset_build_id: 'dsb_001',
        model_id: 'resnet18_groupnorm',
        epochs: 20,
        learning_rate: 0.01,
        training_seed: 42,
        training_strategy: 'strict_bsp',
        workload_policy: 'equal',
      },
    };

    const res = await service.createJob(payload);

    assert.strictEqual(res.data.job_id, 'job_equal_001');
    assert.strictEqual(capturedBody.requested_contract.training_strategy, 'strict_bsp');
    assert.strictEqual(capturedBody.requested_contract.workload_policy, 'equal');
    assert.strictEqual(capturedBody.requested_contract.work_units_per_step, undefined);

    globalThis.fetch = originalFetch;
  });

  test('Create Job payload includes explicit DBS work units under strict_bsp', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs');
      assert.strictEqual(init?.method, 'POST');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_dbs_002',
            display_name: 'ResNet18 on CIFAR-10 DBS',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-09-29T12:00:00Z',
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const payload: JobCreateRequest = {
      display_name: 'ResNet18 on CIFAR-10 DBS',
      requested_contract: {
        dataset_build_id: 'dsb_002',
        model_id: 'resnet18_groupnorm',
        epochs: 20,
        learning_rate: 0.01,
        training_seed: 42,
        training_strategy: 'strict_bsp',
        workload_policy: 'dbs',
        work_units_per_step: 6,
      },
    };

    const res = await service.createJob(payload);

    assert.strictEqual(res.data.job_id, 'job_dbs_002');
    assert.strictEqual(capturedBody.requested_contract.training_strategy, 'strict_bsp');
    assert.strictEqual(capturedBody.requested_contract.workload_policy, 'dbs');
    assert.strictEqual(capturedBody.requested_contract.work_units_per_step, 6);

    globalThis.fetch = originalFetch;
  });

  test('Patch Job payload supports workload_policy update', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_dbs_002');
      assert.strictEqual(init?.method, 'PATCH');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_dbs_002',
            display_name: 'ResNet18 on CIFAR-10 DBS',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-09-29T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    const patchPayload: JobPatchRequest = {
      requested_contract: {
        training_strategy: 'strict_bsp',
        workload_policy: 'equal',
      },
    };

    const res = await service.patchJob('job_dbs_002', patchPayload);
    assert.strictEqual(capturedBody.requested_contract.workload_policy, 'equal');

    globalThis.fetch = originalFetch;
  });

  test('Bug #4: Patching a different field preserves existing workload_policy="dbs"', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_dbs_existing');
      assert.strictEqual(init?.method, 'PATCH');
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_dbs_existing',
            display_name: 'DBS Job Updated Epochs',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-09-29T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    // User only changes epochs from 20 to 35 on a DBS job
    const patchPayload: JobPatchRequest = {
      requested_contract: {
        epochs: 35,
        training_strategy: 'strict_bsp',
        workload_policy: 'dbs', // Policy preserved, not dropped or reset to equal
      },
    };

    await service.patchJob('job_dbs_existing', patchPayload);
    assert.strictEqual(capturedBody.requested_contract.epochs, 35);
    assert.strictEqual(capturedBody.requested_contract.workload_policy, 'dbs');
    assert.strictEqual(capturedBody.requested_contract.work_units_per_step, undefined);

    globalThis.fetch = originalFetch;
  });

  test('Bug #4: Deterministic carry-forward of work_units_per_step when policy unchanged', async () => {
    let capturedBody: any = null;

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedBody = JSON.parse(String(init?.body));
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_carry_forward',
            state: 'DRAFT',
            requested_contract: capturedBody.requested_contract,
            created_at: '2026-09-29T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);

    // Job had work_units_per_step=12 with DBS policy; user only edited learning_rate
    const patchPayload: JobPatchRequest = {
      requested_contract: {
        learning_rate: 0.005,
        training_strategy: 'strict_bsp',
        workload_policy: 'dbs',
        work_units_per_step: 12,
      },
    };

    await service.patchJob('job_carry_forward', patchPayload);
    assert.strictEqual(capturedBody.requested_contract.workload_policy, 'dbs');
    assert.strictEqual(capturedBody.requested_contract.work_units_per_step, 12);

    globalThis.fetch = originalFetch;
  });

  test('EditJobModal exposes required DBS work units input', () => {
    const modalPath = path.resolve(process.cwd(), 'src/components/common/EditJobModal.tsx');
    const content = fs.readFileSync(modalPath, 'utf-8');

    // 1. Must define workloadPolicy state
    assert.match(content, /const \[workloadPolicy,\s*setWorkloadPolicy\]\s*=\s*useState<WorkloadPolicy>\('equal'\)/);

    // 2. Must load workload_policy from requested_contract
    assert.match(content, /fullJob\.requested_contract\.workload_policy/);

    // 3. Must expose UI options for Equal and DBS Adaptive
    assert.match(content, /Equal/);
    assert.match(content, /DBS Adaptive/);
    assert.match(content, /changeWorkloadPolicy\('equal'\)/);
    assert.match(content, /changeWorkloadPolicy\('dbs'\)/);
    assert.match(content, /if \(policy !== workloadPolicy\) setExistingWups\(undefined\)/);

    // 4. Must send workload_policy in patch payload
    assert.match(content, /workload_policy:\s*workloadPolicy/);

    assert.match(content, /name="work_units_per_step"/);
    assert.match(content, /workloadPolicy === 'dbs' && \(!Number\.isInteger\(existingWups\)/);
  });

  test('NewTrainingFlowPage exposes required DBS work units input', () => {
    const pagePath = path.resolve(process.cwd(), 'src/pages/NewTrainingFlowPage.tsx');
    const content = fs.readFileSync(pagePath, 'utf-8');

    // 1. Must define workloadPolicy state with default 'equal'
    assert.match(content, /const \[workloadPolicy,\s*setWorkloadPolicy\]\s*=\s*useState<'equal'\s*\|\s*'dbs'>\('equal'\)/);

    // 2. Must expose UI options for Equal and DBS Adaptive
    assert.match(content, /Equal/);
    assert.match(content, /DBS Adaptive/);
    assert.match(content, /changeWorkloadPolicy\('equal'\)/);
    assert.match(content, /changeWorkloadPolicy\('dbs'\)/);
    assert.match(content, /if \(policy !== workloadPolicy\) setExistingWups\(undefined\)/);

    // 3. Must lock training strategy to strict_bsp
    assert.match(content, /training_strategy:\s*'strict_bsp'/);
    assert.doesNotMatch(content, /training_strategy:\s*['"]local_sgd['"]/);
    assert.doesNotMatch(content, /training_strategy:\s*['"]async['"]/);

    // 4. Must send workload_policy in requested_contract
    assert.match(content, /workload_policy:\s*workloadPolicy/);

    assert.match(content, /name="work_units_per_step"/);
    assert.match(content, /workloadPolicy === 'dbs' && \(!Number\.isInteger\(existingWups\)/);
  });
});
