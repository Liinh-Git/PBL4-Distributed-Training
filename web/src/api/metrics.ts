/**
 * Training Metrics Time-Series API Service
 *
 * Source of Truth: API_contract.md (40.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  MetricItemData,
  PaginatedResponse,
} from '../types/api';

export interface ListMetricsParams {
  name?: string;
  worker_id?: number;
  from_step?: number;
  to_step?: number;
  from?: string;
  to?: string;
  cursor?: string | null;
  limit?: number;
}

export class MetricsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 40.0 GET /api/v1/attempts/{attempt_id}/metrics — Query training metrics time-series
   */
  async queryMetrics(
    attemptId: string,
    params?: ListMetricsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<MetricItemData>> {
    return this.client.getPaginated<MetricItemData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/metrics`,
      {
        ...options,
        params: {
          name: params?.name,
          worker_id: params?.worker_id,
          from_step: params?.from_step,
          to_step: params?.to_step,
          from: params?.from,
          to: params?.to,
          cursor: params?.cursor,
          limit: params?.limit ?? 100,
        },
      }
    );
  }
}

export const metricsService = new MetricsService();
