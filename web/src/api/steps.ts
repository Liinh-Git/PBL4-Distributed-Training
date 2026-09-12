/**
 * Strict BSP Steps API Service
 *
 * Source of Truth: API_contract.md (30.0 - 31.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  PaginatedResponse,
  StepDetailData,
  StepListItemData,
} from '../types/api';

export interface ListStepsParams {
  cursor?: string | null;
  limit?: number;
}

export class StepsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 30.0 GET /api/v1/attempts/{attempt_id}/steps — List Strict BSP steps with cursor pagination
   */
  async listSteps(
    attemptId: string,
    params?: ListStepsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<StepListItemData>> {
    return this.client.getPaginated<StepListItemData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/steps`,
      {
        ...options,
        params: {
          cursor: params?.cursor,
          limit: params?.limit ?? 50,
        },
      }
    );
  }

  /**
   * 31.0 GET /api/v1/attempts/{attempt_id}/steps/{step_id} — Get step detail and worker steps
   */
  async getStep(
    attemptId: string,
    stepId: number,
    options?: RequestOptions
  ): Promise<ApiResponse<StepDetailData>> {
    return this.client.get<StepDetailData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/steps/${encodeURIComponent(stepId)}`,
      options
    );
  }
}

export const stepsService = new StepsService();
