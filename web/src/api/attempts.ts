/**
 * Attempts Lifecycle & Runtime Control API Service
 *
 * Source of Truth: API_contract.md (23.0 - 27.0, 34.0 - 35.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  AbortAttemptRequest,
  AbortAttemptResponseData,
  ApiResponse,
  AttemptDetailData,
  AttemptListItemData,
  AttemptSnapshotData,
  AttemptState,
  CheckpointRequestBody,
  CheckpointRequestResponseData,
  ExecutionMode,
  JoinSpecData,
  PaginatedResponse,
  RuntimeEventsResponseData,
} from '../types/api';

export interface ListAttemptsParams {
  job_id?: string;
  state?: AttemptState | string;
  execution_mode?: ExecutionMode | string;
  cursor?: string | null;
  limit?: number;
}

export interface CatchUpEventsParams {
  after_seq?: number;
  limit?: number;
}

export class AttemptsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 23.0 GET /api/v1/attempts — List attempts with filtering and cursor pagination
   */
  async listAttempts(
    params?: ListAttemptsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<AttemptListItemData>> {
    return this.client.getPaginated<AttemptListItemData>('/api/v1/attempts', {
      ...options,
      params: {
        job_id: params?.job_id,
        state: params?.state,
        execution_mode: params?.execution_mode,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }

  /**
   * 24.0 GET /api/v1/attempts/{attempt_id} — Get attempt detail
   */
  async getAttempt(
    attemptId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<AttemptDetailData>> {
    return this.client.get<AttemptDetailData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}`,
      options
    );
  }

  /**
   * 25.0 POST /api/v1/attempts/{attempt_id}/abort — Abort running attempt
   */
  async abortAttempt(
    attemptId: string,
    data?: AbortAttemptRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<AbortAttemptResponseData>> {
    return this.client.post<ApiResponse<AbortAttemptResponseData>, AbortAttemptRequest | undefined>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/abort`,
      data,
      options
    );
  }

  /**
   * 26.0 GET /api/v1/attempts/{attempt_id}/join-spec — Get worker join spec
   */
  async getJoinSpec(
    attemptId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<JoinSpecData>> {
    return this.client.get<JoinSpecData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/join-spec`,
      options
    );
  }

  /**
   * 27.0 GET /api/v1/attempts/{attempt_id}/snapshot — Get attempt runtime snapshot
   */
  async getSnapshot(
    attemptId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<AttemptSnapshotData>> {
    return this.client.get<AttemptSnapshotData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/snapshot`,
      options
    );
  }

  /**
   * 34.0 POST /api/v1/attempts/{attempt_id}/checkpoint-requests — Manual checkpoint request
   */
  async requestCheckpoint(
    attemptId: string,
    data?: CheckpointRequestBody,
    options?: RequestOptions
  ): Promise<ApiResponse<CheckpointRequestResponseData>> {
    return this.client.post<
      ApiResponse<CheckpointRequestResponseData>,
      CheckpointRequestBody | undefined
    >(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/checkpoint-requests`,
      data || { reason: 'manual' },
      options
    );
  }

  /**
   * 35.0 GET /api/v1/attempts/{attempt_id}/events — Catch-up runtime events with after_seq
   */
  async getCatchUpEvents(
    attemptId: string,
    params?: CatchUpEventsParams,
    options?: RequestOptions
  ): Promise<RuntimeEventsResponseData> {
    return this.client.request<RuntimeEventsResponseData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/events`,
      {
        ...options,
        method: 'GET',
        params: {
          after_seq: params?.after_seq ?? 0,
          limit: params?.limit ?? 50,
        },
      }
    );
  }
}

export const attemptsService = new AttemptsService();
