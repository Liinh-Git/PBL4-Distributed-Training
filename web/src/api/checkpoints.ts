import { api } from './client';
import type { CheckpointListItem, ListResponse } from '../domain/types';

export interface CheckpointDetail extends CheckpointListItem {
  contract_hash?: string;
  dataset_build_id?: string;
  dataset_manifest_hash?: string;
  parameter_manifest_hash?: string;
  source_operation_id: string;
  recovery_cursor?: {
    epoch: number;
    next_batch_ordinal: number;
  } | null;
  integrity?: {
    model_sha256: string;
    metadata_sha256?: string;
    artifact_size_bytes?: number;
  } | null;
}

export const checkpointsApi = {
  list: (params?: {
    attempt_id?: string;
    job_id?: string;
    state?: string;
    limit?: number;
    cursor?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params?.attempt_id) qs.set('attempt_id', params.attempt_id);
    if (params?.job_id) qs.set('job_id', params.job_id);
    if (params?.state) qs.set('state', params.state);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    return api.get<ListResponse<CheckpointListItem>>(`/checkpoints?${qs}`);
  },
  get: (checkpointId: string) => api.getItem<CheckpointDetail>(`/checkpoints/${checkpointId}`),
};
