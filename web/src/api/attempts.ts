/**
 * Attempts Lifecycle & Runtime Control API Service
 *
 * API implementation reference: docs/API.md
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import { AppApiError } from './errors';
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
  event_type?: string;
}

// COMPLETING is retained only for compatibility with legacy persisted attempts.
export const isActiveAttempt = (state?: string | null): boolean =>
  ['CREATED', 'WAITING_WORKERS', 'PROVISIONING', 'INITIALIZING', 'RUNNING', 'COMPLETING'].includes(state ?? '');

export class AttemptsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  async getActiveAttempt(): Promise<AttemptListItemData | null> {
    let cursor: string | null | undefined;
    do {
      const res = await this.listAttempts({ limit: 200, cursor });
      const active = res.data.find(attempt => isActiveAttempt(attempt.state));
      if (active) return active;
      if (res.data.some(attempt => !['COMPLETED', 'FAILED', 'ABORTED'].includes(attempt.state))) {
        throw new Error('Unable to verify active attempts. Refresh before starting training.');
      }
      cursor = res.page?.next_cursor;
    } while (cursor);
    return null;
  }

  async assertNoActiveAttempt(): Promise<void> {
    const active = await this.getActiveAttempt();
    if (active) {
      throw new AppApiError({
        status: 409,
        code: 'ACTIVE_ATTEMPT_EXISTS',
        message: `Attempt ${active.attempt_id} for job ${active.job_id} is still active. View that run before starting another.`,
      });
    }
  }

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
    const queryParams: Record<string, string | number> = {
      after_seq: params?.after_seq ?? 0,
      limit: params?.limit ?? 50,
    };
    if (params?.event_type) {
      queryParams.event_type = params.event_type;
    }
    return this.client.request<RuntimeEventsResponseData>(
      `/api/v1/attempts/${encodeURIComponent(attemptId)}/events`,
      {
        ...options,
        method: 'GET',
        params: queryParams,
      }
    );
  }
}

export const attemptsService = new AttemptsService();
