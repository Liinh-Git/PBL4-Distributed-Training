import { api } from './client';
import type {
  HealthResponse,
  CapabilitiesResponse,
  RuntimeSnapshot,
} from '../domain/types';

export const systemApi = {
  health: () => api.getItem<HealthResponse>('/health'),
  capabilities: () => api.getItem<CapabilitiesResponse>('/system/capabilities'),
  runtimeSnapshot: () => api.getItem<RuntimeSnapshot>('/runtime/snapshot'),
};
