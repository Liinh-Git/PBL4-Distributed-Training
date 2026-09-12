/**
 * Dataset Builds API Service
 *
 * Source of Truth: API_contract.md (7.0 - 12.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  BuildCommandData,
  DatasetBuildCreateV1,
  DatasetBuildDeleteV1,
  DatasetBuildDeprecateResponseData,
  DatasetBuildDeprecateV1,
  DatasetBuildDetailData,
  DatasetBuildListItemData,
  DatasetBuildRebuildV1,
  DatasetBuildState,
  PaginatedResponse,
} from '../types/api';

export interface ListDatasetBuildsParams {
  dataset_id?: string;
  state?: DatasetBuildState | string;
  profile?: string;
  cursor?: string | null;
  limit?: number;
}

export class DatasetBuildsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 7.0 POST /api/v1/dataset-builds — Create a new dataset build (async command)
   */
  async createBuild(
    data: DatasetBuildCreateV1,
    options?: RequestOptions
  ): Promise<ApiResponse<BuildCommandData>> {
    return this.client.post<ApiResponse<BuildCommandData>, DatasetBuildCreateV1>(
      '/api/v1/dataset-builds',
      data,
      options
    );
  }

  /**
   * 8.0 GET /api/v1/dataset-builds — List dataset builds with cursor pagination
   */
  async listBuilds(
    params?: ListDatasetBuildsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<DatasetBuildListItemData>> {
    return this.client.getPaginated<DatasetBuildListItemData>('/api/v1/dataset-builds', {
      ...options,
      params: {
        dataset_id: params?.dataset_id,
        state: params?.state,
        profile: params?.profile,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }

  /**
   * 9.0 GET /api/v1/dataset-builds/{dataset_build_id} — Get dataset build details
   */
  async getBuild(
    buildId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<DatasetBuildDetailData>> {
    return this.client.get<DatasetBuildDetailData>(
      `/api/v1/dataset-builds/${encodeURIComponent(buildId)}`,
      options
    );
  }

  /**
   * 10.0 POST /api/v1/dataset-builds/{dataset_build_id}/rebuild — Rebuild dataset build
   */
  async rebuildBuild(
    buildId: string,
    data?: DatasetBuildRebuildV1,
    options?: RequestOptions
  ): Promise<ApiResponse<BuildCommandData>> {
    return this.client.post<ApiResponse<BuildCommandData>, DatasetBuildRebuildV1 | undefined>(
      `/api/v1/dataset-builds/${encodeURIComponent(buildId)}/rebuild`,
      data || {},
      options
    );
  }

  /**
   * 11.0 POST /api/v1/dataset-builds/{dataset_build_id}/deprecate — Deprecate a READY build
   */
  async deprecateBuild(
    buildId: string,
    data?: DatasetBuildDeprecateV1,
    options?: RequestOptions
  ): Promise<ApiResponse<DatasetBuildDeprecateResponseData>> {
    return this.client.post<ApiResponse<DatasetBuildDeprecateResponseData>, DatasetBuildDeprecateV1 | undefined>(
      `/api/v1/dataset-builds/${encodeURIComponent(buildId)}/deprecate`,
      data || {},
      options
    );
  }

  /**
   * 12.0 POST /api/v1/dataset-builds/{dataset_build_id}/delete — Delete/purge dataset build
   */
  async deleteBuild(
    buildId: string,
    data?: DatasetBuildDeleteV1,
    options?: RequestOptions
  ): Promise<ApiResponse<BuildCommandData>> {
    return this.client.post<ApiResponse<BuildCommandData>, DatasetBuildDeleteV1 | undefined>(
      `/api/v1/dataset-builds/${encodeURIComponent(buildId)}/delete`,
      data || {},
      options
    );
  }
}

export const datasetBuildsService = new DatasetBuildsService();
