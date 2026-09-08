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

  get: (jobId: string) => api.get<{ data: JobDetail }>(`/jobs/${jobId}`),

  create: (body: { display_name: string; description?: string; requested_contract: RequestedContract }) =>
    api.post<JobDetail>('/jobs', body),

  update: (jobId: string, body: { display_name?: string; description?: string; requested_contract?: Partial<RequestedContract> }) =>
    api.patch<JobDetail>(`/jobs/${jobId}`, body),

  freeze: (jobId: string) => api.post<JobDetail>(`/jobs/${jobId}/freeze`),

  start: (jobId: string, note?: string) =>
    api.post<StartAttemptResponse>(`/jobs/${jobId}/start`, note ? { note } : undefined),

  retry: (jobId: string) => api.post<StartAttemptResponse>(`/jobs/${jobId}/retry`),

  resume: (jobId: string, checkpoint_id: string) =>
    api.post<StartAttemptResponse>(`/jobs/${jobId}/resume`, { checkpoint_id }),

  clone: (jobId: string) => api.post<JobDetail>(`/jobs/${jobId}/clone`),

  archive: (jobId: string) => api.post<{ job_id: string; state: string; archived_at: string }>(`/jobs/${jobId}/archive`),

  validate: (jobId: string) =>
    api.post<{ valid: boolean; errors?: string[] }>(`/jobs/${jobId}/validate`),
};
