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

  builds: (params?: { dataset_id?: string; state?: string; limit?: number; cursor?: string }) => {
    const qs = new URLSearchParams();
    if (params?.dataset_id) qs.set('dataset_id', params.dataset_id);
    if (params?.state) qs.set('state', params.state);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<DatasetBuildListItem>>(`/dataset-builds?${qs}`);
  },
};
