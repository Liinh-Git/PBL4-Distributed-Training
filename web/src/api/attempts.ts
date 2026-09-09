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

  get: (attemptId: string) => api.getItem<AttemptDetail>(`/attempts/${attemptId}`),

  snapshot: (attemptId: string) => api.getItem<AttemptSnapshot>(`/attempts/${attemptId}/snapshot`),

  abort: (attemptId: string, idempotencyKey: string, reason?: string) =>
    api.postItem(`/attempts/${attemptId}/abort`, reason ? { reason } : undefined, { idempotencyKey }),

  requestCheckpoint: (attemptId: string, idempotencyKey: string, reason?: string) =>
    api.postItem(`/attempts/${attemptId}/checkpoint-requests`, reason ? { reason } : undefined, { idempotencyKey }),

  workers: (attemptId: string) =>
    api.get<ListResponse<WorkerSessionItem>>(`/attempts/${attemptId}/workers`),

  steps: (attemptId: string, params?: { limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<StepListItem>>(`/attempts/${attemptId}/steps?${qs}`);
  },

  events: (attemptId: string, params?: { limit?: number; event_type?: string; severity?: string; after_seq?: number }) => {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.after_seq !== undefined) qs.set('after_seq', String(params.after_seq));
    return api.get<{
      data: EventListItem[];
      page: { next_cursor: string | null };
      meta: { complete: boolean; gap_detected: boolean; snapshot_required: boolean };
    }>(`/attempts/${attemptId}/events?${qs}`);
  },
};
