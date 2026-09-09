// ─── Pagination ────────────────────────────────────────────────────────────

export interface PageInfo {
  next_cursor: string | null;
}

export interface ListResponse<T> {
  data: T[];
  page: PageInfo;
}

export interface ApiError {
  code: string;
  message: string;
  detail?: unknown;
}

// ─── Health / System ───────────────────────────────────────────────────────

export type ServiceStatus = 'healthy' | 'degraded' | 'unknown';
export type RuntimeStatus = 'connected' | 'disconnected' | 'unknown';

export interface HealthResponse {
  backend: ServiceStatus;
  postgres: ServiceStatus;
  runtime_mcp: RuntimeStatus;
  dataset_manager: ServiceStatus;
  timestamp: string;
}

export interface FeatureFlags {
  attempt_websocket_stream: boolean;
  manual_checkpoint_request: boolean;
}

export interface CapabilitiesResponse {
  api_version: string;
  dtp_versions: number[];
  mcp_versions: number[];
  runtime_connected: boolean;
  runtime_instance_id: string | null;
  supported_training_strategies: string[];
  feature_flags: FeatureFlags;
}

// ─── Runtime Snapshot ──────────────────────────────────────────────────────

export interface RuntimeWorkerInfo {
  worker_id: number;
  session_id: string;
  node_label: string;
  state: string;
}

export interface RuntimeSnapshot {
  runtime_instance_id: string | null;
  active_job_id: string | null;
  active_attempt_id: string | null;
  attempt_state: string | null;
  training_strategy: string | null;
  epoch: number | null;
  model_version: number | null;
  workers: RuntimeWorkerInfo[];
  stale: boolean;
  observed_at: string | null;
  runtime_event_seq: number | null;
}

// ─── Dataset ───────────────────────────────────────────────────────────────

export interface DatasetItem {
  dataset_id: string;
  name: string;
  task_type: string;
  source_type: string;
  source_reference: string;
  created_at: string;
}

export interface DatasetDetail extends DatasetItem {
  build_counts?: {
    total: number;
    ready: number;
  };
}

export type DatasetBuildState =
  | 'CREATED'
  | 'QUEUED'
  | 'IMPORTING'
  | 'VALIDATING'
  | 'PREPROCESSING'
  | 'MATERIALIZING'
  | 'VERIFYING'
  | 'REGISTERING'
  | 'READY'
  | 'DEPRECATED'
  | 'DELETING'
  | 'DELETED'
  | 'FAILED';

export interface DatasetBuildListItem {
  dataset_build_id: string;
  dataset_id: string;
  state: DatasetBuildState;
  profile: string;
  batch_size: number;
  shard_count: number;
  sample_count: number | null;
  created_at: string;
  ready_at: string | null;
}

// ─── Job ───────────────────────────────────────────────────────────────────

export type JobState = 'DRAFT' | 'READY' | 'ARCHIVED';
export type AttemptState =
  | 'CREATED'
  | 'WAITING_WORKERS'
  | 'PROVISIONING'
  | 'INITIALIZING'
  | 'RUNNING'
  | 'COMPLETING'
  | 'COMPLETED'
  | 'FAILED'
  | 'ABORTED';
export type ExecutionMode = 'FRESH' | 'RETRY_FROM_START' | 'RESUME';

export interface RequestedContract {
  dataset_build_id: string;
  model_id: string;
  epochs: number;
  learning_rate: number;
  training_seed: number;
  training_strategy: string;
}

export interface LatestAttemptSummary {
  attempt_id: string | null;
  state: AttemptState | null;
}

export interface AttemptSummary {
  total: number;
  latest_attempt_id: string | null;
  latest_attempt_state: AttemptState | null;
}

export interface JobListItem {
  job_id: string;
  display_name: string;
  state: JobState;
  dataset_build_id: string | null;
  model_id: string | null;
  training_strategy: string | null;
  contract_hash: string | null;
  attempt_count: number;
  latest_attempt: LatestAttemptSummary | null;
  created_at: string;
  frozen_at: string | null;
}

export interface JobLinks {
  attempts: string;
}

