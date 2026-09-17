/**
 * Audit Events API Service
 *
 * Source of Truth: API_contract.md (36.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  EventListItemData,
  EventSeverity,
  PaginatedResponse,
  ScopeType,
} from '../types/api';

export interface ListEventsParams {
  scope_type?: ScopeType | string;
  scope_id?: string;
  event_type?: string;
  severity?: EventSeverity | string;
  from?: string;
  to?: string;
  cursor?: string | null;
  limit?: number;
}

export class EventsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 36.0 GET /api/v1/events — Audit log of management-plane and system events
   */
  async listEvents(
    params?: ListEventsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<EventListItemData>> {
    return this.client.getPaginated<EventListItemData>('/api/v1/events', {
      ...options,
      params: {
        scope_type: params?.scope_type,
        scope_id: params?.scope_id,
        event_type: params?.event_type,
        severity: params?.severity,
        from: params?.from,
        to: params?.to,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }
}

export const eventsService = new EventsService();
