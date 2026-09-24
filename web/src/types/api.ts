/**
 * API Contract Strict TypeScript Definitions
 *
 * Source of Truth: API_contract.md
 * Wire format representation for all 40 REST endpoints and WebSocket stream frames.
 */

// ─── Enums & Domain Literals ──────────────────────────────────────────────────

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

export type CheckpointState = 'WRITING' | 'COMPLETE' | 'FAILED';

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
  | 'FAILED'
  | 'DEPRECATED'
  | 'DELETING'
  | 'DELETED';

export type WorkerSessionState =
  | 'CONNECTING'
  | 'REGISTERING'
  | 'PROVISIONING'
  | 'SHARD_READY'
  | 'MODEL_SYNCING'
  | 'READY'
  | 'DISCONNECTED'
  | 'FAILED';

export type StepState =
  | 'CREATED'
  | 'DISPATCHED'
  | 'COLLECTING_GRADIENTS'
  | 'AGGREGATING'
  | 'UPDATING'
  | 'BROADCASTING'
  | 'WAITING_PARAMETER_APPLIED'
  | 'CHECKPOINTING'
  | 'COMMITTED';

export type CommandType =
  | 'CREATE_DATASET_BUILD'
  | 'REBUILD_DATASET_BUILD'
  | 'DELETE_DATASET_BUILD'
  | 'START_ATTEMPT'
  | 'ABORT_ATTEMPT'
  | 'REQUEST_CHECKPOINT'
  | string;

export type CommandState =
  | 'PENDING'
  | 'ACCEPTED'
  | 'DEFERRED'
  | 'SUCCEEDED'
  | 'REJECTED'
  | 'FAILED';

export type TargetType = 'DATASET_BUILD' | 'ATTEMPT' | string;

export type ScopeType =
  | 'SYSTEM'
  | 'DATASET_BUILD'
  | 'JOB'
  | 'ATTEMPT'
  | 'CHECKPOINT'
  | 'COMMAND'
  | string;

export type EventSeverity = 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export type TrainingStrategy = 'strict_bsp' | string;

// ─── Response Envelopes & Pagination ─────────────────────────────────────────

export interface ResponseMeta {
  request_id?: string;
  [key: string]: any;
}

export interface PageInfo {
  next_cursor: string | null;
}

export interface ApiResponse<T> {
  data: T;
  meta?: ResponseMeta;
}

export interface PaginatedResponse<T> {
  data: T[];
  page: PageInfo;
  meta?: ResponseMeta;
}

export interface ApiErrorDetail {
  code: string;
  message: string;
  details?: Record<string, any> | null;
  request_id?: string;
  command_id?: string | null;
}

export interface ApiErrorResponse {
  error: ApiErrorDetail;
}

// ─── 1.0 & 2.0 System & Capabilities ─────────────────────────────────────────

export interface HealthData {
  backend: string;
  postgres: string;
  runtime_mcp: string;
  dataset_manager: string;
  timestamp: string;
}

export interface FeatureFlagData {
  attempt_websocket_stream?: boolean;
  manual_checkpoint_request?: boolean;
  [key: string]: boolean | undefined;
}

export interface SupportedModelData {
  model_id: string;
  display_name: string;
  task_type: string;
}

export interface CapabilitiesData {
  api_version: string;
  dtp_versions: number[];
  mcp_versions: number[];
  runtime_connected: boolean;
  runtime_instance_id: string | null;
  supported_training_strategies: string[];
  feature_flags: FeatureFlagData;
  supported_models?: SupportedModelData[];
}

// ─── 3.0 Runtime Snapshot ────────────────────────────────────────────────────

export interface RecoveryCursorData {
  epoch: number;
  next_batch_ordinal: number;
}

export interface StrategyStateStrictBSPData {
  type: 'strict_bsp';
  current_step_id?: number | null;
  state?: string | null;
  accepted_contribution_count?: number | null;
  expected_contribution_count?: number | null;
  parameter_applied_count?: number | null;
  barrier_wait_ms?: number | null;
  synchronization_complete?: boolean | null;
}

export interface RuntimeSnapshotWorkerData {
  worker_id: number;
  session_id: string;
  node_label?: string;
  state: WorkerSessionState | string;
  local_model_version?: number | null;
}

