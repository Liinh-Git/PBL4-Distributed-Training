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

// Alias for backwards compat
export type WorkerState = WorkerSessionState;

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

export type SubsystemStatus = 'HEALTHY' | 'DEGRADED' | 'DISCONNECTED';

export type EventSeverity = 'INFO' | 'WARN' | 'ERROR' | 'CRITICAL';

export interface SubsystemHealth {
  id: string;
  name: string;
  status: SubsystemStatus;
  latencyMs: number;
  lastHeartbeat: string;
  version: string;
  details: string;
}

export interface WorkerSession {
  workerId: number;
  sessionId: string;
  nodeLabel: string;
  protocolVersion: string;
  connectedAt: string;
  lastHeartbeatAt?: string;
  lastHeartbeatMs?: number;
  disconnectedAt?: string | null;
  failureCode?: string | null;
  // Shard & local model are OPTIONAL in public backend API
  shardId?: string | null;
  localModelVersion?: string | null;
  assignedShard?: string | null; // legacy alias
  currentModelVersion?: string | null; // legacy alias
  state: WorkerSessionState;
  historicalSessions?: string[];
  previousSessions?: string[]; // legacy alias
}

export interface WorkerContribution {
  workerId: number;
  sessionId: string;
  shardId?: string | null;
  batchId: string;
  sampleCount: number;
  samples?: number; // legacy alias
  contributionAccepted: boolean;
  parameterApplied: boolean;
  contribution?: string; // legacy alias
}

export interface StepTimings {
  startedAt: string;
  updateCompletedAt?: string | null;
  synchronizationCompletedAt?: string | null;
  checkpointCompletedAt?: string | null;
  committedAt?: string | null;
  totalDurationMs?: number; // derived (committedAt - startedAt)
  gradientCollectionMs?: number;
  aggregateMs?: number;
  optimizerUpdateMs?: number;
  broadcastMs?: number;
  parameterAppliedWaitMs?: number;
  checkpointMs?: number;
}

export interface TrainingStep {
  operationId: number;
  stepId?: number; // alias
  attemptId: string;
  trainingStrategy?: 'strict_bsp';
  state: StepState;
  epoch: number;
  batchOrdinal: number;
  inputModelVersion: string;
  outputModelVersion: string;
  totalSampleCount: number;
  timings: StepTimings;
  workerContributions: WorkerContribution[];
  loss?: number;
  accuracy?: number;
}

export interface DatasetShard {
  shardId: string;
  samples: number;
  sampleCount?: number;
  batches: number;
  manifestPath: string;
  storagePath?: string;
  hash: string;
  checksum?: string;
  sizeBytes: number;
  byteSizeMb?: number;
  partitionKey?: string;
}

export interface DatasetBuildManifest {
  schemaVersion: string;
  taskType: string;
  inputShape: string;
  dtype: string;
  numClasses: number;
  preprocessing: string;
  batchSize: number;
  shardCount: number;
  sampleCount: number;
  batchCountPerShard: number;
  datasetManifestHash: string;
}

export interface DatasetBuildManifestSummary {
  datasetManifestHash: string;
  manifestUri?: string;
  artifactBaseUrl?: string;
}

export interface DatasetBuild {
  id: string; // dataset_build_id
  datasetId: string;
  datasetName: string;
  state: DatasetBuildState;
  currentStage?: string;
  progress?: number;
  profile: string;
  batchSize: number;
  shardCount: number;
  partitionSeed?: number;
  sampleCount: number;
  totalSamples?: number;
  error?: string | null;
  createdAt: string;
  readyAt: string | null;
  manifestSummary?: DatasetBuildManifestSummary;
  // Aliases for compatibility
  datasetManifestHash?: string;
  manifestHash?: string;
  partitionStrategy?: string;
  inputShape?: string;
  sizeMb?: number;
  manifest?: DatasetBuildManifest;
  shards?: DatasetShard[];
  references?: {
    jobIds: string[];
    checkpointIds?: string[];
  };
}

