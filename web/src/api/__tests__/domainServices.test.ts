/**
 * Unit tests for Domain API Services (Phase 3)
 *
 * Runs with Node.js built-in test runner: npx tsx --test src/api/__tests__/domainServices.test.ts
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { ApiClient } from '../client';
import { SystemService } from '../system';
import { DatasetsService } from '../datasets';
import { DatasetBuildsService } from '../datasetBuilds';
import { CheckpointsService } from '../checkpoints';
import { EventsService } from '../events';
import { CommandsService } from '../commands';
import { JobsService } from '../jobs';
import { AttemptsService } from '../attempts';
import { WorkersService } from '../workers';
import { StepsService } from '../steps';
import { MetricsService } from '../metrics';



describe('System and Capabilities Service', () => {
  const originalFetch = globalThis.fetch;

  test('getHealth queries /api/v1/health', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/health');
      return new Response(
        JSON.stringify({
          data: {
            backend: 'ok',
            postgres: 'ok',
            runtime_mcp: 'ok',
            dataset_manager: 'ok',
            timestamp: '2026-09-11T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new SystemService(client);
    const res = await service.getHealth();

    assert.strictEqual(res.data.backend, 'ok');
    assert.strictEqual(res.data.postgres, 'ok');

    globalThis.fetch = originalFetch;
  });

  test('getCapabilities queries /api/v1/system/capabilities', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/system/capabilities');
      return new Response(
        JSON.stringify({
          data: {
            api_version: 'v1',
            dtp_versions: [1],
            mcp_versions: [1],
            runtime_connected: true,
            runtime_instance_id: 'rt_001',
            supported_training_strategies: ['strict_bsp'],
            feature_flags: { attempt_websocket_stream: true, manual_checkpoint_request: true },
            supported_models: [
              { model_id: 'resnet18_groupnorm', display_name: 'ResNet-18', task_type: 'image_classification' },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new SystemService(client);
    const res = await service.getCapabilities();

    assert.strictEqual(res.data.api_version, 'v1');
    assert.strictEqual(res.data.supported_models?.[0].model_id, 'resnet18_groupnorm');

    globalThis.fetch = originalFetch;
  });
});

describe('Datasets Service', () => {
  const originalFetch = globalThis.fetch;

  test('listDatasets sends query params and returns paginated response', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/datasets?task_type=image_classification&q=cifar&limit=20'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              dataset_id: 'cifar10',
              name: 'CIFAR-10',
              task_type: 'image_classification',
              source_type: 'builtin',
              source_reference: 'cifar10',
              created_at: '2026-09-07T02:00:00Z',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new DatasetsService(client);
    const res = await service.listDatasets({
      task_type: 'image_classification',
      q: 'cifar',
      limit: 20,
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].dataset_id, 'cifar10');

    globalThis.fetch = originalFetch;
  });

  test('getDataset returns dataset detail with build counts', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/datasets/cifar10');
      return new Response(
        JSON.stringify({
          data: {
            dataset_id: 'cifar10',
            name: 'CIFAR-10',
            task_type: 'image_classification',
            source_type: 'builtin',
            source_reference: 'cifar10',
            created_at: '2026-09-07T02:00:00Z',
            build_counts: { CREATED: 0, QUEUED: 0, IMPORTING: 0, VALIDATING: 0, PREPROCESSING: 0, MATERIALIZING: 0, VERIFYING: 0, REGISTERING: 0, READY: 3, FAILED: 1, DEPRECATED: 0, DELETING: 0, DELETED: 0 },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new DatasetsService(client);
    const res = await service.getDataset('cifar10');

    assert.strictEqual(res.data.dataset_id, 'cifar10');
    assert.strictEqual(res.data.build_counts.READY, 3);

    globalThis.fetch = originalFetch;
  });

  test('createDataset sends POST request with Idempotency-Key', async () => {
    let capturedMethod = '';
    let capturedIdempotencyKey = '';

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      capturedMethod = init?.method || '';
      capturedIdempotencyKey = (init?.headers as Record<string, string>)?.['Idempotency-Key'] || '';

      return new Response(
        JSON.stringify({
          data: {
            dataset_id: 'cifar10',
            name: 'CIFAR-10',
            task_type: 'image_classification',
            source_type: 'builtin',
            source_reference: 'cifar10',
            created_at: '2026-09-07T02:00:00Z',
            build_counts: { CREATED: 0, QUEUED: 0, IMPORTING: 0, VALIDATING: 0, PREPROCESSING: 0, MATERIALIZING: 0, VERIFYING: 0, REGISTERING: 0, READY: 0, FAILED: 0, DEPRECATED: 0, DELETING: 0, DELETED: 0 },
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new DatasetsService(client);
    const res = await service.createDataset({
      name: 'CIFAR-10',
      task_type: 'image_classification',
      source_type: 'builtin',
      source_reference: 'cifar10',
    });

    assert.strictEqual(capturedMethod, 'POST');
    assert.ok(capturedIdempotencyKey.length > 0);
    assert.strictEqual(res.data.dataset_id, 'cifar10');

    globalThis.fetch = originalFetch;
  });
});

describe('Dataset Builds Service', () => {
  const originalFetch = globalThis.fetch;

  test('createBuild sends POST and returns 202 Accepted Command', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/dataset-builds');
      assert.strictEqual(init?.method, 'POST');
      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_001',
            command_type: 'CREATE_DATASET_BUILD',
            command_state: 'ACCEPTED',
            target_type: 'DATASET_BUILD',
            target_id: 'dsb_001',
            dataset_build_id: 'dsb_001',
            dataset_build_state: 'CREATED',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new DatasetBuildsService(client);
    const res = await service.createBuild({
      dataset_id: 'cifar10',
      profile: 'CNN_IMAGE_CLASSIFICATION_V1',
      batch_size: 32,
      partition_seed: 2026,
      preprocessing: {
        input_shape: [3, 32, 32],
        normalization: { mean: [0.4914, 0.4822, 0.4465], std: [0.247, 0.2435, 0.2616] },
      },
    });

    assert.strictEqual(res.data.command_id, 'cmd_001');
    assert.strictEqual(res.data.command_state, 'ACCEPTED');
    assert.strictEqual(res.data.dataset_build_id, 'dsb_001');

    globalThis.fetch = originalFetch;
  });

  test('deprecateBuild and deleteBuild send POST with correct paths', async () => {
    let capturedUrls: string[] = [];

    globalThis.fetch = async (input: RequestInfo | URL) => {
      capturedUrls.push(String(input));
      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_002',
            command_type: 'DELETE_DATASET_BUILD',
            command_state: 'ACCEPTED',
            target_type: 'DATASET_BUILD',
            target_id: 'dsb_001',
            dataset_build_id: 'dsb_001',
            dataset_build_state: 'DELETING',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new DatasetBuildsService(client);

    await service.deprecateBuild('dsb_001', { reason: 'No longer needed' });
    await service.deleteBuild('dsb_001', { reason: 'Purge' });

    assert.strictEqual(capturedUrls[0], 'http://localhost:8000/api/v1/dataset-builds/dsb_001/deprecate');
    assert.strictEqual(capturedUrls[1], 'http://localhost:8000/api/v1/dataset-builds/dsb_001/delete');

    globalThis.fetch = originalFetch;
  });
});

describe('Checkpoints Service', () => {
  const originalFetch = globalThis.fetch;

  test('listCheckpoints queries /api/v1/checkpoints with filter params', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/checkpoints?job_id=job_001&state=COMPLETE&limit=10'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              checkpoint_id: 'ckpt_001',
              job_id: 'job_001',
              created_by_attempt_id: 'att_001',
              state: 'COMPLETE',
              model_version: 42,
              source_step_id: 17,
              created_at: '2026-09-07T03:24:17.800Z',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new CheckpointsService(client);
    const res = await service.listCheckpoints({
      job_id: 'job_001',
      state: 'COMPLETE',
      limit: 10,
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].checkpoint_id, 'ckpt_001');

    globalThis.fetch = originalFetch;
  });

  test('getCheckpoint returns full checkpoint details and recovery cursor', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/checkpoints/ckpt_001');
      return new Response(
        JSON.stringify({
          data: {
            checkpoint_id: 'ckpt_001',
            state: 'COMPLETE',
            job_id: 'job_001',
            created_by_attempt_id: 'att_001',
            contract_hash: 'hash_abc',
            dataset_build_id: 'dsb_001',
            source_operation_id: 17,
            source_step_id: 17,
            model_version: 42,
            recovery_cursor: { epoch: 2, next_batch_ordinal: 6 },
            integrity: { model_sha256: 'sha_model_123', artifact_size_bytes: 46821376 },
            created_at: '2026-09-07T03:24:17.800Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new CheckpointsService(client);
    const res = await service.getCheckpoint('ckpt_001');

    assert.strictEqual(res.data.checkpoint_id, 'ckpt_001');
    assert.strictEqual(res.data.recovery_cursor?.epoch, 2);

    globalThis.fetch = originalFetch;
  });
});

describe('Audit Events & Commands Services', () => {
  const originalFetch = globalThis.fetch;

  test('listEvents queries /api/v1/events with audit filters', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/events?scope_type=ATTEMPT&scope_id=att_001&severity=INFO&limit=50'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              event_id: '124',
              scope: { type: 'ATTEMPT', id: 'att_001' },
              event_type: 'model.updated',
              severity: 'INFO',
              occurred_at: '2026-09-07T03:24:18.527Z',
              summary: 'Canonical model advanced from version 41 to 42',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new EventsService(client);
    const res = await service.listEvents({
      scope_type: 'ATTEMPT',
      scope_id: 'att_001',
      severity: 'INFO',
      limit: 50,
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].event_id, '124');

    globalThis.fetch = originalFetch;
  });

  test('getCommand queries /api/v1/commands/{id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/commands/cmd_001');
      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_001',
            command_type: 'REQUEST_CHECKPOINT',
            state: 'SUCCEEDED',
            target_type: 'ATTEMPT',
            target_id: 'att_001',
            request: { reason: 'manual' },
            result: { code: 'NO_OP', message: 'Recovery point already durable' },
            requested_at: '2026-09-07T03:20:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new CommandsService(client);
    const res = await service.getCommand('cmd_001');

    assert.strictEqual(res.data.command_id, 'cmd_001');
    assert.strictEqual(res.data.state, 'SUCCEEDED');
    assert.strictEqual(res.data.result?.code, 'NO_OP');

    globalThis.fetch = originalFetch;
  });
});

describe('Jobs Service (13.0 - 22.0)', () => {
  const originalFetch = globalThis.fetch;

  test('13.0 createJob sends POST /api/v1/jobs', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs');
      assert.strictEqual(init?.method, 'POST');
      const body = JSON.parse(String(init?.body));
      assert.strictEqual(body.display_name, 'Test Job');
      assert.strictEqual(body.requested_contract.epochs, 5);
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_001',
            display_name: 'Test Job',
            description: '',
            state: 'DRAFT',
            requested_contract: body.requested_contract,
            created_at: '2026-09-11T12:00:00Z',
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.createJob({
      display_name: 'Test Job',
      requested_contract: {
        dataset_build_id: 'dsb_001',
        model_id: 'resnet18_groupnorm',
        epochs: 5,
        learning_rate: 0.01,
        training_seed: 42,
        training_strategy: 'strict_bsp',
      },
    });

    assert.strictEqual(res.data.job_id, 'job_001');
    assert.strictEqual(res.data.state, 'DRAFT');

    globalThis.fetch = originalFetch;
  });

  test('14.0 listJobs sends GET /api/v1/jobs with params', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/jobs?state=READY&dataset_build_id=dsb_001&q=test&limit=20'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              job_id: 'job_001',
              display_name: 'Test Job',
              state: 'READY',
              attempt_count: 1,
              created_at: '2026-09-11T12:00:00Z',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.listJobs({
      state: 'READY',
      dataset_build_id: 'dsb_001',
      q: 'test',
      limit: 20,
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].job_id, 'job_001');

    globalThis.fetch = originalFetch;
  });

  test('15.0 getJob sends GET /api/v1/jobs/{job_id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001');
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_001',
            display_name: 'Test Job',
            description: 'My Description',
            state: 'DRAFT',
            requested_contract: {
              dataset_build_id: 'dsb_001',
              model_id: 'resnet18_groupnorm',
              epochs: 5,
              learning_rate: 0.01,
              training_seed: 42,
              training_strategy: 'strict_bsp',
            },
            created_at: '2026-09-11T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.getJob('job_001');

    assert.strictEqual(res.data.job_id, 'job_001');
    assert.strictEqual(res.data.display_name, 'Test Job');

    globalThis.fetch = originalFetch;
  });

  test('16.0 patchJob sends PATCH /api/v1/jobs/{job_id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001');
      assert.strictEqual(init?.method, 'PATCH');
      const body = JSON.parse(String(init?.body));
      assert.strictEqual(body.display_name, 'Updated Job');
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_001',
            display_name: 'Updated Job',
            description: '',
            state: 'DRAFT',
            requested_contract: {
              dataset_build_id: 'dsb_001',
              model_id: 'resnet18_groupnorm',
              epochs: 10,
              learning_rate: 0.01,
              training_seed: 42,
              training_strategy: 'strict_bsp',
            },
            created_at: '2026-09-11T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.patchJob('job_001', {
      display_name: 'Updated Job',
      requested_contract: { epochs: 10 },
    });

    assert.strictEqual(res.data.display_name, 'Updated Job');
    assert.strictEqual(res.data.requested_contract.epochs, 10);

    globalThis.fetch = originalFetch;
  });

  test('17.0 validateJob sends POST /api/v1/jobs/{job_id}/validate', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/validate');
      assert.strictEqual(init?.method, 'POST');
      return new Response(
        JSON.stringify({
          data: {
            requested_contract: {
              dataset_build_id: 'dsb_001',
              model_id: 'resnet18_groupnorm',
              epochs: 5,
              learning_rate: 0.01,
              training_seed: 42,
              training_strategy: 'strict_bsp',
            },
            resolved_preview: {
              dataset: { dataset_build_id: 'dsb_001', dataset_manifest_hash: 'hash123', total_train_samples: 50000, batch_size: 64, steps_per_epoch: 782 },
              model: { model_id: 'resnet18_groupnorm', architecture_name: 'ResNet-18', parameter_count: 11173962 },
              training: { epochs: 5, learning_rate: 0.01, training_seed: 42 },
              synchronization: { training_strategy: 'strict_bsp', expected_workers: 3 },
              update_policy: { type: 'sgd' },
              checkpoint_policy: { type: 'epoch_end', schema_version: 1 },
              protocols: { dtp_version: 1, mcp_version: 1 },
            },
            warnings: [],
            errors: [],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.validateJob('job_001');

    assert.strictEqual(res.data.errors.length, 0);
    assert.strictEqual(res.data.resolved_preview?.synchronization.expected_workers, 3);

    globalThis.fetch = originalFetch;
  });

  test('18.0 cloneJob sends POST /api/v1/jobs/{job_id}/clone', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/clone');
      assert.strictEqual(init?.method, 'POST');
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_002',
            state: 'DRAFT',
            cloned_from_job_id: 'job_001',
            display_name: 'Test Job (Clone)',
            description: '',
            requested_contract: {
              dataset_build_id: 'dsb_001',
              model_id: 'resnet18_groupnorm',
              epochs: 5,
              learning_rate: 0.01,
              training_seed: 42,
              training_strategy: 'strict_bsp',
            },
            resolved_contract: null,
            contract_hash: null,
          },
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.cloneJob('job_001');

    assert.strictEqual(res.data.job_id, 'job_002');
    assert.strictEqual(res.data.cloned_from_job_id, 'job_001');
    assert.strictEqual(res.data.state, 'DRAFT');

    globalThis.fetch = originalFetch;
  });

  test('19.0 archiveJob sends POST /api/v1/jobs/{job_id}/archive', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/archive');
      assert.strictEqual(init?.method, 'POST');
      return new Response(
        JSON.stringify({
          data: {
            job_id: 'job_001',
            state: 'ARCHIVED',
            archived_at: '2026-09-11T12:00:00Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.archiveJob('job_001');

    assert.strictEqual(res.data.state, 'ARCHIVED');

    globalThis.fetch = originalFetch;
  });

  test('20.0 startJob sends POST /api/v1/jobs/{job_id}/start with Idempotency-Key', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/start');
      assert.strictEqual(init?.method, 'POST');
      assert.ok(init?.headers);
      const headers = new Headers(init.headers);
      assert.ok(headers.has('Idempotency-Key'));

      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_start_001',
            command_type: 'START_ATTEMPT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_001',
            job_id: 'job_001',
            attempt_id: 'att_001',
            execution_mode: 'FRESH',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.startJob('job_001');

    assert.strictEqual(res.data.command_type, 'START_ATTEMPT');
    assert.strictEqual(res.data.attempt_id, 'att_001');
    assert.strictEqual(res.data.execution_mode, 'FRESH');

    globalThis.fetch = originalFetch;
  });

  test('21.0 retryJob sends POST /api/v1/jobs/{job_id}/retry', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/retry');
      assert.strictEqual(init?.method, 'POST');
      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_retry_001',
            command_type: 'START_ATTEMPT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_retry_001',
            job_id: 'job_001',
            attempt_id: 'att_retry_001',
            execution_mode: 'RETRY_FROM_START',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.retryJob('job_001', { note: 'Retry after failure' });

    assert.strictEqual(res.data.attempt_id, 'att_retry_001');
    assert.strictEqual(res.data.execution_mode, 'RETRY_FROM_START');

    globalThis.fetch = originalFetch;
  });

  test('22.0 resumeJob sends POST /api/v1/jobs/{job_id}/resume with checkpoint_id', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/jobs/job_001/resume');
      assert.strictEqual(init?.method, 'POST');
      const body = JSON.parse(String(init?.body));
      assert.strictEqual(body.checkpoint_id, 'ckpt_001');

      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_resume_001',
            command_type: 'START_ATTEMPT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_resume_001',
            job_id: 'job_001',
            attempt_id: 'att_resume_001',
            execution_mode: 'RESUME',
            resume_from_checkpoint_id: 'ckpt_001',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new JobsService(client);
    const res = await service.resumeJob('job_001', { checkpoint_id: 'ckpt_001' });

    assert.strictEqual(res.data.attempt_id, 'att_resume_001');
    assert.strictEqual(res.data.execution_mode, 'RESUME');
    assert.strictEqual(res.data.resume_from_checkpoint_id, 'ckpt_001');

    globalThis.fetch = originalFetch;
  });
});

describe('Attempts Service (23.0 - 24.0)', () => {
  const originalFetch = globalThis.fetch;

  test('23.0 listAttempts queries /api/v1/attempts with query params', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts?job_id=job_001&state=FAILED&execution_mode=FRESH&limit=50'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              attempt_id: 'att_001',
              job_id: 'job_001',
              state: 'FAILED',
              execution_mode: 'FRESH',
              training_strategy: 'strict_bsp',
              created_at: '2026-09-07T02:20:00.000Z',
              failure_code: 'WORKER_DISCONNECTED',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.listAttempts({
      job_id: 'job_001',
      state: 'FAILED',
      execution_mode: 'FRESH',
      limit: 50,
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].attempt_id, 'att_001');
    assert.strictEqual(res.data[0].state, 'FAILED');

    globalThis.fetch = originalFetch;
  });

  test('24.0 getAttempt queries /api/v1/attempts/{attempt_id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/attempts/att_001');
      return new Response(
        JSON.stringify({
          data: {
            attempt_id: 'att_001',
            job_id: 'job_001',
            contract_hash: 'hash_abc',
            state: 'RUNNING',
            execution_mode: 'FRESH',
            training_strategy: 'strict_bsp',
            expected_workers: 3,
            membership: { active_workers: 3, expected_workers: 3 },
            epoch: 2,
            progress_cursor: { epoch: 2, next_batch_ordinal: 6 },
            model_version: 42,
            checkpoint: { state: 'COMPLETE', latest_checkpoint_id: 'ckpt_001' },
            runtime: { stale: false, observed_at: '2026-09-07T03:24:18.527Z', runtime_event_seq: 123 },
            strategy_state: {
              type: 'strict_bsp',
              current_step_id: 18,
              state: 'COLLECTING_GRADIENTS',
              accepted_contribution_count: 1,
              expected_contribution_count: 3,
            },
            failure: null,
            links: {
              job: '/api/v1/jobs/job_001',
              workers: '/api/v1/attempts/att_001/workers',
              steps: '/api/v1/attempts/att_001/steps',
              events: '/api/v1/attempts/att_001/events',
            },
            created_at: '2026-09-07T02:20:00.000Z',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.getAttempt('att_001');

    assert.strictEqual(res.data.attempt_id, 'att_001');
    assert.strictEqual(res.data.state, 'RUNNING');
    assert.strictEqual(res.data.strategy_state?.accepted_contribution_count, 1);

    globalThis.fetch = originalFetch;
  });

  test('25.0 abortAttempt sends POST /api/v1/attempts/{id}/abort with Idempotency-Key', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/attempts/att_001/abort');
      assert.strictEqual(init?.method, 'POST');
      const body = JSON.parse(String(init?.body));
      assert.strictEqual(body.reason, 'Operator stopped run');
      assert.ok(new Headers(init?.headers).has('Idempotency-Key'));

      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_abort_001',
            command_type: 'ABORT_ATTEMPT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_001',
            attempt_id: 'att_001',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.abortAttempt('att_001', { reason: 'Operator stopped run' });

    assert.strictEqual(res.data.command_type, 'ABORT_ATTEMPT');
    assert.strictEqual(res.data.command_state, 'ACCEPTED');

    globalThis.fetch = originalFetch;
  });

  test('26.0 getJoinSpec queries /api/v1/attempts/{id}/join-spec', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/attempts/att_001/join-spec');
      return new Response(
        JSON.stringify({
          data: {
            ps_host: '192.168.1.10',
            ps_port: 5000,
            job_id: 'job_001',
            attempt_id: 'att_001',
            contract_hash: 'hash_abc',
            protocol: { dtp_version: 1 },
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.getJoinSpec('att_001');

    assert.strictEqual(res.data.ps_host, '192.168.1.10');
    assert.strictEqual(res.data.ps_port, 5000);

    globalThis.fetch = originalFetch;
  });

  test('27.0 getSnapshot queries /api/v1/attempts/{id}/snapshot', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/attempts/att_001/snapshot');
      return new Response(
        JSON.stringify({
          data: {
            attempt_id: 'att_001',
            state: 'RUNNING',
            epoch: 2,
            model_version: 42,
            workers: [{ worker_id: 0, session_id: '10000', state: 'READY' }],
            strategy_state: { type: 'strict_bsp', accepted_contribution_count: 3 },
            stale: false,
            runtime_event_seq: 123,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.getSnapshot('att_001');

    assert.strictEqual(res.data.epoch, 2);
    assert.strictEqual(res.data.runtime_event_seq, 123);

    globalThis.fetch = originalFetch;
  });

  test('34.0 requestCheckpoint sends POST /api/v1/attempts/{id}/checkpoint-requests', async () => {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/checkpoint-requests'
      );
      assert.strictEqual(init?.method, 'POST');
      const body = JSON.parse(String(init?.body));
      assert.strictEqual(body.reason, 'manual');
      assert.ok(new Headers(init?.headers).has('Idempotency-Key'));

      return new Response(
        JSON.stringify({
          data: {
            command_id: 'cmd_ckpt_001',
            command_type: 'REQUEST_CHECKPOINT',
            command_state: 'ACCEPTED',
            target_type: 'ATTEMPT',
            target_id: 'att_001',
            attempt_id: 'att_001',
          },
        }),
        { status: 202, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.requestCheckpoint('att_001');

    assert.strictEqual(res.data.command_type, 'REQUEST_CHECKPOINT');

    globalThis.fetch = originalFetch;
  });

  test('35.0 getCatchUpEvents queries /api/v1/attempts/{id}/events with after_seq', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/events?after_seq=123&limit=50'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              attempt_id: 'att_001',
              runtime_event_seq: 124,
              event_type: 'model.updated',
              event_schema_version: 1,
              occurred_at: '2026-09-07T03:24:18.527Z',
              source_component: 'Coordinator',
              severity: 'INFO',
              details: { input_model_version: 41, output_model_version: 42 },
            },
          ],
          meta: { complete: true, gap_detected: false, snapshot_required: false },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new AttemptsService(client);
    const res = await service.getCatchUpEvents('att_001', { after_seq: 123, limit: 50 });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].runtime_event_seq, 124);
    assert.strictEqual(res.meta.gap_detected, false);

    globalThis.fetch = originalFetch;
  });
});

describe('Workers Service (28.0 - 29.0)', () => {
  const originalFetch = globalThis.fetch;

  test('28.0 listWorkers queries /api/v1/attempts/{id}/workers', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(String(input), 'http://localhost:8000/api/v1/attempts/att_001/workers');
      return new Response(
        JSON.stringify({
          data: [
            {
              worker_id: 0,
              session_id: '10000',
              node_label: 'machine-a',
              state: 'READY',
              local_model_version: 42,
              protocol_version: 1,
              connected_at: '2026-09-07T02:20:00.000Z',
            },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new WorkersService(client);
    const res = await service.listWorkers('att_001');

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].worker_id, 0);

    globalThis.fetch = originalFetch;
  });

  test('29.0 getWorker queries /api/v1/attempts/{id}/workers/{worker_id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/workers/1?include_history=true'
      );
      return new Response(
        JSON.stringify({
          data: {
            worker_id: 1,
            active_session: {
              worker_id: 1,
              session_id: '10001',
              node_label: 'machine-b',
              state: 'READY',
              protocol_version: 1,
              connected_at: '2026-09-07T02:20:01.000Z',
            },
            historical_sessions: [],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new WorkersService(client);
    const res = await service.getWorker('att_001', 1, { include_history: true });

    assert.strictEqual(res.data.worker_id, 1);
    assert.strictEqual(res.data.active_session?.session_id, '10001');

    globalThis.fetch = originalFetch;
  });
});

describe('Steps Service (30.0 - 31.0)', () => {
  const originalFetch = globalThis.fetch;

  test('30.0 listSteps queries /api/v1/attempts/{id}/steps with pagination', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/steps?limit=50'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              step_id: 17,
              operation_id: 17,
              state: 'COMMITTED',
              input_model_version: 41,
              output_model_version: 42,
              epoch: 2,
              batch_ordinal: 5,
              total_sample_count: 96,
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new StepsService(client);
    const res = await service.listSteps('att_001');

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].step_id, 17);

    globalThis.fetch = originalFetch;
  });

  test('31.0 getStep queries /api/v1/attempts/{id}/steps/{step_id}', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/steps/17'
      );
      return new Response(
        JSON.stringify({
          data: {
            training_strategy: 'strict_bsp',
            step_id: 17,
            operation_id: 17,
            input_model_version: 41,
            output_model_version: 42,
            state: 'COMMITTED',
            epoch: 2,
            batch_ordinal: 5,
            metrics: { loss: 0.21, accuracy: 89.0 },
            worker_steps: [
              {
                worker_id: 0,
                session_id: '10000',
                compute_ms: 65.4,
                upload_ms: 28.1,
                sample_count: 32,
              },
            ],
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new StepsService(client);
    const res = await service.getStep('att_001', 17);

    assert.strictEqual(res.data.step_id, 17);
    assert.strictEqual(res.data.metrics?.loss, 0.21);
    assert.strictEqual(res.data.worker_steps[0].compute_ms, 65.4);

    globalThis.fetch = originalFetch;
  });
});

describe('Metrics Service (40.0)', () => {
  const originalFetch = globalThis.fetch;

  test('40.0 queryMetrics queries /api/v1/attempts/{id}/metrics with query params', async () => {
    globalThis.fetch = async (input: RequestInfo | URL) => {
      assert.strictEqual(
        String(input),
        'http://localhost:8000/api/v1/attempts/att_001/metrics?name=loss&from_step=0&limit=100'
      );
      return new Response(
        JSON.stringify({
          data: [
            {
              metric_id: '1001',
              attempt_id: 'att_001',
              step_id: 1,
              name: 'loss',
              value: 0.45,
              observed_at: '2026-09-07T03:24:05.120Z',
            },
          ],
          page: { next_cursor: null },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const service = new MetricsService(client);
    const res = await service.queryMetrics('att_001', { name: 'loss', from_step: 0 });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.data[0].name, 'loss');
    assert.strictEqual(res.data[0].value, 0.45);

    globalThis.fetch = originalFetch;
  });
});


