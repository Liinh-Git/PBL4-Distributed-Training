import { api } from './client';
import type {
  HealthResponse,
  CapabilitiesResponse,
  RuntimeSnapshot,
} from '../domain/types';

export const systemApi = {
  health: () => api.get<HealthResponse>('/health'),
  capabilities: () => api.get<CapabilitiesResponse>('/system/capabilities'),
  runtimeSnapshot: () => api.get<RuntimeSnapshot>('/runtime/snapshot'),
};