export interface Dataset {
  id: string;
  name: string;
  task: string;
  source: string;
  buildCount: number;
  createdAt: string;
  description: string;
  license: string;
  modality: string;
  format?: string;
  totalSamples?: number;
  sizeMb?: number;
  latestBuildId?: string;
  builds: DatasetBuild[];
}

export interface RequestedContract {
  datasetBuildId: string;
  modelId: string;
  epochs: number;
  learningRate: number;
  trainingSeed: number;
  trainingStrategy: 'strict_bsp';
}

export interface ResolvedContract {
  dataset: {
    datasetBuildId: string;
    datasetManifestHash: string;
    inputShape: string;
    dtype: string;
    numClasses: number;
    batchSize: number;
    shardCount: number;
    preprocessing: string;
  };
  model: {
    modelId: string;
    modelProfile: string;
    parameterManifestHash: string;
    parameterCount: string;
  };
  training: {
    epochs: number;
    learningRate: number;
    seed: number;
    optimizer: string;
    weightDecay: number;
  };
  synchronization: {
    trainingStrategy: 'strict_bsp';
    expectedWorkers: number;
    barrierTimeoutMs: number;
  };
  durability: {
    checkpointPolicy: string;
    retentionCount: number;
  };
  protocol: {
    dtpVersion: string;
    mcpVersion: string;
  };
  contractHash: string;
}

export interface Attempt {
  id: string;
  jobId: string;
  jobName: string;
  datasetBuildId?: string;
  executionMode: 'FRESH' | 'RESUME' | 'RETRY_FROM_START';
  state: AttemptState;
  startedAt: string;
  endedAt: string | null;
  failureReason: string | null;
  latestCheckpointId: string;
  epoch: number;
  totalEpochs: number;
  currentBatch: number;
  totalBatches: number;
  modelVersion: string;
  expectedWorkers: number;
  activeWorkers: number;
  runtimeEventSeq: number;
  strategy: 'strict_bsp';
  elapsedFormatted: string;
  barrierWaitMs: number;
}

export interface Job {
  id: string;
  name: string;
  jobState: JobState;
  datasetBuildId: string;
  datasetName: string;
  modelId: string;
  strategy: 'strict_bsp';
  attemptsCount: number;
  latestAttemptId: string;
  latestAttemptState: AttemptState;
  createdAt: string;
  frozenAt: string | null;
  requestedContract: RequestedContract;
  resolvedContract: ResolvedContract;
  attempts: Attempt[];
}

export interface Checkpoint {
  id: string;
  state: CheckpointState;
  jobId: string;
  jobName: string;
  attemptId: string;
  modelVersion: string;
  sourceStepId: number;
  createdAt: string;
  sizeMb: number;
  recovery: {
    modelVersion: string;
    epoch: number;
    nextBatchOrdinal: number;
  };
  lineage: {
    jobId: string;
    createdByAttempt: string;
    sourceStep: number;
    datasetBuildId: string;
  };
  integrity: {
    contractHash: string;
    manifestHash: string;
    modelSha256: string;
    artifactSizeBytes: number;
  };
}

export interface DiagnosticEvent {
  id: string;
  time: string;
  severity: EventSeverity;
  event: string;
  scope: string;
  runtimeSeq: number;
  source: string;
  attemptId: string;
  payload: Record<string, any>;
  technicalCorrelationId: string;
}

export interface SystemCapabilities {
  apiVersion: string;
  dtpVersions: string[];
  mcpVersions: string[];
  supportedTrainingStrategies: string[];
  webSocketEnabled: boolean;
  manualCheckpointFeatureFlag: boolean;
}

export interface RuntimeSnapshot {
  runtimeInstance: string;
  activeJobId: string;
  activeJobName: string;
  activeAttemptId: string;
  attemptState: AttemptState;
  trainingStrategy: 'strict_bsp';
  epoch: number;
  totalEpochs: number;
  batch: number;
  totalBatches: number;
  modelVersion: string;
  runtimeEventSeq: number;
  observedAt: string;
  isStale: boolean;
  staleObservedAt?: string;
  workersConnected: number;
  expectedWorkers: number;
}