export interface JobDetail {
  job_id: string;
  display_name: string;
  description: string;
  state: JobState;
  requested_contract: RequestedContract | null;
  resolved_contract: Record<string, unknown> | null;
  contract_hash: string | null;
  cloned_from_job_id: string | null;
  attempt_summary: AttemptSummary;
  links: JobLinks;
  created_at: string;
  frozen_at: string | null;
  archived_at: string | null;
}

export interface StartAttemptResponse {
  command_id: string;
  command_type: string;
  command_state: string;
  target_type: string;
  target_id: string;
  job_id: string;
  attempt_id: string;
  execution_mode: ExecutionMode;
  resume_from_checkpoint_id?: string | null;
}

// ─── Attempt ───────────────────────────────────────────────────────────────

export interface MembershipInfo {
  active_workers: number;
  expected_workers: number;
}

export interface AttemptListItem {
  attempt_id: string;
  job_id: string;
  state: AttemptState;
  execution_mode: ExecutionMode;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  failure_code: string | null;
}

export interface AttemptDetail {
  attempt_id: string;
  job_id: string;
  contract_hash: string;
  state: AttemptState;
  execution_mode: ExecutionMode;
  training_strategy: string | null;
  expected_workers: number | null;
  membership: MembershipInfo | null;
  epoch: number | null;
  progress_cursor: { epoch: number; next_batch_ordinal: number } | null;
  model_version: number | null;
  checkpoint: { state: CheckpointState; latest_checkpoint_id: string | null } | null;
  runtime: { stale: boolean; observed_at: string | null; runtime_event_seq: number | null } | null;
  strategy_state: Record<string, unknown> | null;
  failure: { code: string; message: string | null } | null;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface WorkerSessionItem {
  worker_id: number;
  session_id: string;
  node_label: string;
  state: string;
  protocol_version: number;
  connected_at: string;
  last_heartbeat_at: string | null;
  disconnected_at: string | null;
  failure_code: string | null;
}

export interface AttemptSnapshot {
  attempt_id: string;
  state: AttemptState;
  training_strategy: string | null;
  epoch: number | null;
  current_operation_id: number | null;
  model_version: number | null;
  workers: WorkerSessionItem[];
  stale: boolean;
  observed_at: string | null;
  runtime_event_seq: number | null;
}

// ─── Step ──────────────────────────────────────────────────────────────────

export interface StepListItem {
  step_id: number;
  operation_id: string;
  state: string;
  input_model_version: number;
  output_model_version: number | null;
  epoch: number;
  batch_ordinal: number;
  total_sample_count: number | null;
  committed_at: string | null;
}

// ─── Checkpoint ────────────────────────────────────────────────────────────

export interface CheckpointListItem {
  checkpoint_id: string;
  job_id: string;
  created_by_attempt_id: string;
  state: CheckpointState;
  model_version: number;
  source_step_id: number | null;
  created_at: string;
  completed_at: string | null;
}

export type CheckpointState = 'WRITING' | 'COMPLETE' | 'FAILED';

// ─── Event ─────────────────────────────────────────────────────────────────

export type EventSeverity = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface EventListItem {
  event_id?: string;
  attempt_id?: string;
  runtime_event_seq?: number;
  scope?: { type: string; id: string | null };
  event_type: string;
  severity: EventSeverity;
  source_component?: string;
  payload?: Record<string, unknown>;
  details?: Record<string, unknown>;
  occurred_at: string;
}

// ─── Command ───────────────────────────────────────────────────────────────

export interface CommandListItem {
  command_id: string;
  command_type: string;
  state: string;
  target_type: string;
  target_id: string | null;
  requested_at: string;
  dispatched_at: string | null;
  completed_at: string | null;
}

// ─── WebSocket messages ────────────────────────────────────────────────────

export type WsFrameKind = 'EVENT' | 'SNAPSHOT' | 'GAP' | 'PING' | 'PONG';

export interface CanonicalWsFrame<T = unknown> {
  kind: WsFrameKind;
  attempt_id?: string | null;
  runtime_event_seq?: number | null;
  occurred_at?: string | null;
  payload?: T;
}
