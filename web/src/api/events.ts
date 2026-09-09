import { api } from './client';
import type { EventListItem, ListResponse } from '../domain/types';

export const eventsApi = {
  list: (params?: {
    attempt_id?: string;
    scope_type?: string;
    scope_id?: string;
    event_type?: string;
    severity?: string;
    limit?: number;
    cursor?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params?.attempt_id) qs.set('attempt_id', params.attempt_id);
    if (params?.scope_type) qs.set('scope_type', params.scope_type);
    if (params?.scope_id) qs.set('scope_id', params.scope_id);
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.severity) qs.set('severity', params.severity);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<EventListItem>>(`/events?${qs}`);
  },
};
