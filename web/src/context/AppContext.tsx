import React, { createContext, useContext, useState, useEffect } from 'react';
import {
  Job,
  Dataset,
  DatasetBuild,
  Attempt,
  TrainingStep,
  Checkpoint,
  DiagnosticEvent,
  SubsystemHealth,
  WorkerSession,
  RuntimeSnapshot,
} from '../types';
import {
  INITIAL_JOBS,
  INITIAL_DATASETS,
  INITIAL_DATASET_BUILDS,
  INITIAL_CHECKPOINTS,
  INITIAL_STEPS_LIST,
  INITIAL_DIAGNOSTIC_EVENTS,
  INITIAL_SUBSYSTEMS,
  INITIAL_CAPABILITIES,
  INITIAL_WORKERS,
  INITIAL_RUNTIME_SNAPSHOT,
  CURRENT_ATTEMPT,
} from '../mock/data';

interface AppContextType {
  jobs: Job[];
  attempts: Attempt[];
  datasets: Dataset[];
  datasetBuilds: DatasetBuild[];
  checkpoints: Checkpoint[];
  steps: TrainingStep[];
  events: DiagnosticEvent[];
  subsystems: SubsystemHealth[];
  workers: WorkerSession[];
  currentAttempt: Attempt;
  runtimeSnapshot: RuntimeSnapshot;
  isRuntimeStale: boolean;
  hasEventHistoryGap: boolean;
  selectedWorker: WorkerSession | null;
  selectedStep: TrainingStep | null;
  selectedEvent: DiagnosticEvent | null;
  selectedCheckpoint: Checkpoint | null;
  selectedDatasetBuild: DatasetBuild | null;
  rawContractModalJob: Job | null;

  // Actions
  toggleRuntimeStale: () => void;
  toggleEventHistoryGap: () => void;
  setSelectedWorker: (worker: WorkerSession | null) => void;
  setSelectedStep: (step: TrainingStep | null) => void;
  setSelectedEvent: (event: DiagnosticEvent | null) => void;
  setSelectedCheckpoint: (checkpoint: Checkpoint | null) => void;
  setSelectedDatasetBuild: (build: DatasetBuild | null) => void;
  setRawContractModalJob: (job: Job | null) => void;
  createJob: (newJob: Job) => Job;
  archiveJob: (jobId: string) => void;
  deprecateBuild: (buildId: string) => void;
  purgeBuild: (buildId: string) => { success: boolean; error?: string };
  purgeDatasetBuild: (buildId: string) => { success: boolean; error?: string };
  triggerDatasetBuild: (datasetId: string, strategy?: 'HASH' | 'RANGE' | 'ROUND_ROBIN', shardsCount?: number) => DatasetBuild;
  resumeFromCheckpoint: (checkpointId: string) => void;
  abortAttempt: (attemptId: string) => void;
  requestCheckpoint: () => void;
  cloneJob: (jobId: string) => void;
  startJobFresh: (jobId: string) => void;
  simulateStepAdvance: () => void;
  isSimulating: boolean;
  setIsSimulating: React.Dispatch<React.SetStateAction<boolean>>;
}

const AppContext = createContext<AppContextType | undefined>(undefined);

