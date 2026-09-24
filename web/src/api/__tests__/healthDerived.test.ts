/**
 * Unit tests for deriveHealthState, mapSubsystemStatus, and worker state helpers.
 *
 * Runs with Node.js built-in test runner: npx tsx --test src/api/__tests__/healthDerived.test.ts
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { deriveHealthState, mapSubsystemStatus } from '../../utils/health';
import { HealthData } from '../../types/api';

describe('Health State Derivation Tests (deriveHealthState)', () => {
  const baseHealth: HealthData = {
    backend: 'healthy',
    postgres: 'healthy',
    runtime_mcp: 'connected',
    dataset_manager: 'healthy',
    timestamp: '2026-09-24T12:00:00Z',
  };

  test('returns "healthy" when all subsystems are healthy and runtime is connected', () => {
    const state = deriveHealthState(baseHealth);
    assert.strictEqual(state, 'healthy');
  });

  test('returns "degraded" when runtime_mcp is disconnected', () => {
    const health: HealthData = {
      ...baseHealth,
      runtime_mcp: 'disconnected',
    };
    const state = deriveHealthState(health);
    assert.strictEqual(state, 'degraded');
  });

  test('returns "degraded" when postgres is degraded', () => {
    const health: HealthData = {
      ...baseHealth,
      postgres: 'degraded',
    };
    const state = deriveHealthState(health);
    assert.strictEqual(state, 'degraded');
  });

  test('returns "degraded" when dataset_manager is degraded or unreachable', () => {
    const degradedHealth: HealthData = {
      ...baseHealth,
      dataset_manager: 'degraded',
    };
    assert.strictEqual(deriveHealthState(degradedHealth), 'degraded');

    const unreachableHealth: HealthData = {
      ...baseHealth,
      dataset_manager: 'unreachable',
    };
    assert.strictEqual(deriveHealthState(unreachableHealth), 'degraded');
  });

  test('returns "degraded" when isRuntimeStale is true even if all subsystems are healthy', () => {
    const state = deriveHealthState(baseHealth, { isRuntimeStale: true });
    assert.strictEqual(state, 'degraded');
  });

  test('returns "down" when backend is not healthy', () => {
    const health: HealthData = {
      ...baseHealth,
      backend: 'down',
    };
    const state = deriveHealthState(health);
    assert.strictEqual(state, 'down');
  });

  test('returns "down" when health is null or hasNetworkError is true', () => {
    assert.strictEqual(deriveHealthState(null), 'down');
    assert.strictEqual(deriveHealthState(undefined), 'down');
    assert.strictEqual(deriveHealthState(baseHealth, { hasNetworkError: true }), 'down');
  });
});

describe('Subsystem Status Mapping Tests (mapSubsystemStatus)', () => {
  test('maps healthy / connected / ok to HEALTHY', () => {
    assert.strictEqual(mapSubsystemStatus('healthy'), 'HEALTHY');
    assert.strictEqual(mapSubsystemStatus('connected'), 'HEALTHY');
    assert.strictEqual(mapSubsystemStatus('ok'), 'HEALTHY');
  });

  test('maps degraded / disconnected / unknown to DEGRADED', () => {
    assert.strictEqual(mapSubsystemStatus('degraded'), 'DEGRADED');
    assert.strictEqual(mapSubsystemStatus('disconnected'), 'DEGRADED');
    assert.strictEqual(mapSubsystemStatus('unknown'), 'DEGRADED');
  });

  test('maps unrecognized or empty strings to DOWN', () => {
    assert.strictEqual(mapSubsystemStatus('unreachable'), 'DOWN');
    assert.strictEqual(mapSubsystemStatus('failed'), 'DOWN');
    assert.strictEqual(mapSubsystemStatus(undefined), 'DOWN');
  });

  test('returns DEGRADED if isStale is true regardless of status', () => {
    assert.strictEqual(mapSubsystemStatus('healthy', true), 'DEGRADED');
  });
});