export interface RuntimeSnapshotData {
  runtime_instance_id?: string | null;
  active_job_id?: string | null;
  active_attempt_id?: string | null;
  attempt_state?: AttemptState | null;
  training_strategy?: TrainingStrategy | null;
  checkpoint_policy?: string | null;
  epoch?: number | null;
  current_operation_id?: number | null;
  current_batch_ordinal?: number | null;
  model_version?: number | null;
  workers: RuntimeSnapshotWorkerData[];
  strategy_state?: StrategyStateStrictBSPData | null;
  checkpoint_state?: CheckpointState | string | null;
  latest_checkpoint_id?: string | null;
  recovery_cursor?: RecoveryCursorData | null;
  dataset_build_id?: string | null;
  dataset_manifest_hash?: string | null;
  management_event_gap_count?: number;
  stale: boolean;
  observed_at?: string | null;
  runtime_event_seq?: number | null;
}

// ─── 4.0 - 12.0 Dataset & Dataset Build ──────────────────────────────────────

export interface DatasetSourceV1 {
  name: string;
  task_type: 'image_classification';
  source_type: 'builtin';
  source_reference: 'cifar10';
}

export interface DatasetItemData {
  dataset_id: string;
  name: string;
  task_type: string;
  source_type: string;
  source_reference: string;
  created_at: string;
}

export interface BuildCountsData {
  CREATED: number;
  QUEUED: number;
  IMPORTING: number;
  VALIDATING: number;
  PREPROCESSING: number;
  MATERIALIZING: number;
  VERIFYING: number;
  REGISTERING: number;
  READY: number;
  FAILED: number;
  DEPRECATED: number;
  DELETING: number;
  DELETED: number;
}

export interface DatasetDetailData extends DatasetItemData {
  build_counts: BuildCountsData;
}

export interface PreprocessingNormalizationConfig {
  mean: number[];
  std: number[];
}

export interface PreprocessingConfigData {
  input_shape?: number[];
  normalization?: PreprocessingNormalizationConfig;
}

export interface DatasetBuildCreateV1 {
  dataset_id: string;
  profile: 'CNN_IMAGE_CLASSIFICATION_V1' | string;
  batch_size: number;
  partition_seed: number;
  preprocessing?: PreprocessingConfigData;
}

export interface DatasetBuildRebuildV1 {
  batch_size?: number;
  partition_seed?: number;
  preprocessing?: PreprocessingConfigData;
}

export interface DatasetBuildDeprecateV1 {
  reason?: string;
}

export interface DatasetBuildDeleteV1 {
  reason?: string;
}

export interface ManifestSummaryData {
  dataset_manifest_hash: string;
  manifest_uri: string;
  artifact_base_url: string;
}

export interface BuildReferenceData {
  type: 'JOB' | 'CHECKPOINT' | string;
  id: string;
}

export interface DatasetBuildListItemData {
  dataset_build_id: string;
  dataset_id: string;
  state: DatasetBuildState;
  profile: string;
  batch_size: number;
  shard_count: number;
  sample_count?: number | null;
  created_at: string;
  ready_at?: string | null;
}

export interface DatasetBuildDetailData {
  dataset_build_id: string;
  dataset_id: string;
  state: DatasetBuildState;
  current_stage?: string | null;
  progress?: number | null;
  profile: string;
  batch_size: number;
  shard_count: number;
  partition_seed: number;
  sample_count?: number | null;
  manifest_summary?: ManifestSummaryData | null;
  references: BuildReferenceData[];
  error?: string | null;
  created_at: string;
  ready_at?: string | null;
}

export interface BuildCommandData {
  command_id: string;
  command_type: CommandType;
  command_state: CommandState;
  target_type: 'DATASET_BUILD';
  target_id: string;
  dataset_build_id: string;
  dataset_build_state: DatasetBuildState;
  source_dataset_build_id?: string | null;
  new_dataset_build_id?: string | null;
}

export interface DatasetBuildDeprecateResponseData {
  dataset_build_id: string;
  state: 'DEPRECATED';
  deprecated_at: string;
}

// ─── 13.0 - 19.0 Job Management ──────────────────────────────────────────────

export interface RequestedContractV1 {
  dataset_build_id: string;
  model_id: string;
  epochs: number;
  learning_rate: number;
  training_seed: number;
  training_strategy: 'strict_bsp';
}

export interface RequestedContractPatchV1 {
  dataset_build_id?: string;
  model_id?: string;
  epochs?: number;
  learning_rate?: number;
  training_seed?: number;
  training_strategy?: 'strict_bsp';
}