let globalEventSequence = 20000;
const generateUniqueEventId = () => {
  globalEventSequence += 1;
  return `evt_${Date.now()}_${globalEventSequence}_${Math.random().toString(36).slice(2, 6)}`;
};

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [jobs, setJobs] = useState<Job[]>(INITIAL_JOBS);
  const [datasets] = useState<Dataset[]>(INITIAL_DATASETS);
  const [datasetBuilds, setDatasetBuilds] = useState<DatasetBuild[]>(INITIAL_DATASET_BUILDS);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>(INITIAL_CHECKPOINTS);
  const [steps, setSteps] = useState<TrainingStep[]>(INITIAL_STEPS_LIST);
  const [events, setEvents] = useState<DiagnosticEvent[]>(INITIAL_DIAGNOSTIC_EVENTS);
  const [subsystems, setSubsystems] = useState<SubsystemHealth[]>(INITIAL_SUBSYSTEMS);
  const [workers, setWorkers] = useState<WorkerSession[]>(INITIAL_WORKERS);
  const [currentAttempt, setCurrentAttempt] = useState<Attempt>(CURRENT_ATTEMPT);
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<RuntimeSnapshot>(INITIAL_RUNTIME_SNAPSHOT);
  const [isRuntimeStale, setIsRuntimeStale] = useState<boolean>(false);
  const [hasEventHistoryGap, setHasEventHistoryGap] = useState<boolean>(false);

  // Safe helper to append events without duplicate IDs
  const addEvent = (newEvent: DiagnosticEvent) => {
    setEvents(prev => {
      if (prev.some(e => e.id === newEvent.id)) {
        return prev;
      }
      return [newEvent, ...prev];
    });
  };

  // Memoized attempts collection across all jobs
  const attempts = React.useMemo(() => {
    return jobs.flatMap(j => j.attempts || []);
  }, [jobs]);

  // Inspector drawers
  const [selectedWorker, setSelectedWorker] = useState<WorkerSession | null>(null);
  const [selectedStep, setSelectedStep] = useState<TrainingStep | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<DiagnosticEvent | null>(null);
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null);
  const [selectedDatasetBuild, setSelectedDatasetBuild] = useState<DatasetBuild | null>(null);
  const [rawContractModalJob, setRawContractModalJob] = useState<Job | null>(null);

  // Simulation state (deprecated, disabled in Phase 5 in favor of WebSocket stream)
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const simPhaseRef = React.useRef<number>(0);


  const toggleRuntimeStale = () => {
    setIsRuntimeStale(prev => {
      const next = !prev;
      setRuntimeSnapshot(snap => ({
        ...snap,
        isStale: next,
        staleObservedAt: next ? '10:42:03 (stale snapshot)' : undefined,
      }));
      setSubsystems(subs =>
        subs.map(s =>
          s.id === 'sub_mcp'
            ? { ...s, status: next ? 'DEGRADED' : 'HEALTHY', details: next ? 'Connection heartbeat lost at 10:42:03' : 'Streaming protocol connected to Local Cluster node 1..3' }
            : s
        )
      );
      return next;
    });
  };

  const toggleEventHistoryGap = () => {
    setHasEventHistoryGap(prev => !prev);
  };

  const createJob = (newJob: Job): Job => {
    setJobs(prev => [newJob, ...prev]);
    return newJob;
  };

  const archiveJob = (jobId: string) => {
    setJobs(prev =>
      prev.map(j => (j.id === jobId ? { ...j, jobState: 'ARCHIVED' } : j))
    );
  };

  const deprecateBuild = (buildId: string) => {
    setDatasetBuilds(prev =>
      prev.map(b => (b.id === buildId ? { ...b, state: 'DEPRECATED' } : b))
    );
  };

  const purgeBuild = (buildId: string): { success: boolean; error?: string } => {
    const build = datasetBuilds.find(b => b.id === buildId);
    if (!build) return { success: false, error: 'Build not found' };
    const jobRefs = build.references?.jobIds?.length ?? 0;
    const ckptRefs = build.references?.checkpointIds?.length ?? 0;
    if (jobRefs > 0 || ckptRefs > 0) {
      return {
        success: false,
        error: `Cannot purge build ${buildId}: It is referenced by ${jobRefs} Job(s) and ${ckptRefs} Checkpoint(s).`,
      };
    }
    setDatasetBuilds(prev => prev.filter(b => b.id !== buildId));
    return { success: true };
  };

  const purgeDatasetBuild = (buildId: string): { success: boolean; error?: string } => {
    return purgeBuild(buildId);
  };

  const triggerDatasetBuild = (
    datasetId: string,
    strategy: 'HASH' | 'RANGE' | 'ROUND_ROBIN' = 'HASH',
    shardsCount: number = 3
  ): DatasetBuild => {
    const ds = datasets.find(d => d.id === datasetId);
    const buildCount = (ds?.builds?.length ?? 0) + 1;
    const shortId = datasetId.replace('ds_', '');
    const newId = `build_${shortId}_v${buildCount}`;
    const totalSamples = ds?.totalSamples ?? 50000;
    const samplesPerShard = Math.floor(totalSamples / shardsCount);

    const newShards = Array.from({ length: shardsCount }).map((_, i) => ({
      shardId: `shard-${String(i).padStart(2, '0')}`,
      samples: i === shardsCount - 1 ? totalSamples - samplesPerShard * (shardsCount - 1) : samplesPerShard,
      sampleCount: i === shardsCount - 1 ? totalSamples - samplesPerShard * (shardsCount - 1) : samplesPerShard,
      batches: Math.floor(samplesPerShard / 64),
      manifestPath: `/shards/${shortId}/${newId}/shard_${String(i).padStart(2, '0')}.mpack`,
      storagePath: `/shards/${shortId}/${newId}/shard_${String(i).padStart(2, '0')}.mpack`,
      hash: `sha256:${Math.random().toString(16).slice(2, 10)}...`,
      checksum: `sha256:${Math.random().toString(16).slice(2, 18)}...`,
      sizeBytes: Math.round(samplesPerShard * 3500),
      byteSizeMb: Math.round((samplesPerShard * 3500) / (1024 * 1024)) || 175,
      partitionKey: `${strategy.toLowerCase()}_mod_${shardsCount}`,
    }));

    const newBuild: DatasetBuild = {
      id: newId,
      datasetId,
      datasetName: ds?.name ?? datasetId,
      state: 'READY',
      profile: `${ds?.modality?.toLowerCase() ?? 'vision'}-${strategy.toLowerCase()}-fp32`,
      partitionStrategy: strategy,
      inputShape: ds?.modality === 'NLP' ? '[512]' : '[3, 32, 32]',
      batchSize: 64,
      shardCount: shardsCount,
      sampleCount: totalSamples,
      totalSamples: totalSamples,
      datasetManifestHash: `0x${Math.random().toString(16).slice(2, 10)}${Math.random().toString(16).slice(2, 10)}`,
      manifestHash: `0x${Math.random().toString(16).slice(2, 10)}${Math.random().toString(16).slice(2, 10)}`,
      sizeMb: Math.round((totalSamples * 3500) / (1024 * 1024)) || 524,
      createdAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      readyAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      manifest: {
        schemaVersion: 'ds-manifest/v2.1',
        taskType: ds?.task ?? 'IMAGE_CLASSIFICATION',
        inputShape: ds?.modality === 'NLP' ? '[512]' : '[3, 32, 32]',
        dtype: 'FLOAT32',
        numClasses: 10,
        preprocessing: 'Standardized normalizer + deterministic sharder',
        batchSize: 64,
        shardCount: shardsCount,
        sampleCount: totalSamples,
        batchCountPerShard: Math.floor(samplesPerShard / 64),
        datasetManifestHash: `0x${Math.random().toString(16).slice(2, 10)}${Math.random().toString(16).slice(2, 10)}`,
      },
      shards: newShards,
      references: {
        jobIds: [],
        checkpointIds: [],
      },
    };

    setDatasetBuilds(prev => [newBuild, ...prev]);
    return newBuild;
  };

  const resumeFromCheckpoint = (checkpointId: string) => {
    const ckpt = checkpoints.find(c => c.id === checkpointId);
    if (!ckpt) return;
    setIsSimulating(true);
    const newAttemptId = `attempt_${Date.now().toString(36).toUpperCase()}`;
    const resumedAttempt: Attempt = {
      ...currentAttempt,
      id: newAttemptId,
      executionMode: 'RESUME',
      state: 'RUNNING',
      startedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      latestCheckpointId: ckpt.id,
      epoch: ckpt.recovery.epoch,
      currentBatch: ckpt.recovery.nextBatchOrdinal,
      modelVersion: ckpt.recovery.modelVersion,
    };
    setCurrentAttempt(resumedAttempt);
    setJobs(prev =>
      prev.map(j =>
        j.id === ckpt.jobId
          ? {
              ...j,
              latestAttemptId: newAttemptId,
              latestAttemptState: 'RUNNING',
              attemptsCount: j.attemptsCount + 1,
              attempts: [resumedAttempt, ...j.attempts],
            }
          : j
      )
    );
  };

  const abortAttempt = (attemptId: string) => {
    const timeStr = new Date().toTimeString().slice(0, 8);
    setIsSimulating(false);
    setCurrentAttempt(prev => ({
      ...prev,
      state: 'ABORTED',
      endedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      failureReason: 'Aborted by operator command',
    }));
    setJobs(prev =>
      prev.map(j => ({
        ...j,
        latestAttemptState: j.latestAttemptId === attemptId ? 'FAILED' : j.latestAttemptState,
        attempts: j.attempts.map(att =>
          att.id === attemptId
            ? { ...att, state: 'FAILED', endedAt: new Date().toISOString().replace('T', ' ').slice(0, 19), failureReason: 'Aborted by operator command' }
            : att
        ),
      }))
    );
    const abortEvt: DiagnosticEvent = {
      id: generateUniqueEventId(),
      time: timeStr,
      severity: 'ERROR',
      event: 'AttemptFailed',
      scope: 'TRAINING_CONTROL',
      runtimeSeq: currentAttempt.runtimeEventSeq + 1,
      source: 'mcp.core.controller',
      attemptId: currentAttempt.id,
      payload: {
        reason: 'Training stopped by operator command',
      },
      technicalCorrelationId: `corr_abort_${Date.now()}`,
    };
    addEvent(abortEvt);
  };

  const requestCheckpoint = () => {
    const timeStr = new Date().toTimeString().slice(0, 8);
    const fullTimeStr = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const newCkptId = `ckpt_${currentAttempt.modelVersion.replace('v', '') || Date.now()}`;
    const newCheckpoint: Checkpoint = {
      id: newCkptId,
      state: 'COMPLETE',
      jobId: currentAttempt.jobId,
      jobName: currentAttempt.jobName,
      attemptId: currentAttempt.id,
      modelVersion: currentAttempt.modelVersion,
      sourceStepId: Number(currentAttempt.modelVersion.replace('v', '')) || 3264,
      createdAt: fullTimeStr,
      sizeMb: 44.8,
      recovery: {
        modelVersion: currentAttempt.modelVersion,
        epoch: currentAttempt.epoch,
        nextBatchOrdinal: currentAttempt.currentBatch,
      },
      lineage: {
        jobId: currentAttempt.jobId,
        createdByAttempt: currentAttempt.id,
        sourceStep: Number(currentAttempt.modelVersion.replace('v', '')) || 3264,
        datasetBuildId: 'build_cifar10_v3',
      },
      integrity: {
        contractHash: '0x8899aabbccddeeff00112233',
        manifestHash: '0x8f4b7e9a22d0c6114b7890efba71',
        modelSha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
        artifactSizeBytes: 46976204,
      },
    };
    setCheckpoints(prev => [newCheckpoint, ...prev]);
    setCurrentAttempt(prev => ({ ...prev, latestCheckpointId: newCkptId }));

    const ckptEvt: DiagnosticEvent = {
      id: generateUniqueEventId(),
      time: timeStr,
      severity: 'INFO',
      event: 'CheckpointComplete',
      scope: 'DURABILITY',
      runtimeSeq: currentAttempt.runtimeEventSeq + 1,
      source: 'mcp.durability.manager',
      attemptId: currentAttempt.id,
      payload: {
        checkpoint_id: newCkptId,
        model_version: currentAttempt.modelVersion,
        size_mb: 44.8,
      },
      technicalCorrelationId: `corr_ckpt_${newCkptId}`,
    };
    addEvent(ckptEvt);
  };

  const cloneJob = (jobId: string) => {
    const source = jobs.find(j => j.id === jobId);
    if (!source) return;
    const newJobId = `job_${Date.now().toString(36).slice(-6)}`;
    const cloned: Job = {
      ...source,
      id: newJobId,
      name: `${source.name} (Copy)`,
      jobState: 'DRAFT',
      attemptsCount: 0,
      latestAttemptId: '',
      latestAttemptState: 'CREATED',
      createdAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      frozenAt: null,
      attempts: [],
    };
    setJobs(prev => [cloned, ...prev]);
  };

  const startJobFresh = (jobId: string) => {
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;
    setIsSimulating(true);
    const newAttemptId = `attempt_${Date.now().toString(36).toUpperCase()}`;
    const newAttempt: Attempt = {
      id: newAttemptId,
      jobId: job.id,
      jobName: job.name,
      executionMode: 'FRESH',
      state: 'RUNNING',
      startedAt: new Date().toISOString().replace('T', ' ').slice(0, 19),
      endedAt: null,
      failureReason: null,
      latestCheckpointId: '',
      epoch: 1,
      totalEpochs: job.requestedContract?.epochs || 20,
      currentBatch: 1,
      totalBatches: 782,
      modelVersion: 'v1',
      expectedWorkers: 3,
      activeWorkers: 3,
      runtimeEventSeq: 1,
      strategy: 'strict_bsp',
      elapsedFormatted: '00:00:01',
      barrierWaitMs: 0,
    };
    setCurrentAttempt(newAttempt);
    setJobs(prev =>
      prev.map(j =>
        j.id === jobId
          ? {
              ...j,
              jobState: 'READY',
              latestAttemptId: newAttemptId,
              latestAttemptState: 'RUNNING',
              attemptsCount: j.attemptsCount + 1,
              attempts: [newAttempt, ...j.attempts],
            }
          : j
      )
    );
  };

  // Step advancement simulation for Strict BSP demonstration
  const simulateStepAdvance = () => {
    if (currentAttempt.state !== 'RUNNING') return;
    const activeStep = steps[0];
    if (!activeStep) return;

    const timeStr = new Date().toTimeString().slice(0, 8);
    const phase = simPhaseRef.current % 9;
    simPhaseRef.current += 1;

    if (phase === 0) {
      // Worker 0 contribution
      setSteps(prev => {
        const [first, ...rest] = prev;
        if (!first) return prev;
        const updatedW = first.workerContributions.map(w =>
          w.workerId === 0 ? { ...w, contributionAccepted: true, parameterApplied: false } : w
        );
        return [{ ...first, workerContributions: updatedW }, ...rest];
      });
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'GradientContributionAccepted',
        scope: 'SYNCHRONIZATION',
        runtimeSeq: currentAttempt.runtimeEventSeq + 1,
        source: 'mcp.barrier.gate',
        attemptId: currentAttempt.id,
        payload: {
          worker_id: 0,
          step_id: activeStep.operationId,
          batch_id: `batch-${activeStep.batchOrdinal}`,
          samples: 64,
          accepted_count: 1,
          expected: 3,
        },
        technicalCorrelationId: `corr_bsp_w0_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 1) {
      // Worker 1 contribution
      setSteps(prev => {
        const [first, ...rest] = prev;
        if (!first) return prev;
        const updatedW = first.workerContributions.map(w =>
          w.workerId === 1 ? { ...w, contributionAccepted: true } : w
        );
        return [{ ...first, workerContributions: updatedW }, ...rest];
      });
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'GradientContributionAccepted',
        scope: 'SYNCHRONIZATION',
        runtimeSeq: currentAttempt.runtimeEventSeq + 2,
        source: 'mcp.barrier.gate',
        attemptId: currentAttempt.id,
        payload: {
          worker_id: 1,
          step_id: activeStep.operationId,
          batch_id: `batch-${activeStep.batchOrdinal}`,
          samples: 64,
          accepted_count: 2,
          expected: 3,
        },
        technicalCorrelationId: `corr_bsp_w1_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 2) {
      // Waiting for Worker 2
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'WaitingForWorker',
        scope: 'SYNCHRONIZATION',
        runtimeSeq: currentAttempt.runtimeEventSeq + 3,
        source: 'mcp.barrier.gate',
        attemptId: currentAttempt.id,
        payload: {
          waiting_for: 2,
          step_id: activeStep.operationId,
          received_count: 2,
          expected_count: 3,
        },
        technicalCorrelationId: `corr_wait_w2_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 3) {
      // Worker 2 contribution
      setSteps(prev => {
        const [first, ...rest] = prev;
        if (!first) return prev;
        const updatedW = first.workerContributions.map(w =>
          w.workerId === 2 ? { ...w, contributionAccepted: true } : w
        );
        return [{ ...first, workerContributions: updatedW }, ...rest];
      });
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'GradientContributionAccepted',
        scope: 'SYNCHRONIZATION',
        runtimeSeq: currentAttempt.runtimeEventSeq + 4,
        source: 'mcp.barrier.gate',
        attemptId: currentAttempt.id,
        payload: {
          worker_id: 2,
          step_id: activeStep.operationId,
          batch_id: `batch-${activeStep.batchOrdinal}`,
          samples: 64,
          accepted_count: 3,
          expected: 3,
        },
        technicalCorrelationId: `corr_bsp_w2_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 4) {
      // Updating global model
      setSteps(prev => {
        const [first, ...rest] = prev;
        if (!first) return prev;
        return [{ ...first, state: 'UPDATING' }, ...rest];
      });
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'UpdatingGlobalModel',
        scope: 'MODEL_OPTIMIZER',
        runtimeSeq: currentAttempt.runtimeEventSeq + 5,
        source: 'mcp.optimizer.engine',
        attemptId: currentAttempt.id,
        payload: {
          step_id: activeStep.operationId,
          optimizer: 'SGD_MOMENTUM',
          learning_rate: 0.01,
        },
        technicalCorrelationId: `corr_opt_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 5) {
      // Model version ready
      const nextVer = `v${activeStep.operationId}`;
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'ModelVersionReady',
        scope: 'MODEL_REGISTRY',
        runtimeSeq: currentAttempt.runtimeEventSeq + 6,
        source: 'mcp.registry.service',
        attemptId: currentAttempt.id,
        payload: {
          model_version: nextVer,
          step_id: activeStep.operationId,
        },
        technicalCorrelationId: `corr_ver_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 6) {
      // Parameters applied by all workers
      setSteps(prev => {
        const [first, ...rest] = prev;
        if (!first) return prev;
        const updatedW = first.workerContributions.map(w => ({ ...w, parameterApplied: true }));
        return [{ ...first, state: 'WAITING_PARAMETER_APPLIED', workerContributions: updatedW }, ...rest];
      });
      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'ParametersAppliedAllWorkers',
        scope: 'DISTRIBUTION',
        runtimeSeq: currentAttempt.runtimeEventSeq + 7,
        source: 'mcp.parameter.broadcast',
        attemptId: currentAttempt.id,
        payload: {
          step_id: activeStep.operationId,
          worker_count: 3,
        },
        technicalCorrelationId: `corr_param_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 7) {
      // Step committed
      const currentLoss = activeStep.loss ?? 0.124;
      const currentAcc = activeStep.accuracy ?? 92.4;
      const committedStep: TrainingStep = {
        ...activeStep,
        state: 'COMMITTED',
        loss: currentLoss,
        accuracy: currentAcc,
        timings: {
          ...activeStep.timings,
          committedAt: timeStr,
          totalDurationMs: 145,
        },
      };
      const nextOpId = activeStep.operationId + 1;
      const nextBatch = activeStep.batchOrdinal + 1;

      setSteps(prev => [committedStep, ...prev.slice(1)]);
      setCurrentAttempt(prev => ({
        ...prev,
        currentBatch: nextBatch,
        modelVersion: `v${activeStep.operationId}`,
        runtimeEventSeq: prev.runtimeEventSeq + 8,
      }));
      setRuntimeSnapshot(prev => ({
        ...prev,
        batch: nextBatch,
        modelVersion: `v${activeStep.operationId}`,
        runtimeEventSeq: prev.runtimeEventSeq + 8,
      }));

      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'StepCommitted',
        scope: 'STRICT_BSP_PIPELINE',
        runtimeSeq: currentAttempt.runtimeEventSeq + 8,
        source: 'mcp.core.engine',
        attemptId: currentAttempt.id,
        payload: {
          operation_id: activeStep.operationId,
          model_version: `v${activeStep.operationId}`,
          samples_aggregated: 192,
        },
        technicalCorrelationId: `corr_commit_${activeStep.operationId}`,
      };
      addEvent(evt);
    } else if (phase === 8) {
      // Starting next training step
      const nextOpId = activeStep.operationId + 1;
      const nextBatch = activeStep.batchOrdinal + 1;
      const prevLoss = activeStep.loss ?? 0.124;
      const nextLoss = Math.max(0.045, Math.round((prevLoss * 0.982) * 1000) / 1000);
      const prevAcc = activeStep.accuracy ?? 92.4;
      const nextAcc = Math.min(97.2, Math.round((prevAcc + (100 - prevAcc) * 0.015) * 10) / 10);

      const newActiveStep: TrainingStep = {
        operationId: nextOpId,
        attemptId: activeStep.attemptId,
        state: 'COLLECTING_GRADIENTS',
        epoch: activeStep.epoch,
        batchOrdinal: nextBatch,
        inputModelVersion: String(activeStep.operationId),
        outputModelVersion: String(nextOpId),
        totalSampleCount: 192,
        loss: nextLoss,
        accuracy: nextAcc,
        timings: {
          startedAt: timeStr,
          gradientCollectionMs: 35,
          aggregateMs: 0,
          optimizerUpdateMs: 0,
          broadcastMs: 0,
          parameterAppliedWaitMs: 0,
          checkpointMs: 0,
          committedAt: '',
          totalDurationMs: 35,
        },
        workerContributions: [
          { workerId: 0, sessionId: 'sess_87391abf02', shardId: 'shard-00', batchId: `batch-${nextBatch}`, sampleCount: 64, samples: 64, contributionAccepted: false, parameterApplied: false },
          { workerId: 1, sessionId: 'sess_22108cfd41', shardId: 'shard-01', batchId: `batch-${nextBatch}`, sampleCount: 64, samples: 64, contributionAccepted: false, parameterApplied: false },
          { workerId: 2, sessionId: 'sess_99187ec092', shardId: 'shard-02', batchId: `batch-${nextBatch}`, sampleCount: 64, samples: 64, contributionAccepted: false, parameterApplied: false },
        ],
      };

      setSteps(prev => [newActiveStep, ...prev]);

      const evt: DiagnosticEvent = {
        id: generateUniqueEventId(),
        time: timeStr,
        severity: 'INFO',
        event: 'StepStarted',
        scope: 'STRICT_BSP_PIPELINE',
        runtimeSeq: currentAttempt.runtimeEventSeq + 9,
        source: 'mcp.core.engine',
        attemptId: currentAttempt.id,
        payload: {
          operation_id: nextOpId,
          batch_ordinal: nextBatch,
        },
        technicalCorrelationId: `corr_start_${nextOpId}`,
      };
      addEvent(evt);
    }
  };

  useEffect(() => {
    let timer: any;
    if (isSimulating && currentAttempt.state === 'RUNNING') {
      timer = setInterval(() => {
        simulateStepAdvance();
      }, 1900);
    }
    return () => clearInterval(timer);
  }, [isSimulating, steps, currentAttempt.state]);

  return (
    <AppContext.Provider
      value={{
        jobs,
        attempts,
        datasets,
        datasetBuilds,
        checkpoints,
        steps,
        events,
        subsystems,
        workers,
        currentAttempt,
        runtimeSnapshot,
        isRuntimeStale,
        hasEventHistoryGap,
        selectedWorker,
        selectedStep,
        selectedEvent,
        selectedCheckpoint,
        selectedDatasetBuild,
        rawContractModalJob,
        toggleRuntimeStale,
        toggleEventHistoryGap,
        setSelectedWorker,
        setSelectedStep,
        setSelectedEvent,
        setSelectedCheckpoint,
        setSelectedDatasetBuild,
        setRawContractModalJob,
        createJob,
        archiveJob,
        deprecateBuild,
        purgeBuild,
        purgeDatasetBuild,
        triggerDatasetBuild,
        resumeFromCheckpoint,
        abortAttempt,
        requestCheckpoint,
        cloneJob,
        startJobFresh,
        simulateStepAdvance,
        isSimulating,
        setIsSimulating,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
