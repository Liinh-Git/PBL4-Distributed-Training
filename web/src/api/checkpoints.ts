/**
 * Checkpoints API Service
 *
 * Source of Truth: API_contract.md (32.0, 33.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  CheckpointDetailData,
  CheckpointListItemData,
  CheckpointState,
  PaginatedResponse,
} from '../types/api';

export interface ListCheckpointsParams {
  job_id?: string;
  attempt_id?: string;
  state?: CheckpointState | string;
  cursor?: string | null;
  limit?: number;
}

export class CheckpointsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 32.0 GET /api/v1/checkpoints — List checkpoints with cursor pagination
   */
  async listCheckpoints(
    params?: ListCheckpointsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<CheckpointListItemData>> {
    return this.client.getPaginated<CheckpointListItemData>('/api/v1/checkpoints', {
      ...options,
      params: {
        job_id: params?.job_id,
        attempt_id: params?.attempt_id,
        state: params?.state,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }

  /**
   * 33.0 GET /api/v1/checkpoints/{checkpoint_id} — Get checkpoint detail with integrity and recovery cursor
   */
  async getCheckpoint(
    checkpointId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<CheckpointDetailData>> {
    return this.client.get<CheckpointDetailData>(
      `/api/v1/checkpoints/${encodeURIComponent(checkpointId)}`,
      options
    );
  }
}

export const checkpointsService = new CheckpointsService();
