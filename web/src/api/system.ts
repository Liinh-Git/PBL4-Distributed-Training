/**
 * System and Capabilities API Service
 *
 * Source of Truth: API_contract.md (1.0, 2.0, 3.0)
 */

import { apiClient, ApiClient } from './client';
import {
  ApiResponse,
  CapabilitiesData,
  HealthData,
  RuntimeSnapshotData,
} from '../types/api';

export class SystemService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 1.0 GET /api/v1/health — Composite health check of backend & dependencies
   */
  async getHealth(): Promise<ApiResponse<HealthData>> {
    return this.client.get<HealthData>('/api/v1/health');
  }

  /**
   * 2.0 GET /api/v1/system/capabilities — System capabilities, protocol versions, supported models
   */
  async getCapabilities(): Promise<ApiResponse<CapabilitiesData>> {
    return this.client.get<CapabilitiesData>('/api/v1/system/capabilities');
  }

  /**
   * 3.0 GET /api/v1/runtime/snapshot — Latest management-plane runtime projection
   */
  async getRuntimeSnapshot(): Promise<ApiResponse<RuntimeSnapshotData>> {
    return this.client.get<RuntimeSnapshotData>('/api/v1/runtime/snapshot');
  }
}

export const systemService = new SystemService();
