import { HealthData } from '../types/api';

export type OverallHealthState = 'healthy' | 'degraded' | 'down';

export interface HealthDeriveOptions {
  isRuntimeStale?: boolean;
  hasNetworkError?: boolean;
}

/**
 * Derives overall system health state from Backend HealthData without fabricating
 * a synthetic 'status' field on the API contract.
 *
 * Backend HealthData semantics:
 * - backend: 'healthy'
 * - postgres: 'healthy' | 'degraded'
 * - runtime_mcp: 'connected' | 'disconnected'
 * - dataset_manager: 'healthy' | 'degraded' | 'unreachable' | 'unknown'
 */
export function deriveHealthState(
  health: HealthData | null | undefined,
  options?: HealthDeriveOptions
): OverallHealthState {
  if (options?.hasNetworkError || !health) {
    return 'down';
  }

  // If backend itself is not healthy, overall status is down
  if (health.backend !== 'healthy') {
    return 'down';
  }

  // Any degraded subsystem, disconnected runtime, or stale stream degrades the system
  if (
    options?.isRuntimeStale ||
    health.postgres === 'degraded' ||
    health.runtime_mcp === 'disconnected' ||
    health.dataset_manager === 'degraded' ||
    health.dataset_manager === 'unreachable' ||
    health.dataset_manager === 'unknown'
  ) {
    return 'degraded';
  }

  return 'healthy';
}

/**
 * Maps a single subsystem health string to visual status.
 */
export function mapSubsystemStatus(
  status: string | undefined,
  isStale: boolean = false
): 'HEALTHY' | 'DEGRADED' | 'DOWN' {
  if (isStale) return 'DEGRADED';
  if (!status) return 'DOWN';
  const s = status.toLowerCase();
  if (s === 'healthy' || s === 'connected' || s === 'ok') return 'HEALTHY';
  if (s === 'degraded' || s === 'disconnected' || s === 'unknown') return 'DEGRADED';
  return 'DOWN';
}
