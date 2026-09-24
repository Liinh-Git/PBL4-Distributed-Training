/**
 * Unit tests for Core API Client, Idempotency, and Error Normalization
 *
 * Runs with Node.js built-in test runner: npx tsx --test src/api/__tests__/client.test.ts
 */

import { test, describe, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { ApiClient, buildQueryString } from '../client';
import { AppApiError } from '../errors';
import {
  generateIdempotencyKey,
  isMutationMethod,
  withIdempotencyHeader,
} from '../idempotency';

describe('Idempotency utilities', () => {
  test('generateIdempotencyKey returns a valid UUID v4 format', () => {
    const uuid = generateIdempotencyKey();
    assert.match(
      uuid,
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      `Expected UUID v4 format, got ${uuid}`
    );
  });

  test('isMutationMethod recognizes POST, PATCH, DELETE and rejects GET', () => {
    assert.strictEqual(isMutationMethod('POST'), true);
    assert.strictEqual(isMutationMethod('post'), true);
    assert.strictEqual(isMutationMethod('PATCH'), true);
    assert.strictEqual(isMutationMethod('DELETE'), true);
    assert.strictEqual(isMutationMethod('GET'), false);
    assert.strictEqual(isMutationMethod('HEAD'), false);
    assert.strictEqual(isMutationMethod('OPTIONS'), false);
  });

  test('withIdempotencyHeader injects UUID for POST when omitted', () => {
    const headers = withIdempotencyHeader(undefined, 'POST');
    assert.ok(headers['Idempotency-Key'], 'Should contain Idempotency-Key');
    assert.match(
      headers['Idempotency-Key'],
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    );
  });

  test('withIdempotencyHeader preserves explicit idempotency key', () => {
    const explicitKey = 'custom-test-key-12345';
    const headers = withIdempotencyHeader(undefined, 'POST', explicitKey);
    assert.strictEqual(headers['Idempotency-Key'], explicitKey);
  });

  test('withIdempotencyHeader preserves caller-provided header key', () => {
    const headers = withIdempotencyHeader(
      { 'Idempotency-Key': 'existing-key-999' },
      'POST'
    );
    assert.strictEqual(headers['Idempotency-Key'], 'existing-key-999');
  });

  test('withIdempotencyHeader does NOT inject key for GET requests', () => {
    const headers = withIdempotencyHeader(undefined, 'GET');
    assert.strictEqual(headers['Idempotency-Key'], undefined);
  });
});

describe('Query string serialization', () => {
  test('serializes string, number, boolean query parameters', () => {
    const qs = buildQueryString({
      limit: 50,
      q: 'resnet',
      active: true,
    });
    assert.strictEqual(qs, '?limit=50&q=resnet&active=true');
  });

  test('omits undefined and null values', () => {
    const qs = buildQueryString({
      limit: 50,
      state: undefined,
      cursor: null,
      q: 'cifar',
    });
    assert.strictEqual(qs, '?limit=50&q=cifar');
  });

  test('returns empty string when no params or all undefined', () => {
    assert.strictEqual(buildQueryString(undefined), '');
    assert.strictEqual(buildQueryString({}), '');
    assert.strictEqual(buildQueryString({ a: undefined, b: null }), '');
  });

  test('handles array parameters by repeating key', () => {
    const qs = buildQueryString({
      ids: ['id1', 'id2'],
    });
    assert.strictEqual(qs, '?ids=id1&ids=id2');
  });
});

describe('AppApiError normalization', () => {
  test('creates normalized error from standard API error payload', () => {
    const payload = {
      error: {
        code: 'JOB_FROZEN',
        message: 'Job contract has been frozen',
        details: { field: 'requested_contract.learning_rate' },
        request_id: 'req_test_123',
        command_id: 'cmd_test_456',
      },
    };

    const err = AppApiError.fromResponse(409, payload, '/api/v1/jobs/1', 'PATCH');

    assert.strictEqual(err.status, 409);
    assert.strictEqual(err.code, 'JOB_FROZEN');
    assert.strictEqual(err.message, 'Job contract has been frozen');
    assert.deepStrictEqual(err.details, { field: 'requested_contract.learning_rate' });
    assert.strictEqual(err.requestId, 'req_test_123');
    assert.strictEqual(err.commandId, 'cmd_test_456');
    assert.strictEqual(err.isConflict, true);
    assert.strictEqual(err.isValidationError, false);
    assert.strictEqual(err.isNetworkError, false);
  });

  test('creates normalized error from FastAPI validation error', () => {
    const payload = {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Request validation failed.',
        details: { errors: [{ loc: ['body', 'epochs'], msg: 'greater than 0' }] },
      },
    };

    const err = AppApiError.fromResponse(422, payload, '/api/v1/jobs', 'POST');

    assert.strictEqual(err.status, 422);
    assert.strictEqual(err.code, 'VALIDATION_ERROR');
    assert.strictEqual(err.isValidationError, true);
  });

  test('creates network error when fetch fails', () => {
    const rawErr = new TypeError('Failed to fetch');
    const err = AppApiError.fromNetworkError(rawErr, '/api/v1/health', 'GET');

    assert.strictEqual(err.status, 0);
    assert.strictEqual(err.code, 'NETWORK_ERROR');
    assert.strictEqual(err.isNetworkError, true);
    assert.strictEqual(err.message, 'Failed to fetch');
  });
});

