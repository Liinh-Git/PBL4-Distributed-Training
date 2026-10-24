/**
 * Strict BSP Steps API Service
 *
 * API implementation reference: docs/API.md
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

  /** Load the complete measured history, including attempts longer than one page. */
  async listAllSteps(attemptId: string): Promise<PaginatedResponse<StepListItemData>> {
    let response = await this.listSteps(attemptId, { limit: 200 });
    const items = new Map(response.data.map(step => [step.step_id, step]));
    const cursors = new Set<string>();
    while (response.page?.next_cursor) {
      const cursor = response.page.next_cursor;
      if (cursors.has(cursor)) throw new Error('Repeated steps pagination cursor');
      cursors.add(cursor);
      response = await this.listSteps(attemptId, { limit: 200, cursor });
      for (const step of response.data) items.set(step.step_id, step);
    }
    return { ...response, data: [...items.values()].sort((a, b) => b.step_id - a.step_id) };
  }

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