export interface ResolvedDatasetData {
  dataset_build_id: string;
  dataset_manifest_hash: string;
  task_type: string;
  input_shape: number[];
  dtype: string;
  num_classes: number;
  batch_size: number;
  shard_count: number;
  preprocessing: Record<string, any>;
}

export interface ResolvedModelData {
  model_id: string;
  profile: string;
  parameter_manifest_hash: string;
}

export interface ResolvedTrainingData {
  epochs: number;
  learning_rate: number;
  training_seed: number;
}

export interface ResolvedSynchronizationData {
  training_strategy: 'strict_bsp' | string;
  expected_workers: number;
}

export interface ResolvedUpdatePolicyData {
  type: string;
}

export interface ResolvedCheckpointPolicyData {
  type: string;
  schema_version: number;
}

export interface ResolvedProtocolsData {
  dtp_version: number;
  mcp_version: number;
}

export interface ResolvedContractV1 {
  dataset: ResolvedDatasetData;
  model: ResolvedModelData;
  training: ResolvedTrainingData;
  synchronization: ResolvedSynchronizationData;
  update_policy: ResolvedUpdatePolicyData;
  checkpoint_policy: ResolvedCheckpointPolicyData;
  protocols: ResolvedProtocolsData;
}

export interface JobCreateRequest {
  display_name: string;
  description?: string;
  requested_contract: RequestedContractV1;
}

export interface JobPatchRequest {
  display_name?: string;
  description?: string;
  requested_contract?: RequestedContractPatchV1;
}

export interface LatestAttemptSummaryData {
  attempt_id: string;
  state: AttemptState;
}

export interface JobListItemData {
  job_id: string;
  display_name: string;
  state: JobState;
  dataset_build_id?: string | null;
  model_id?: string | null;
  training_strategy?: string | null;
  contract_hash?: string | null;
  attempt_count: number;
  latest_attempt?: LatestAttemptSummaryData | null;
  created_at: string;
  frozen_at?: string | null;
}

export interface AttemptSummaryData {
  total: number;
  latest_attempt_id?: string | null;
  latest_attempt_state?: AttemptState | null;
}

export interface JobLinksData {
  attempts: string;
}

export interface JobDetailData {
  job_id: string;
  display_name: string;
  description: string;
  state: JobState;
  requested_contract: RequestedContractV1;
  resolved_contract?: ResolvedContractV1 | null;
  contract_hash?: string | null;
  cloned_from_job_id?: string | null;
  attempt_summary?: AttemptSummaryData | null;
  links?: JobLinksData | null;
  created_at: string;
  frozen_at?: string | null;
  archived_at?: string | null;
}

export interface JobValidateResponseData {
  requested_contract: RequestedContractV1;
  resolved_preview?: ResolvedContractV1 | null;
  warnings: string[];
  errors: string[];
}

export interface JobCloneResponseData {
  job_id: string;
  state: 'DRAFT';
  cloned_from_job_id: string;
  display_name: string;
  description: string;
  requested_contract: RequestedContractV1;
  resolved_contract: null;
  contract_hash: null;
}

export interface JobArchiveResponseData {
  job_id: string;
  state: 'ARCHIVED';
  archived_at: string;
}

// ─── 20.0 - 25.0 Training / Attempt Lifecycle ────────────────────────────────

export interface JobStartRequest {
  note?: string;
}

export interface JobResumeRequest {
  checkpoint_id: string;
}

export interface StartAttemptResponseData {
  command_id: string;
  command_type: 'START_ATTEMPT';
  command_state: CommandState;
  target_type: 'ATTEMPT';
  target_id: string;
  job_id: string;
  attempt_id: string;
  execution_mode: ExecutionMode;
  resume_from_checkpoint_id?: string | null;
}

export interface AttemptListItemData {
  attempt_id: string;
  job_id: string;
  state: AttemptState;
  execution_mode: ExecutionMode;
  training_strategy?: string | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
  failure_code?: string | null;
}

export interface MembershipData {
  active_workers: number;
  expected_workers: number;
}

export interface ProgressCursorData {
  epoch: number;
  next_batch_ordinal: number;
}

export interface CheckpointRefData {
  state: CheckpointState | string;
  latest_checkpoint_id?: string | null;
}

export interface RuntimeInfoData {
  stale: boolean;
  observed_at?: string | null;
  runtime_event_seq?: number | null;
}

