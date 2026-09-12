import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Play,
  Layers,
  Cpu,
  Sliders,
  FileCheck,
  Plus,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { datasetsService, datasetBuildsService, systemService, jobsService } from '../api';
import {
  DatasetItemData,
  DatasetBuildListItemData,
  SupportedModelData,
  JobDetailData,
  JobValidateResponseData,
} from '../types/api';

export const NewTrainingFlowPage: React.FC = () => {
  const { triggerDatasetBuild } = useApp();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // API Catalog State
  const [apiDatasets, setApiDatasets] = useState<DatasetItemData[]>([]);
  const [apiBuilds, setApiBuilds] = useState<DatasetBuildListItemData[]>([]);
  const [supportedModels, setSupportedModels] = useState<SupportedModelData[]>([]);
  const [loadingData, setLoadingData] = useState<boolean>(true);

  // Step state: 1 = Dataset, 2 = Model, 3 = Settings, 4 = Review, 5 = Ready
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);

  // Preselection from query params if available
  const initialDatasetId = searchParams.get('datasetId') || '';
  const initialBuildId = searchParams.get('buildId') || '';

  // Form State
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(initialDatasetId);
  const [selectedBuildId, setSelectedBuildId] = useState<string>(initialBuildId);
  const [selectedModel, setSelectedModel] = useState<string>('resnet18_groupnorm');
  const [epochs, setEpochs] = useState<number>(20);
  const [learningRate, setLearningRate] = useState<number>(0.01);
  const [seed, setSeed] = useState<number>(42);
  const [jobName, setJobName] = useState<string>('');

  // Created Job & Validation tracking (Server State)
  const [createdJob, setCreatedJob] = useState<JobDetailData | null>(null);
  const [validationResult, setValidationResult] = useState<JobValidateResponseData | null>(null);
  const [validating, setValidating] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const loadFlowData = async () => {
      try {
        setLoadingData(true);
        const [dsRes, buildsRes, capRes] = await Promise.allSettled([
          datasetsService.listDatasets({ limit: 50 }),
          datasetBuildsService.listBuilds({ limit: 100 }),
          systemService.getCapabilities(),
        ]);

        if (dsRes.status === 'fulfilled') {
          const ds = dsRes.value.data || [];
          setApiDatasets(ds);
          if (!selectedDatasetId && ds.length > 0) {
            setSelectedDatasetId(ds[0].dataset_id);
          }
        }

        if (buildsRes.status === 'fulfilled') {
          setApiBuilds(buildsRes.value.data || []);
        }

        if (capRes.status === 'fulfilled' && capRes.value.data?.supported_models) {
          setSupportedModels(capRes.value.data.supported_models);
          if (capRes.value.data.supported_models.length > 0) {
            setSelectedModel(capRes.value.data.supported_models[0].model_id);
          }
        }
      } finally {
        setLoadingData(false);
      }
    };

    loadFlowData();
  }, []);

  // Filter available builds for the chosen dataset
  const currentDataset = (apiDatasets || []).find(d => d.dataset_id === selectedDatasetId);
  const readyBuilds = (apiBuilds || []).filter(
    b => b.dataset_id === selectedDatasetId && b.state === 'READY'
  );

  // Auto-select a ready build if none is selected or selection is invalid
  useEffect(() => {
    if (readyBuilds.length > 0) {
      if (!selectedBuildId || !readyBuilds.some(b => b.dataset_build_id === selectedBuildId)) {
        setSelectedBuildId(readyBuilds[0].dataset_build_id);
      }
    } else {
      setSelectedBuildId('');
    }
  }, [selectedDatasetId, apiBuilds]);

  // Set default job name when dataset/model changes
  useEffect(() => {
    if (currentDataset && !jobName) {
      setJobName(`${selectedModel} on ${currentDataset.name}`);
    }
  }, [currentDataset, selectedModel]);

  const selectedBuild = readyBuilds.find(b => b.dataset_build_id === selectedBuildId);

  // Model Options: dynamic from capabilities if provided, with fallback defaults
  const MODEL_OPTIONS = supportedModels.length > 0
    ? supportedModels.map(m => ({
        id: m.model_id,
        name: m.display_name || m.model_id,
        description: `Architecture ${m.model_id} for distributed training.`,
        parameters: '11.2M',
      }))
    : [
        {
          id: 'resnet18_groupnorm',
          name: 'ResNet-18 (GroupNorm)',
          description: 'Standard 18-layer residual network with GroupNorm for robust distributed mini-batch training.',
          parameters: '11.2M',
        },
        {
          id: 'resnet50_groupnorm',
          name: 'ResNet-50 (GroupNorm)',
          description: 'Deeper 50-layer residual network for high-capacity distributed vision tasks.',
          parameters: '25.6M',
        },
      ];

  const handleBuildDataset = () => {
    if (!selectedDatasetId) return;
    const newBuild = triggerDatasetBuild(selectedDatasetId, 'HASH', 3);
    setSelectedBuildId(newBuild.id);
  };

  /**
   * Transition from Step 3 to Step 4:
   * Create DRAFT job via POST /api/v1/jobs (or PATCH if updating existing DRAFT)
   * and validate contract via POST /api/v1/jobs/{id}/validate
   */
  const handleProceedToReview = async () => {
    try {
      setFormError(null);
      setValidating(true);

      const finalName = jobName.trim() || `${selectedModel} on ${currentDataset?.name || 'Dataset'}`;

      let currentDraft: JobDetailData;

      if (!createdJob) {
        // API 13.0: Create Job in DRAFT state
        const createRes = await jobsService.createJob({
          display_name: finalName,
          requested_contract: {
            dataset_build_id: selectedBuildId,
            model_id: selectedModel,
            epochs,
            learning_rate: learningRate,
            training_seed: seed,
            training_strategy: 'strict_bsp',
          },
        });
        currentDraft = createRes.data;
        setCreatedJob(currentDraft);
      } else {
        // API 16.0: Patch existing DRAFT job
        const patchRes = await jobsService.patchJob(createdJob.job_id, {
          display_name: finalName,
          requested_contract: {
            dataset_build_id: selectedBuildId,
            model_id: selectedModel,
            epochs,
            learning_rate: learningRate,
            training_seed: seed,
            training_strategy: 'strict_bsp',
          },
        });
        currentDraft = patchRes.data;
        setCreatedJob(currentDraft);
      }

      // API 17.0: Validate Job contract with backend
      const valRes = await jobsService.validateJob(currentDraft.job_id);
      setValidationResult(valRes.data);

      setStep(4);
    } catch (err: any) {
      setFormError(err?.message || 'Failed to create and validate training specification');
    } finally {
      setValidating(false);
    }
  };

  /**
   * Launch Training:
   * API 20.0 POST /api/v1/jobs/{job_id}/start -> 202 Accepted with attempt_id
   */
  const handleStartTraining = async () => {
    if (!createdJob) return;
    try {
      setActionLoading('start');
      setFormError(null);
      const startRes = await jobsService.startJob(createdJob.job_id);
      const attemptId = startRes.data.attempt_id;
      // Navigate to live monitoring or job detail with real attempt_id
      navigate(`/jobs/${createdJob.job_id}`);
    } catch (err: any) {
      setFormError(err?.message || 'Failed to start training attempt');
    } finally {
      setActionLoading(null);
    }
  };

  const hasValidationErrors = (validationResult?.errors?.length ?? 0) > 0;
  const hasValidationWarnings = (validationResult?.warnings?.length ?? 0) > 0;
  const preview = validationResult?.resolved_preview;

  return (
    <div className="space-y-6 w-full pb-12 font-sans select-none">
      {/* Top Breadcrumb & Cancel */}
      <div className="flex items-center justify-between text-xs text-[#73737c]">
        <div className="flex items-center gap-2">
          <Link to="/jobs" className="hover:text-[#f3f3f4] flex items-center gap-1 transition-colors">
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Jobs</span>
          </Link>
          <span>/</span>
          <span className="text-[#a1a1a8]">New training</span>
        </div>
        <Link to="/jobs" className="hover:text-[#f3f3f4] transition-colors">
          Cancel
        </Link>
      </div>

      {/* Header */}
      <div>
        <h1 className="text-base font-semibold text-[#f3f3f4]">
          New training
        </h1>
        <p className="text-xs text-[#73737c] mt-0.5">
          Configure a dataset, select a model architecture, and launch distributed training.
        </p>
      </div>

      {/* Step Indicator */}
      <nav aria-label="Training setup steps" className="border-y border-white/[0.07] py-2.5">
        <div className="flex items-center gap-2 sm:gap-4 text-xs">
          {[
            { num: 1, label: 'Dataset' },
            { num: 2, label: 'Model' },
            { num: 3, label: 'Training settings' },
            { num: 4, label: 'Review' },
          ].map((s, idx) => {
            const isCurrent = step === s.num;
            const isDone = step > s.num;
            return (
              <React.Fragment key={s.num}>
                {idx > 0 && <span className="text-[#3f3f46]">→</span>}
                <button
                  type="button"
                  onClick={() => step < 5 && setStep(s.num as any)}
                  disabled={step === 5 || (s.num > 1 && !selectedBuildId)}
                  className={`flex items-center gap-1.5 transition-colors ${
                    isCurrent
                      ? 'text-[#f3f3f4] font-medium'
                      : isDone
                      ? 'text-[#a1a1a8] hover:text-[#f3f3f4]'
                      : 'text-[#52525b]'
                  }`}
                >
                  <span
                    className={`w-4 h-4 rounded-full flex items-center justify-center text-[10px] ${
                      isCurrent
                        ? 'bg-blue-600 text-white font-semibold'
                        : isDone
                        ? 'bg-white/[0.1] text-[#f3f3f4]'
                        : 'bg-white/[0.04] text-[#73737c]'
                    }`}
                  >
                    {isDone ? <Check className="w-2.5 h-2.5" /> : s.num}
                  </span>
                  <span>{s.label}</span>
                </button>
              </React.Fragment>
            );
          })}
        </div>
      </nav>

      {/* Form Error Banner */}
      {formError && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center gap-2 text-xs text-rose-300">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{formError}</span>
        </div>
      )}

      {/* STEP 1: CHOOSE DATASET */}
      {step === 1 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Choose a dataset
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Select verified training data. Training requires an active, partitioned build.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {(apiDatasets || []).map(ds => {
              const isSelected = selectedDatasetId === ds.dataset_id;
              const dsBuilds = (apiBuilds || []).filter(b => b.dataset_id === ds.dataset_id);
              const dsReadyBuilds = dsBuilds.filter(b => b.state === 'READY');
              const hasReadyBuild = dsReadyBuilds.length > 0;

              return (
                <div
                  key={ds.dataset_id}
                  onClick={() => setSelectedDatasetId(ds.dataset_id)}
                  className={`p-4 rounded border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                      : 'bg-[#121214] border-white/[0.07] hover:border-white/[0.15]'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-sm font-medium text-[#f3f3f4]">
                        {ds.name}
                      </div>
                      <div className="text-xs text-[#73737c] mt-0.5 font-mono">
                        {ds.dataset_id} · {ds.task_type || 'image_classification'}
                      </div>
                    </div>
                    {isSelected && (
                      <span className="w-4 h-4 rounded-full bg-blue-600 flex items-center justify-center text-white">
                        <Check className="w-2.5 h-2.5" />
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-[#a1a1a8] mt-2 line-clamp-2 leading-relaxed">
                    Source: {ds.source_type} ({ds.source_reference})
                  </p>

                  <div className="mt-3 pt-2.5 border-t border-white/[0.06] text-xs">
                    {hasReadyBuild ? (
                      <span className="text-emerald-400 text-[11px] flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        {dsReadyBuilds.length} ready build{dsReadyBuilds.length > 1 ? 's' : ''} available
                      </span>
                    ) : (
                      <span className="text-amber-400 text-[11px] flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" />
                        No ready build available
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Dataset Builds Selection for the chosen dataset */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#f3f3f4]">
                Available builds for {currentDataset?.name}
              </span>
              {readyBuilds.length === 0 && (
                <button
                  type="button"
                  onClick={handleBuildDataset}
                  className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center gap-1 transition-colors"
                >
                  <Plus className="w-3 h-3" />
                  <span>Create dataset build</span>
                </button>
              )}
            </div>

            {readyBuilds.length > 0 ? (
              <div className="space-y-2">
                {readyBuilds.map(b => {
                  const isBuildSelected = selectedBuildId === b.dataset_build_id;
                  const shardsCount = b.shard_count || 3;
                  const sampleCount = b.sample_count || 50000;
                  return (
                    <label
                      key={b.dataset_build_id}
                      className={`flex items-center justify-between p-3 rounded border cursor-pointer transition-colors ${
                        isBuildSelected
                          ? 'bg-[#171719] border-blue-500/60'
                          : 'bg-[#141416] border-white/[0.05] hover:border-white/[0.1]'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <input
                          type="radio"
                          name="dataset_build"
                          checked={isBuildSelected}
                          onChange={() => setSelectedBuildId(b.dataset_build_id)}
                          className="text-blue-600 focus:ring-0 bg-transparent border-white/20"
                        />
                        <div>
                          <div className="text-xs font-medium text-[#f3f3f4]">
                            Ready build <span className="font-mono text-[11px] text-[#a1a1a8]">({b.dataset_build_id})</span> · batch size {b.batch_size || 64} · {shardsCount} shards
                          </div>
                          <div className="text-[11px] text-[#73737c] mt-0.5">
                            {sampleCount.toLocaleString()} samples · {b.profile || 'standard-sharded'}
                          </div>
                        </div>
                      </div>
                      <span className="text-[11px] text-emerald-400">Ready for training</span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 bg-[#171719] rounded text-center space-y-2">
                <div className="text-xs text-[#a1a1a8]">
                  Dataset is not ready for training.
                </div>
                <p className="text-[11px] text-[#73737c]">
                  A materialized partitioned build is required before starting distributed training.
                </p>
                <button
                  type="button"
                  onClick={handleBuildDataset}
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium inline-flex items-center gap-1.5 transition-colors mt-1"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Create dataset build</span>
                </button>
              </div>
            )}
          </div>

          {/* Navigation */}
          <div className="flex items-center justify-end pt-2">
            <button
              type="button"
              disabled={!selectedBuildId}
              onClick={() => setStep(2)}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors flex items-center gap-1.5"
            >
              <span>Next: Choose model</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: CHOOSE MODEL */}
      {step === 2 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Choose a model
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Select the neural network architecture configured for distributed training.
            </p>
          </div>

          <div className="space-y-3">
            {MODEL_OPTIONS.map(m => {
              const isSelected = selectedModel === m.id;
              return (
                <div
                  key={m.id}
                  onClick={() => setSelectedModel(m.id)}
                  className={`p-4 rounded border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                      : 'bg-[#121214] border-white/[0.07] hover:border-white/[0.15]'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <span
                        className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                          isSelected ? 'border-blue-500 bg-blue-600' : 'border-white/20'
                        }`}
                      >
                        {isSelected && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
                      </span>
                      <span className="text-sm font-medium text-[#f3f3f4]">{m.name}</span>
                    </div>
                    <span className="text-xs text-[#73737c]">{m.parameters} parameters</span>
                  </div>

                  <p className="text-xs text-[#a1a1a8] mt-2 pl-6 leading-relaxed">
                    {m.description}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Navigation */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5"
            >
              <span>Next: Training settings</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: TRAINING SETTINGS */}
      {step === 3 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Training settings
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Set training hyperparameters and distributed synchronization parameters.
            </p>
          </div>

          {/* Job Name */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <label className="block text-xs font-semibold text-[#f3f3f4]">
              Training name
            </label>
            <input
              type="text"
              value={jobName}
              onChange={e => setJobName(e.target.value)}
              placeholder="e.g. ResNet18 on CIFAR-10"
              className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
            />
          </div>

          {/* Hyperparameters */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-4">
            <div className="text-xs font-semibold text-[#f3f3f4]">
              Hyperparameters
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <label className="block text-[#73737c] mb-1">
                  Epochs
                </label>
                <input
                  type="number"
                  min="1"
                  max="200"
                  value={epochs}
                  onChange={e => setEpochs(parseInt(e.target.value, 10) || 1)}
                  className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
                />
              </div>

              <div>
                <label className="block text-[#73737c] mb-1">
                  Learning rate
                </label>
                <input
                  type="number"
                  step="0.001"
                  min="0.0001"
                  max="1.0"
                  value={learningRate}
                  onChange={e => setLearningRate(parseFloat(e.target.value) || 0.001)}
                  className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
                />
              </div>

              <div>
                <label className="block text-[#73737c] mb-1">
                  Training seed
                </label>
                <input
                  type="number"
                  value={seed}
                  onChange={e => setSeed(parseInt(e.target.value, 10) || 42)}
                  className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
                />
              </div>

              <div>
                <label className="block text-[#73737c] mb-1">
                  Dataset Batch Size (Configured in Build)
                </label>
                <input
                  type="number"
                  disabled
                  value={selectedBuild?.batch_size || 64}
                  className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.05] rounded text-xs text-[#a1a1a8] cursor-not-allowed opacity-80"
                />
                <span className="text-[11px] text-[#73737c] mt-1 block">
                  Determined by dataset build #{selectedBuildId.slice(-6)}
                </span>
              </div>
            </div>
          </div>

          {/* Distributed Strategy */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#f3f3f4]">
                Distributed training strategy
              </span>
              <span className="text-[11px] text-[#73737c]">Strict BSP</span>
            </div>

            <div className="p-3 bg-[#171719] rounded text-xs space-y-1">
              <div className="font-medium text-[#f3f3f4]">
                Strict BSP (Bulk Synchronous Parallel)
              </div>
              <p className="text-[#a1a1a8] text-xs leading-relaxed">
                All workers synchronize before each global model update. Guarantees deterministic convergence without stale gradients.
              </p>
            </div>
          </div>

          {/* Navigation */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </button>
            <button
              type="button"
              disabled={validating}
              onClick={handleProceedToReview}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50"
            >
              {validating ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Validating contract...</span>
                </>
              ) : (
                <>
                  <span>Next: Review & Validate</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* STEP 4: REVIEW & VALIDATION */}
      {step === 4 && (
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Review training specification
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Contract validation completed with backend Parameter Server coordinator.
            </p>
          </div>

          {/* Validation Warnings */}
          {hasValidationWarnings && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded text-xs text-amber-300 space-y-1">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Contract Warnings</span>
              </div>
              <ul className="list-disc pl-5 text-[11px] space-y-0.5 text-amber-200">
                {validationResult?.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Validation Errors */}
          {hasValidationErrors && (
            <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded text-xs text-rose-300 space-y-1">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertCircle className="w-4 h-4 text-rose-400" />
                <span>Contract Validation Errors (Cannot Start)</span>
              </div>
              <ul className="list-disc pl-5 text-[11px] space-y-0.5 text-rose-200">
                {validationResult?.errors.map((e, idx) => (
                  <li key={idx}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="bg-[#121214] border border-white/[0.07] rounded divide-y divide-white/[0.07]">
            {/* Dataset Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Dataset Build</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5 font-mono">
                  {selectedBuildId}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.dataset?.total_train_samples ? `${preview.dataset.total_train_samples.toLocaleString()} samples` : 'Ready'} · batch size {preview?.dataset?.batch_size || selectedBuild?.batch_size || 64} · {preview?.dataset?.steps_per_epoch ? `${preview.dataset.steps_per_epoch} steps/epoch` : ''}
              </div>
            </div>

            {/* Model Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Model Architecture</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  {preview?.model?.architecture_name || selectedModel}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.model?.parameter_count ? `${(preview.model.parameter_count / 1_000_000).toFixed(1)}M parameters` : 'Neural Network'}
              </div>
            </div>

            {/* Training Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Training Hyperparameters</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  {epochs} epochs
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                Learning rate {learningRate} · Seed {seed}
              </div>
            </div>

            {/* Distributed Training Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Distributed Synchronization</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  Strict BSP
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.synchronization?.expected_workers || 3} expected workers · DTP v{preview?.protocols?.dtp_version ?? 1} / MCP v{preview?.protocols?.mcp_version ?? 1}
              </div>
            </div>
          </div>

          {/* Review Actions */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(3)}
              className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setStep(5)}
                className="px-3.5 py-1.5 rounded text-xs text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors"
              >
                Save as Draft
              </button>
              <button
                type="button"
                disabled={hasValidationErrors || actionLoading === 'start'}
                onClick={handleStartTraining}
                className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:pointer-events-none"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>{actionLoading === 'start' ? 'Starting...' : 'Create & Start'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 5: READY STATE (After Job creation) */}
      {step === 5 && (
        <div className="p-8 bg-[#121214] border border-white/[0.07] rounded text-center space-y-4 max-w-lg mx-auto">
          <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto">
            <Check className="w-5 h-5" />
          </div>

          <div>
            <h2 className="text-base font-semibold text-[#f3f3f4]">
              Training Job Created
            </h2>
            <p className="text-xs text-[#73737c] mt-1">
              Job specification <strong className="text-[#f3f3f4]">{createdJob?.display_name}</strong> is registered on the server.
            </p>
          </div>

          <div className="flex items-center justify-center gap-3 pt-2">
            {createdJob && (
              <Link
                to={`/jobs/${createdJob.job_id}`}
                className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#171719] border border-white/[0.07] transition-colors"
              >
                View training details
              </Link>
            )}
            <button
              type="button"
              disabled={hasValidationErrors || actionLoading === 'start'}
              onClick={handleStartTraining}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:pointer-events-none"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>{actionLoading === 'start' ? 'Starting...' : 'Start training'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
