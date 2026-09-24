/**
 * Jobs Management API Service
 *
 * Source of Truth: API_contract.md (13.0 - 22.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  JobArchiveResponseData,
  JobCloneResponseData,
  JobCreateRequest,
  JobDetailData,
  JobListItemData,
  JobPatchRequest,
  JobResumeRequest,
  JobStartRequest,
  JobState,
  JobValidateResponseData,
  PaginatedResponse,
  StartAttemptResponseData,
} from '../types/api';

export interface ListJobsParams {
  state?: JobState | string;
  dataset_build_id?: string;
  q?: string;
  cursor?: string | null;
  limit?: number;
}

export class JobsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 13.0 POST /api/v1/jobs — Create a new Job in DRAFT state
   */
  async createJob(
    data: JobCreateRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<JobDetailData>> {
    return this.client.post<ApiResponse<JobDetailData>, JobCreateRequest>(
      '/api/v1/jobs',
      data,
      options
    );
  }

  /**
   * 14.0 GET /api/v1/jobs — List jobs with cursor pagination
   */
  async listJobs(
    params?: ListJobsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<JobListItemData>> {
    return this.client.getPaginated<JobListItemData>('/api/v1/jobs', {
      ...options,
      params: {
        state: params?.state,
        dataset_build_id: params?.dataset_build_id,
        q: params?.q,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }

  /**
   * 15.0 GET /api/v1/jobs/{job_id} — Get job detail
   */
  async getJob(
    jobId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<JobDetailData>> {
    return this.client.get<JobDetailData>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}`,
      options
    );
  }

  /**
   * 16.0 PATCH /api/v1/jobs/{job_id} — Partial update job metadata or DRAFT contract
   */
  async patchJob(
    jobId: string,
    data: JobPatchRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<JobDetailData>> {
    return this.client.patch<ApiResponse<JobDetailData>, JobPatchRequest>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}`,
      data,
      options
    );
  }

  /**
   * 17.0 POST /api/v1/jobs/{job_id}/validate — Validate and preview resolved contract
   */
  async validateJob(
    jobId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<JobValidateResponseData>> {
    return this.client.post<ApiResponse<JobValidateResponseData>, undefined>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/validate`,
      undefined,
      options
    );
  }

  /**
   * 18.0 POST /api/v1/jobs/{job_id}/clone — Clone existing job to a new DRAFT job
   */
  async cloneJob(
    jobId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<JobCloneResponseData>> {
    return this.client.post<ApiResponse<JobCloneResponseData>, undefined>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/clone`,
      undefined,
      options
    );
  }

  /**
   * 19.0 POST /api/v1/jobs/{job_id}/archive — Archive job
   */
  async archiveJob(
    jobId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<JobArchiveResponseData>> {
    return this.client.post<ApiResponse<JobArchiveResponseData>, undefined>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/archive`,
      undefined,
      options
    );
  }

  /**
   * 20.0 POST /api/v1/jobs/{job_id}/start — Start training fresh
   */
  async startJob(
    jobId: string,
    data?: JobStartRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<StartAttemptResponseData>> {
    return this.client.post<ApiResponse<StartAttemptResponseData>, JobStartRequest | undefined>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/start`,
      data,
      options
    );
  }

  /**
   * 21.0 POST /api/v1/jobs/{job_id}/retry — Retry training from start
   */
  async retryJob(
    jobId: string,
    data?: JobStartRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<StartAttemptResponseData>> {
    return this.client.post<ApiResponse<StartAttemptResponseData>, JobStartRequest | undefined>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/retry`,
      data,
      options
    );
  }

  /**
   * 22.0 POST /api/v1/jobs/{job_id}/resume — Resume training from checkpoint
   */
  async resumeJob(
    jobId: string,
    data: JobResumeRequest,
    options?: RequestOptions
  ): Promise<ApiResponse<StartAttemptResponseData>> {
    return this.client.post<ApiResponse<StartAttemptResponseData>, JobResumeRequest>(
      `/api/v1/jobs/${encodeURIComponent(jobId)}/resume`,
      data,
      options
    );
  }
}

export const jobsService = new JobsService();
