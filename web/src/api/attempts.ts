import { api } from './client';
import type {
  AttemptListItem,
  AttemptDetail,
  AttemptSnapshot,
  WorkerSessionItem,
  StepListItem,
  EventListItem,
  ListResponse,
} from '../domain/types';

export const attemptsApi = {
  list: (params?: { job_id?: string; state?: string; limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.job_id) qs.set('job_id', params.job_id);
    if (params?.state) qs.set('state', params.state);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<AttemptListItem>>(`/attempts?${qs}`);
  },

  get: (attemptId: string) => api.get<AttemptDetail>(`/attempts/${attemptId}`),

  snapshot: (attemptId: string) => api.get<AttemptSnapshot>(`/attempts/${attemptId}/snapshot`),

  abort: (attemptId: string, reason?: string) =>
    api.post(`/attempts/${attemptId}/abort`, reason ? { reason } : undefined),

  requestCheckpoint: (attemptId: string, reason?: string) =>
    api.post(`/attempts/${attemptId}/checkpoint`, reason ? { reason } : undefined),

  workers: (attemptId: string) =>
    api.get<ListResponse<WorkerSessionItem>>(`/attempts/${attemptId}/workers`),

  steps: (attemptId: string, params?: { limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<StepListItem>>(`/attempts/${attemptId}/steps?${qs}`);
  },

  events: (attemptId: string, params?: { limit?: number; event_type?: string; severity?: string }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.severity) qs.set('severity', params.severity);
    return api.get<{ data: EventListItem[] }>(`/attempts/${attemptId}/events?${qs}`);
  },
};