export interface FailureInfoData {
  code: string;
  message?: string | null;
}

export interface AttemptLinksData {
  job: string;
  workers: string;
  steps: string;
  events: string;
}

export interface AttemptDetailData {
  attempt_id: string;
  job_id: string;
  contract_hash: string;
  state: AttemptState;
  execution_mode: ExecutionMode;
  training_strategy?: TrainingStrategy | null;
  expected_workers?: number | null;
  membership?: MembershipData | null;
  epoch?: number | null;
  progress_cursor?: ProgressCursorData | null;
  model_version?: number | null;
  checkpoint?: CheckpointRefData | null;
  runtime?: RuntimeInfoData | null;
  strategy_state?: StrategyStateStrictBSPData | null;
  failure?: FailureInfoData | null;
  links?: AttemptLinksData | null;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface AbortAttemptRequest {
  reason?: string;
}

export interface AbortAttemptResponseData {
  command_id: string;
  command_type: 'ABORT_ATTEMPT';
  command_state: CommandState;
  target_type: 'ATTEMPT';
  target_id: string;
  attempt_id: string;
}

// ─── 26.0 - 29.0 Worker Bootstrap & Runtime Observation ──────────────────────

export interface JoinSpecProtocolData {
  dtp_version: number;
}

export interface JoinSpecData {
  ps_host: string;
  ps_port: number;
  job_id: string;
  attempt_id: string;
  contract_hash: string;
  protocol: JoinSpecProtocolData;
  expires_at?: string | null;
  expected_workers?: number;
}

export interface WorkerSessionItemData {
  worker_id: number;
  session_id: string;
  node_label: string;
  state: WorkerSessionState | string;
  shard_id?: number | null;
  local_model_version?: number | null;
  protocol_version: number;
  connected_at: string;
  last_heartbeat_at?: string | null;
  disconnected_at?: string | null;
  failure_code?: string | null;
}

export interface AttemptSnapshotData {
  attempt_id: string;
  state: AttemptState;
  training_strategy?: TrainingStrategy | null;
  epoch?: number | null;
  current_operation_id?: number | null;
  current_batch_ordinal?: number | null;
  model_version?: number | null;
  workers: WorkerSessionItemData[];
  strategy_state?: StrategyStateStrictBSPData | null;
  checkpoint_state?: CheckpointState | string | null;
  latest_checkpoint_id?: string | null;
  stale: boolean;
  observed_at?: string | null;
  runtime_event_seq?: number | null;
}

export interface WorkerDetailData {
  worker_id: number;
  active_session?: WorkerSessionItemData | null;
  historical_sessions: WorkerSessionItemData[];
}

// ─── 30.0 - 31.0 Strict BSP Steps ────────────────────────────────────────────

export interface StepListItemData {
  step_id: number;
  operation_id: number;
  state: StepState;
  input_model_version: number;
  output_model_version?: number | null;
  epoch: number;
  batch_ordinal: number;
  total_sample_count?: number | null;
  committed_at?: string | null;
}

export interface StepTimingData {
  started_at: string;
  update_completed_at?: string | null;
  synchronization_completed_at?: string | null;
  checkpoint_completed_at?: string | null;
  committed_at?: string | null;
}

export interface StepMetricsData {
  loss?: number | null;
  accuracy?: number | null;
  [key: string]: any;
}

export interface WorkerStepData {
  worker_id: number;
  session_id: string;
  shard_id?: number | null;
  batch_id?: number | string | null;
  sample_count: number;
  contribution_accepted?: boolean;
  parameter_applied?: boolean;
  loss?: number | null;
  accuracy?: number | null;
  compute_ms?: number | null;
  upload_ms?: number | null;
  parameter_apply_ms?: number | null;
  bytes_sent?: number | null;
  bytes_received?: number | null;
}

export interface StepDetailData {
  training_strategy: 'strict_bsp' | string;
  step_id: number;
  operation_id: number;
  input_model_version: number;
  output_model_version?: number | null;
  state: StepState;
  epoch: number;
  batch_ordinal: number;
  total_sample_count?: number | null;
  timing?: StepTimingData | null;
  metrics?: StepMetricsData | null;
  worker_steps: WorkerStepData[];
}

// ─── 32.0 - 34.0 Checkpoints ─────────────────────────────────────────────────

export interface CheckpointListItemData {
  checkpoint_id: string;
  job_id: string;
  created_by_attempt_id: string;
  state: CheckpointState;
  model_version: number;
  source_step_id?: number | null;
  created_at: string;
  completed_at?: string | null;
}

export interface CheckpointIntegrityData {
  model_sha256?: string | null;
  metadata_sha256?: string | null;
  artifact_size_bytes?: number | null;
}

export interface CheckpointDetailData {
  checkpoint_id: string;
  state: CheckpointState;
  job_id: string;
  created_by_attempt_id: string;
  contract_hash?: string | null;
  dataset_build_id?: string | null;
  dataset_manifest_hash?: string | null;
  parameter_manifest_hash?: string | null;
  training_strategy?: string | null;
  source_operation_id?: number | null;
  source_step_id?: number | null;
  model_version: number;
  recovery_cursor?: RecoveryCursorData | null;
  integrity?: CheckpointIntegrityData | null;
  created_at: string;
  completed_at?: string | null;
}

export interface CheckpointRequestBody {
  reason?: string;
}

export interface CheckpointRequestResponseData {
  command_id: string;
  command_type: 'REQUEST_CHECKPOINT';
  command_state: CommandState;
  target_type: 'ATTEMPT';
  target_id: string;
  attempt_id: string;
}

// ─── 35.0 - 38.0 Audit Events & Commands ─────────────────────────────────────

export interface RuntimeEventItemData {
  attempt_id: string;
  job_id?: string | null;
  runtime_event_seq: number;
  event_type: string;
  event_schema_version?: number;
  occurred_at: string;
  source_component: string;
  severity: EventSeverity;
  details: Record<string, any>;
}

export interface RuntimeEventsMeta {
  complete: boolean;
  gap_detected: boolean;
  snapshot_required: boolean;
}

export interface RuntimeEventsResponseData {
  data: RuntimeEventItemData[];
  meta: RuntimeEventsMeta;
}

export interface ScopeRefData {
  type: ScopeType;
  id?: string | null;
}

export interface EventListItemData {
  event_id: string;
  scope: ScopeRefData;
  event_type: string;
  severity: EventSeverity;
  occurred_at: string;
  summary?: string | null;
}

export interface CommandResultData {
  code: string;
  message?: string | null;
}

export interface CommandListItemData {
  command_id: string;
  command_type: CommandType;
  state: CommandState;
  target_type: TargetType;
  target_id?: string | null;
  requested_at: string;
  dispatched_at?: string | null;
  completed_at?: string | null;
}

export interface CommandDetailData {
  command_id: string;
  command_type: CommandType;
  state: CommandState;
  target_type: TargetType;
  target_id?: string | null;
  request?: Record<string, any>;
  result?: CommandResultData | null;
  requested_at: string;
  dispatched_at?: string | null;
  completed_at?: string | null;
}

// ─── 39.0 WebSocket Stream Frames ────────────────────────────────────────────

export interface WsEventFrameData {
  kind: 'EVENT';
  attempt_id: string;
  runtime_event_seq: number;
  occurred_at: string;
  payload: {
    event_type: string;
    event_schema_version?: number;
    source_component: string;
    severity: EventSeverity;
    details?: Record<string, any>;
    [key: string]: any;
  };
}

export interface WsSnapshotFrameData {
  kind: 'SNAPSHOT';
  attempt_id: string;
  runtime_event_seq: number | null;
  occurred_at: string;
  payload: {
    snapshot_seq?: number | null;
    state?: any;
    [key: string]: any;
  };
}

export interface WsGapFrameData {
  kind: 'GAP';
  attempt_id: string;
  runtime_event_seq: null;
  occurred_at: string;
  payload: {
    snapshot_required: boolean;
    after_seq?: number | null;
    authoritative_seq?: number | null;
    reason?: string;
    [key: string]: any;
  };
}

export type WsFrameData = WsEventFrameData | WsSnapshotFrameData | WsGapFrameData;

// ─── 40.0 Training Metrics Time-Series ───────────────────────────────────────

export interface MetricItemData {
  metric_id: string;
  attempt_id: string;
  worker_id?: number | null;
  step_id: number;
  operation_id?: number | null;
  name: string;
  value: number;
  unit?: string | null;
  labels?: Record<string, string>;
  observed_at: string;
}

export type MetricsQueryResponseData = PaginatedResponse<MetricItemData>;
