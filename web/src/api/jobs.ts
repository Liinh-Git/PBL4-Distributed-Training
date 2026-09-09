import { api } from './client';
import type {
  JobListItem,
  JobDetail,
  StartAttemptResponse,
  ListResponse,
  RequestedContract,
} from '../domain/types';

export const jobsApi = {
  list: (params?: { state?: string; limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.state) qs.set('state', params.state);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<JobListItem>>(`/jobs?${qs}`);
  },

  get: (jobId: string) => api.getItem<JobDetail>(`/jobs/${jobId}`),

  create: (body: { display_name: string; description?: string; requested_contract: RequestedContract }, idempotencyKey: string) =>
    api.postItem<JobDetail>('/jobs', body, { idempotencyKey }),

  update: (jobId: string, body: { display_name?: string; description?: string; requested_contract?: Partial<RequestedContract> }) =>
    api.patchItem<JobDetail>(`/jobs/${jobId}`, body),


  start: (jobId: string, idempotencyKey: string, note?: string) =>
    api.postItem<StartAttemptResponse>(`/jobs/${jobId}/start`, note ? { note } : undefined, { idempotencyKey }),

  retry: (jobId: string, idempotencyKey: string) => api.postItem<StartAttemptResponse>(`/jobs/${jobId}/retry`, undefined, { idempotencyKey }),

  resume: (jobId: string, checkpoint_id: string, idempotencyKey: string) =>
    api.postItem<StartAttemptResponse>(`/jobs/${jobId}/resume`, { checkpoint_id }, { idempotencyKey }),

  clone: (jobId: string, idempotencyKey: string) => api.postItem<JobDetail>(`/jobs/${jobId}/clone`, undefined, { idempotencyKey }),

  archive: (jobId: string, idempotencyKey: string) => api.postItem<{ job_id: string; state: string; archived_at: string }>(`/jobs/${jobId}/archive`, undefined, { idempotencyKey }),

  validate: (jobId: string) =>
    api.postItem<{ valid: boolean; errors?: string[] }>(`/jobs/${jobId}/validate`),
};
