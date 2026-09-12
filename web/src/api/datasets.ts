/**
 * Datasets API Service
 *
 * Source of Truth: API_contract.md (4.0, 5.0, 6.0)
 */

import { apiClient, ApiClient, RequestOptions } from './client';
import {
  ApiResponse,
  DatasetDetailData,
  DatasetItemData,
  DatasetSourceV1,
  PaginatedResponse,
} from '../types/api';

export interface ListDatasetsParams {
  task_type?: string;
  q?: string;
  cursor?: string | null;
  limit?: number;
}

export class DatasetsService {
  constructor(private readonly client: ApiClient = apiClient) {}

  /**
   * 4.0 POST /api/v1/datasets — Create a logical dataset source
   */
  async createDataset(
    data: DatasetSourceV1,
    options?: RequestOptions
  ): Promise<ApiResponse<DatasetDetailData>> {
    return this.client.post<ApiResponse<DatasetDetailData>, DatasetSourceV1>(
      '/api/v1/datasets',
      data,
      options
    );
  }

  /**
   * 5.0 GET /api/v1/datasets — List catalog datasets with cursor pagination
   */
  async listDatasets(
    params?: ListDatasetsParams,
    options?: RequestOptions
  ): Promise<PaginatedResponse<DatasetItemData>> {
    return this.client.getPaginated<DatasetItemData>('/api/v1/datasets', {
      ...options,
      params: {
        task_type: params?.task_type,
        q: params?.q,
        cursor: params?.cursor,
        limit: params?.limit,
      },
    });
  }

  /**
   * 6.0 GET /api/v1/datasets/{dataset_id} — Get dataset details and build counts
   */
  async getDataset(
    datasetId: string,
    options?: RequestOptions
  ): Promise<ApiResponse<DatasetDetailData>> {
    return this.client.get<DatasetDetailData>(`/api/v1/datasets/${encodeURIComponent(datasetId)}`, options);
  }
}

export const datasetsService = new DatasetsService();
