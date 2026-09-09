import { api } from './client';
import type {
  DatasetItem,
  DatasetBuildListItem,
  ListResponse,
} from '../domain/types';

export const datasetsApi = {
  list: (params?: { task_type?: string; limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.task_type) qs.set('task_type', params.task_type);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<DatasetItem>>(`/datasets?${qs}`);
  },

  get: (datasetId: string) => api.getItem<DatasetItem>(`/datasets/${datasetId}`),

  create: (body: { name: string; task_type: 'image_classification'; source_type: 'builtin'; source_reference: 'cifar10' }, idempotencyKey: string) =>
    api.postItem<DatasetItem>('/datasets', body, { idempotencyKey }),

  builds: (params?: { dataset_id?: string; state?: string; limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.dataset_id) qs.set('dataset_id', params.dataset_id);
    if (params?.state) qs.set('state', params.state);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<DatasetBuildListItem>>(`/dataset-builds?${qs}`);
  },

  getBuild: (buildId: string) => api.getItem<DatasetBuildListItem>(`/dataset-builds/${buildId}`),

  createBuild: (
    body: {
      dataset_id: string;
      profile: string;
      batch_size?: number;
      partition_seed?: number;
      preprocessing?: Record<string, unknown>;
    },
    idempotencyKey: string,
  ) => api.postItem<DatasetBuildListItem>('/dataset-builds', body, { idempotencyKey }),

  rebuildBuild: (
    buildId: string,
    idempotencyKey: string,
    body?: { batch_size?: number; partition_seed?: number; preprocessing?: Record<string, unknown> },
  ) => api.postItem(`/dataset-builds/${buildId}/rebuild`, body, { idempotencyKey }),

  deprecateBuild: (buildId: string, idempotencyKey: string, reason?: string) =>
    api.postItem(`/dataset-builds/${buildId}/deprecate`, reason ? { reason } : undefined, { idempotencyKey }),

  deleteBuild: (buildId: string, idempotencyKey: string, reason?: string) =>
    api.postItem(`/dataset-builds/${buildId}/delete`, reason ? { reason } : undefined, { idempotencyKey }),
};
