/**
 * Workers Observation API Service
 *
 * Source of Truth: API_contract.md (28.0 - 29.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  WorkerDetailData,
  WorkerSessionItemData,
} from '../types/api';

export interface GetWorkerParams {
  include_history?: boolean;
}

export class WorkersService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 28.0 GET /api/v1/attempts/{attempt_id}/workers — List worker sessions for attempt
   */
  async listWorkers(
    attemptId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<WorkerSessionItemData[]>> {
    return this.client.get<WorkerSessionItemData[]>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/workers`,
      options
    );
  }

  /**
   * 29.0 GET /api/v1/attempts/{attempt_id}/workers/{worker_id} — Get worker detail and session history
   */
  async getWorker(
    attemptId: string,
    workerId: number,
    params?: GetWorkerParams,
    options?: RequestOptions
  ): Promise<ApiResponse<WorkerDetailData>> {
    return this.client.get<WorkerDetailData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/workers/${encodeURIComponent(workerId)}`,
      {
        ...options,
        params: {
          include_history: params?.include_history ?? false,
        },
      }
    );
  }
}

export const workersService = new WorkersService();