describe('ApiClient HTTP dispatcher', () => {
  const originalFetch = globalThis.fetch;

  test('GET request successfully parses ApiResponse envelope', async () => {
    const mockData = {
      data: {
        backend: 'ok',
        postgres: 'ok',
        runtime_mcp: 'ok',
        dataset_manager: 'ok',
        timestamp: '2026-09-11T12:00:00Z',
      },
      meta: {
        request_id: 'req_health_001',
      },
    };

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(init?.method, 'GET');
      assert.strictEqual(
        (init?.headers as Record<string, string>)?.['Idempotency-Key'],
        undefined
      );
      return new Response(JSON.stringify(mockData), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': 'req_health_001',
        },
      });
    };

    const client = new ApiClient('http://localhost:8000');
    const res = await client.get<typeof mockData.data>('/api/v1/health');

    assert.deepStrictEqual(res.data, mockData.data);
    assert.strictEqual(res.meta?.request_id, 'req_health_001');

    globalThis.fetch = originalFetch;
  });

  test('GET paginated request parses PaginatedResponse envelope', async () => {
    const mockPaginated = {
      data: [
        { dataset_id: 'cifar10', name: 'CIFAR-10' },
      ],
      page: {
        next_cursor: 'cursor_abc123',
      },
      meta: {
        request_id: 'req_datasets_001',
      },
    };

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const urlStr = String(input);
      assert.ok(urlStr.includes('/api/v1/datasets?limit=10&task_type=image_classification'));
      return new Response(JSON.stringify(mockPaginated), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient('http://localhost:8000');
    const res = await client.getPaginated('/api/v1/datasets', {
      params: { limit: 10, task_type: 'image_classification' },
    });

    assert.strictEqual(res.data.length, 1);
    assert.strictEqual(res.page.next_cursor, 'cursor_abc123');

    globalThis.fetch = originalFetch;
  });

  test('POST request automatically injects Idempotency-Key and sends JSON body', async () => {
    let capturedHeaders: Record<string, string> = {};
    let capturedBody: string = '';

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      assert.strictEqual(init?.method, 'POST');
      capturedHeaders = (init?.headers as Record<string, string>) || {};
      capturedBody = String(init?.body);

      return new Response(
        JSON.stringify({
          data: { job_id: 'job_001', state: 'DRAFT' },
          meta: { request_id: 'req_job_001' },
        }),
        {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient('http://localhost:8000');
    const res = await client.post('/api/v1/jobs', {
      display_name: 'Test Job',
      requested_contract: {
        dataset_build_id: 'dsb_001',
        model_id: 'resnet18_groupnorm',
        epochs: 10,
        learning_rate: 0.01,
        training_seed: 2026,
        training_strategy: 'strict_bsp',
      },
    });

    assert.ok(capturedHeaders['Idempotency-Key'], 'Should auto-inject Idempotency-Key');
    assert.strictEqual(capturedHeaders['Content-Type'], 'application/json');
    assert.ok(capturedBody.includes('"display_name":"Test Job"'));
    assert.strictEqual(res.data.job_id, 'job_001');

    globalThis.fetch = originalFetch;
  });

  test('POST request throws AppApiError on 409 conflict', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          error: {
            code: 'DATASET_BUILD_IN_USE',
            message: 'Dataset Build is still referenced by Jobs or Checkpoints',
            details: { references: [{ type: 'JOB', id: 'job_001' }] },
          },
        }),
        {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient('http://localhost:8000');

    await assert.rejects(
      async () => {
        await client.post('/api/v1/dataset-builds/dsb_001/delete');
      },
      (err: any) => {
        assert.ok(err instanceof AppApiError);
        assert.strictEqual(err.status, 409);
        assert.strictEqual(err.code, 'DATASET_BUILD_IN_USE');
        assert.strictEqual(err.isConflict, true);
        return true;
      }
    );

    globalThis.fetch = originalFetch;
  });

  test('Throws normalized network error when fetch rejects', async () => {
    globalThis.fetch = async () => {
      throw new Error('Connection refused (ECONNREFUSED)');
    };

    const client = new ApiClient('http://localhost:8000');

    await assert.rejects(
      async () => {
        await client.get('/api/v1/health');
      },
      (err: any) => {
        assert.ok(err instanceof AppApiError);
        assert.strictEqual(err.status, 0);
        assert.strictEqual(err.code, 'NETWORK_ERROR');
        assert.strictEqual(err.isNetworkError, true);
        return true;
      }
    );

    globalThis.fetch = originalFetch;
  });
});
