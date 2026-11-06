import { TrainingStrategySettings } from '../components/training/TrainingStrategySettings';
import { defaultAsyncSettings, trainingStrategyFields } from '../api/trainingStrategy';
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams, useParams, Link } from 'react-router-dom';
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
  ChevronDown,
} from 'lucide-react';
import { datasetsService, datasetBuildsService, systemService, jobsService, attemptsService } from '../api';
import {
  DatasetItemData,
  DatasetBuildListItemData,
  SupportedModelData,
  JobDetailData,
  JobValidateResponseData,
  NodeItemData,
  AttemptListItemData,
} from '../types/api';

export const NewTrainingFlowPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { jobId } = useParams<{ jobId?: string }>();
  const isEditMode = Boolean(jobId);

  // API Catalog State
  const [apiDatasets, setApiDatasets] = useState<DatasetItemData[]>([]);
  const [apiBuilds, setApiBuilds] = useState<DatasetBuildListItemData[]>([]);
  const [supportedModels, setSupportedModels] = useState<SupportedModelData[]>([]);
  const [loadingData, setLoadingData] = useState<boolean>(true);
  const [nodes, setNodes] = useState<NodeItemData[]>([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [nodeSelectionMode, setNodeSelectionMode] = useState<'auto' | 'manual'>('auto');

  // Step state: 1 = Dataset, 2 = Model, 3 = Settings, 4 = Review, 5 = Ready
  const [step, setStep] = useState<1 | 2 | 3 | 4 | 5>(1);

  // Preselection from query params if available
  const initialDatasetId = searchParams.get('datasetId') || '';
  const initialBuildId = searchParams.get('buildId') || '';

  // Form State
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>(initialDatasetId);
  const [selectedBuildId, setSelectedBuildId] = useState<string>(initialBuildId);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [epochs, setEpochs] = useState<number>(20);
  const [learningRate, setLearningRate] = useState<number>(0.01);
  const [seed, setSeed] = useState<number>(42);
  const [trainingStrategy, setTrainingStrategy] = useState<'strict_bsp' | 'async_sgd'>('strict_bsp');
  const [asyncSettings, setAsyncSettings] = useState(defaultAsyncSettings);
  const [workloadPolicy, setWorkloadPolicy] = useState<'equal' | 'dbs'>('equal');
  const [existingWups, setExistingWups] = useState<number | undefined>(undefined);
  const [everyNEpochs, setEveryNEpochs] = useState<number>(5);
  const [jobName, setJobName] = useState<string>('');
  const [jobDescription, setJobDescription] = useState<string>('');

  // Created Job & Validation tracking (Server State)
  const [createdJob, setCreatedJob] = useState<JobDetailData | null>(null);
  const [validationResult, setValidationResult] = useState<JobValidateResponseData | null>(null);
  const [validating, setValidating] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [activeAttempt, setActiveAttempt] = useState<AttemptListItemData | null | undefined>();
  const launching = useRef(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    attemptsService.getActiveAttempt().then(setActiveAttempt).catch(() => {
      setFormError('Unable to verify active attempts. Reload before starting training.');
    });
  }, []);

  const changeWorkloadPolicy = (policy: 'equal' | 'dbs') => {
    if (policy !== workloadPolicy) setExistingWups(undefined);
    setWorkloadPolicy(policy);
  };

  useEffect(() => {
    const loadFlowData = async () => {
      try {
        setLoadingData(true);
        const [dsRes, buildsRes, capRes, jobRes, nodesRes] = await Promise.allSettled([
          datasetsService.listDatasets({ limit: 50 }),
          datasetBuildsService.listBuilds({ limit: 100 }),
          systemService.getCapabilities(),
          isEditMode && jobId ? jobsService.getJob(jobId) : Promise.resolve(null),
          systemService.getNodes(),
        ]);
        if (nodesRes.status === 'fulfilled') setNodes(nodesRes.value.data || []);

        let loadedBuilds: DatasetBuildListItemData[] = [];
        if (buildsRes.status === 'fulfilled') {
          loadedBuilds = buildsRes.value.data || [];
          setApiBuilds(loadedBuilds);
        }

        if (dsRes.status === 'fulfilled') {
          const ds = dsRes.value.data || [];
          setApiDatasets(ds);
          if (!isEditMode && !selectedDatasetId && ds.length > 0) {
            setSelectedDatasetId(ds[0].dataset_id);
          }
        }

        if (capRes.status === 'fulfilled' && capRes.value.data?.supported_models) {
          setSupportedModels(capRes.value.data.supported_models);
          if (!isEditMode && capRes.value.data.supported_models.length > 0) {
            setSelectedModel(capRes.value.data.supported_models[0].model_id);
          }
        }

        if (isEditMode && jobRes.status === 'fulfilled' && jobRes.value?.data) {
          const job: JobDetailData = jobRes.value.data;
          setCreatedJob(job);
          setJobName(job.display_name);
          setJobDescription(job.description || '');

          if (job.requested_contract) {
            const req = job.requested_contract;
            setSelectedModel(req.model_id);
            setSelectedBuildId(req.dataset_build_id);
            setEpochs(req.epochs);
            setLearningRate(req.learning_rate);
            setSeed(req.training_seed);
            const pol =
              req.workload_policy ||
              (job as any).workload_policy ||
              (job as any).resolved_contract?.workload?.policy;
            if (pol === 'dbs' || pol === 'equal') {
              setWorkloadPolicy(pol);
            }
            setTrainingStrategy(req.training_strategy === "async_sgd" ? "async_sgd" : "strict_bsp");
            if (req.async_training) setAsyncSettings({ ...defaultAsyncSettings, ...req.async_training });
            if (req.work_units_per_step !== undefined) {
              setExistingWups(req.work_units_per_step);
            }
            if (req.checkpoint?.every_n_epochs) {
              setEveryNEpochs(req.checkpoint.every_n_epochs);
            } else if ((job as any).resolved_contract?.checkpoint_policy?.every_n_epochs) {
              setEveryNEpochs((job as any).resolved_contract.checkpoint_policy.every_n_epochs);
            }

            const matchingBuild = loadedBuilds.find(b => b.dataset_build_id === req.dataset_build_id);
            if (matchingBuild) {
              setSelectedDatasetId(matchingBuild.dataset_id);
            }
          }

          if (job.state !== 'DRAFT') {
            setFormError(`Job "${job.display_name}" is in ${job.state} state. Only DRAFT jobs may be edited.`);
          }
        }
      } finally {
        setLoadingData(false);
      }
    };

    loadFlowData();
  }, [isEditMode, jobId]);

  // Filter available builds for the chosen dataset
  const currentDataset = (apiDatasets || []).find(d => d.dataset_id === selectedDatasetId);
  const readyBuilds = (apiBuilds || []).filter(
    b => b.dataset_id === selectedDatasetId && b.state === 'READY'
  );

  // Auto-select a ready build if none is selected or selection is invalid (in Create mode)
  useEffect(() => {
    if (!isEditMode) {
      if (readyBuilds.length > 0) {
        if (!selectedBuildId || !readyBuilds.some(b => b.dataset_build_id === selectedBuildId)) {
          setSelectedBuildId(readyBuilds[0].dataset_build_id);
        }
      } else {
        setSelectedBuildId('');
      }
    }
  }, [selectedDatasetId, apiBuilds, isEditMode]);

  // Set default job name when dataset/model changes (Create mode only)
  useEffect(() => {
    if (!isEditMode && currentDataset && !jobName) {
      setJobName(`${selectedModel} on ${currentDataset.name}`);
    }
  }, [currentDataset, selectedModel, isEditMode]);

  const selectedBuild = readyBuilds.find(b => b.dataset_build_id === selectedBuildId) ||
    apiBuilds.find(b => b.dataset_build_id === selectedBuildId);

  // Model choices come from the Backend catalog, including the CPU smoke model.
  const MODEL_OPTIONS = supportedModels.map(m => ({
    id: m.model_id,
    name: m.display_name || m.model_id,
    description: m.description || `Kiến trúc ${m.model_id} cho huấn luyện phân tán.`,
    parameters: 'Chưa có dữ liệu',
  }));

  const handleBuildDataset = async () => {
    if (!selectedDatasetId) return;
    try {
      const res = await datasetBuildsService.createBuild({
        dataset_id: selectedDatasetId,
        profile: 'CNN_IMAGE_CLASSIFICATION_V1',
        batch_size: 64,
        partition_seed: 42,
      });
      if (res.data?.target_id) {
        setSelectedBuildId(res.data.target_id);
      }
      const buildsRes = await datasetBuildsService.listBuilds({ dataset_id: selectedDatasetId });
      setApiBuilds(buildsRes.data || []);
    } catch (err: any) {
      setFormError(err?.message || 'Không thể tạo bản dựng tập dữ liệu');
    }
  };

  /**
   * Transition from Step 3 to Step 4:
   * Create DRAFT job via POST /api/v1/jobs (or PATCH if updating existing DRAFT)
   * and validate contract via POST /api/v1/jobs/{id}/validate
   */
  const handleProceedToReview = async () => {
    try {
      setFormError(null);
      if (!selectedModel || !supportedModels.some(m => m.model_id === selectedModel)) {
        setFormError('Vui lòng chọn một mô hình được hỗ trợ từ danh mục.');
        return;
      }
      if (trainingStrategy === 'strict_bsp' && workloadPolicy === 'dbs' && (!Number.isInteger(existingWups) || (existingWups ?? 0) <= 0)) {
        setFormError('Nhập số nguyên dương các đơn vị công việc mỗi bước cho DBS. Giá trị phải lớn hơn số lượng worker dự kiến.');
        return;
      }
      if (!Number.isInteger(everyNEpochs) || everyNEpochs <= 0) {
        setFormError('Nhập số nguyên dương các epoch cho chu kỳ lưu checkpoint.');
        return;
      }
      setValidating(true);

      const finalName = jobName.trim() || `${selectedModel} on ${currentDataset?.name || 'Dataset'}`;

      let currentDraft: JobDetailData;

      if (isEditMode || createdJob) {
        const targetId = (createdJob?.job_id || jobId)!;
        // API 16.0: Patch existing DRAFT job
        const patchRes = await jobsService.patchJob(targetId, {
          display_name: finalName,
          description: jobDescription || undefined,
          requested_contract: {
            dataset_build_id: selectedBuildId,
            model_id: selectedModel,
            epochs,
            learning_rate: learningRate,
            training_seed: seed,
            ...trainingStrategyFields(trainingStrategy, workloadPolicy, existingWups, asyncSettings),
            checkpoint: { every_n_epochs: everyNEpochs },
          },
        });
        currentDraft = patchRes.data;
        setCreatedJob(currentDraft);
      } else {
        // API 13.0: Create Job in DRAFT state
        const createRes = await jobsService.createJob({
          display_name: finalName,
          description: jobDescription || undefined,
          requested_contract: {
            dataset_build_id: selectedBuildId,
            model_id: selectedModel,
            epochs,
            learning_rate: learningRate,
            training_seed: seed,
            ...trainingStrategyFields(trainingStrategy, workloadPolicy, existingWups, asyncSettings),
            checkpoint: { every_n_epochs: everyNEpochs },
          },
        });
        currentDraft = createRes.data;
        setCreatedJob(currentDraft);
      }

      // API 17.0: Validate Job contract with backend
      const valRes = await jobsService.validateJob(currentDraft.job_id);
      setValidationResult(valRes.data);

      setStep(4);
    } catch (err: any) {
      setFormError(err?.message || 'Không thể lưu và xác thực cấu hình huấn luyện');
    } finally {
      setValidating(false);
    }
  };

  /**
   * Launch Training:
   * API 20.0 POST /api/v1/jobs/{job_id}/start -> 202 Accepted with attempt_id
   */
  const handleStartTraining = async () => {
    const targetId = createdJob?.job_id || jobId;
    if (!targetId || activeAttempt !== null || launching.current) return;
    launching.current = true;
    try {
      setActionLoading('start');
      setFormError(null);
      if (selectedNodeIds.length && selectedNodeIds.length !== selectedBuild?.shard_count) {
        setFormError(`Chọn chính xác ${selectedBuild?.shard_count} Node trực tuyến, hoặc chọn Tự động phân bổ.`);
        return;
      }
      await attemptsService.assertNoActiveAttempt();
      const startRes = await jobsService.startJob(targetId, selectedNodeIds.length ? { node_ids: selectedNodeIds } : undefined);
      const attemptId = startRes.data.attempt_id;
      navigate(`/live?attempt_id=${encodeURIComponent(attemptId)}`);
    } catch (err: any) {
      setFormError(err?.message || 'Không thể khởi chạy phiên huấn luyện');
      setActiveAttempt(undefined);
      attemptsService.getActiveAttempt().then(setActiveAttempt).catch(() => {});
    } finally {
      launching.current = false;
      setActionLoading(null);
    }
  };

  const hasValidationErrors = (validationResult?.errors?.length ?? 0) > 0;
  const hasValidationWarnings = (validationResult?.warnings?.length ?? 0) > 0;
  const preview = validationResult?.resolved_preview;

  const onlineNodes = nodes.filter(n => n.state === 'ONLINE');
  const offlineNodes = nodes.filter(n => n.state !== 'ONLINE');
  const requiredNodes = selectedBuild?.shard_count ?? 3;

  return (
    <div className="space-y-6 w-full pb-12 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold text-[#f3f3f4]">
            {isEditMode ? 'Chỉnh sửa bản nháp huấn luyện' : 'Tạo phiên huấn luyện mới'}
          </h1>
          <p className="text-xs text-[#73737c] mt-0.5">
            {isEditMode
              ? 'Điều chỉnh cấu hình, chọn tập dữ liệu và siêu tham số cho bản nháp này.'
              : 'Cấu hình tập dữ liệu, chọn kiến trúc mô hình và khởi chạy huấn luyện phân tán.'}
          </p>
        </div>
        <Link
          to={isEditMode && jobId ? `/jobs/${jobId}` : "/jobs"}
          className="px-3 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors self-start sm:self-auto shrink-0"
        >
          Hủy
        </Link>
      </div>

      {/* Step Indicator */}
      <nav aria-label="Training setup steps" className="border-y border-white/[0.07] py-2.5">
        <div className="flex items-center gap-2 sm:gap-4 text-xs">
          {[
            { num: 1, label: 'Tập dữ liệu' },
            { num: 2, label: 'Mô hình' },
            { num: 3, label: 'Cấu hình huấn luyện' },
            { num: 4, label: 'Xem lại' },
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
              Chọn tập dữ liệu
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Chọn dữ liệu huấn luyện đã xác thực. Cần một bản dựng phân vùng sẵn sàng trước khi huấn luyện.
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
                      <div className="text-xs text-[#73737c] mt-0.5">
                        {ds.task_type || 'Phân loại hình ảnh'} · {ds.source_type || 'Tập dữ liệu chuẩn'}
                      </div>
                    </div>
                    {isSelected && (
                      <span className="w-4 h-4 rounded-full bg-blue-600 flex items-center justify-center text-white">
                        <Check className="w-2.5 h-2.5" />
                      </span>
                    )}
                  </div>

                  <p className="text-xs text-[#a1a1a8] mt-2 line-clamp-2 leading-relaxed">
                    Nguồn: {ds.source_type} ({ds.source_reference})
                  </p>

                  <div className="mt-3 pt-2.5 border-t border-white/[0.06] text-xs">
                    {hasReadyBuild ? (
                      <span className="text-emerald-400 text-[11px] flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        {dsReadyBuilds.length} bản dựng sẵn sàng
                      </span>
                    ) : (
                      <span className="text-amber-400 text-[11px] flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" />
                        Chưa có bản dựng sẵn sàng
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
                Bản dựng khả dụng cho {currentDataset?.name}
              </span>
              {readyBuilds.length === 0 && (
                <button
                  type="button"
                  onClick={handleBuildDataset}
                  className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center gap-1 transition-colors"
                >
                  <Plus className="w-3 h-3" />
                  <span>Tạo bản dựng tập dữ liệu</span>
                </button>
              )}
            </div>

            {readyBuilds.length > 0 ? (
              <div className="space-y-2">
                {readyBuilds.map(b => {
                  const isBuildSelected = selectedBuildId === b.dataset_build_id;
                  const shardsCount = b.shard_count ?? 0;
                  const sampleCount = b.sample_count ?? 0;
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
                            Bản dựng sẵn sàng · Lô {b.batch_size || 64} mẫu · {shardsCount} phân vùng
                          </div>
                          <div className="text-[11px] text-[#73737c] mt-0.5">
                            {sampleCount.toLocaleString()} mẫu · {b.profile || 'standard-sharded'}
                          </div>
                        </div>
                      </div>
                      <span className="text-[11px] text-emerald-400">Sẵn sàng huấn luyện</span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 bg-[#171719] rounded text-center space-y-2">
                <div className="text-xs text-[#a1a1a8]">
                  Tập dữ liệu chưa sẵn sàng cho huấn luyện.
                </div>
                <p className="text-[11px] text-[#73737c]">
                  Cần tạo một bản dựng phân vùng trước khi bắt đầu huấn luyện phân tán.
                </p>
                <button
                  type="button"
                  onClick={handleBuildDataset}
                  className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium inline-flex items-center gap-1.5 transition-colors mt-1"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Tạo bản dựng tập dữ liệu</span>
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
              <span>Tiếp theo: Chọn mô hình</span>
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
              Chọn mô hình
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Chọn kiến trúc mạng nơ-ron được cấu hình cho huấn luyện phân tán.
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
                    <span className="text-xs text-[#73737c]">{m.parameters} tham số</span>
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
              <span>Quay lại</span>
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              disabled={!selectedModel || !supportedModels.some(m => m.model_id === selectedModel)}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5"
            >
              <span>Tiếp theo: Cấu hình huấn luyện</span>
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
              Cấu hình huấn luyện
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Thiết lập siêu tham số huấn luyện và tham số đồng bộ phân tán.
            </p>
          </div>

          {/* Job Name */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <label className="block text-xs font-semibold text-[#f3f3f4]">
              Tên phiên huấn luyện
            </label>
            <input
              type="text"
              value={jobName}
              onChange={e => setJobName(e.target.value)}
              placeholder="Ví dụ: SmallCNN trên CIFAR-10"
              className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
            />
          </div>

          {/* Job Description (Optional) */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <label className="block text-xs font-semibold text-[#f3f3f4]">
              Mô tả <span className="text-[#73737c] font-normal">(Tùy chọn)</span>
            </label>
            <textarea
              rows={2}
              value={jobDescription}
              onChange={e => setJobDescription(e.target.value)}
              placeholder="Ghi chú hoặc ngữ cảnh về cấu hình huấn luyện này..."
              className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors resize-none"
            />
          </div>

          {/* Hyperparameters */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-4">
            <div className="text-xs font-semibold text-[#f3f3f4]">
              Siêu tham số
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <label className="block text-[#73737c] mb-1">
                  Số epoch
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
                  Seed
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
                  Lưu checkpoint mỗi N epoch
                </label>
                <input
                  type="number"
                  min="1"
                  max="1000"
                  step="1"
                  value={everyNEpochs}
                  onChange={e => setEveryNEpochs(Math.max(1, parseInt(e.target.value, 10) || 1))}
                  className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden transition-colors"
                />
                <span className="text-[11px] text-[#73737c] mt-1 block">
                  Chu kỳ lưu checkpoint định kỳ (mặc định 5 epochs)
                </span>
              </div>

              <div>
                <label className="block text-[#73737c] mb-1">
                  Kích thước batch (Được cấu hình trong bản dựng)
                </label>
                <input
                  type="number"
                  disabled
                  value={selectedBuild?.batch_size || 64}
                  className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.05] rounded text-xs text-[#a1a1a8] cursor-not-allowed opacity-80"
                />
                <span className="text-[11px] text-[#73737c] mt-1 block">
                  Xác định bởi bản dựng #{selectedBuildId.slice(-6)}
                </span>
              </div>
            </div>
          </div>

          {/* Distributed Strategy */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#f3f3f4]">
                Chiến lược phân tán
              </span>
              <span className="text-[11px] text-[#73737c]">{trainingStrategy === "async_sgd" ? "Async-SGD" : "Strict BSP"}</span>
            </div>

            <TrainingStrategySettings strategy={trainingStrategy} settings={asyncSettings}
              onStrategyChange={setTrainingStrategy} onSettingsChange={setAsyncSettings} />
          </div>

          {/* Workload Policy */}
          {trainingStrategy === 'strict_bsp' && (
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <div>
              <span className="text-xs font-semibold text-[#f3f3f4]">
                Chính sách phân bổ khối lượng công việc
              </span>
              <p className="text-[11px] text-[#73737c] mt-0.5">
                Kiểm soát cách phân bổ các đơn vị công việc cho các worker trong mỗi bước đồng bộ Strict BSP.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              <div
                role="radio"
                aria-checked={workloadPolicy === 'equal'}
                tabIndex={0}
                onClick={() => changeWorkloadPolicy('equal')}
                onKeyDown={e => {
                  if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    changeWorkloadPolicy('equal');
                  }
                }}
                className={`p-3.5 rounded border cursor-pointer transition-all ${
                  workloadPolicy === 'equal'
                    ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                    : 'bg-[#141416] border-white/[0.07] hover:border-white/[0.15]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                      workloadPolicy === 'equal' ? 'border-blue-500 bg-blue-600' : 'border-white/20'
                    }`}
                  >
                    {workloadPolicy === 'equal' && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="text-xs font-semibold text-[#f3f3f4]">Equal</span>
                </div>
                <p className="text-[11px] text-[#a1a1a8] mt-2 leading-relaxed">
                  Phân bổ khối lượng công việc giống nhau cho mọi worker trong từng bước. Mặc định tiêu chuẩn trong Strict BSP.
                </p>
              </div>

              <div
                role="radio"
                aria-checked={workloadPolicy === 'dbs'}
                tabIndex={0}
                onClick={() => changeWorkloadPolicy('dbs')}
                onKeyDown={e => {
                  if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    changeWorkloadPolicy('dbs');
                  }
                }}
                className={`p-3.5 rounded border cursor-pointer transition-all ${
                  workloadPolicy === 'dbs'
                    ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                    : 'bg-[#141416] border-white/[0.07] hover:border-white/[0.15]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                      workloadPolicy === 'dbs' ? 'border-blue-500 bg-blue-600' : 'border-white/20'
                    }`}
                  >
                    {workloadPolicy === 'dbs' && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="text-xs font-semibold text-[#f3f3f4]">DBS Adaptive</span>
                </div>
                <p className="text-[11px] text-[#a1a1a8] mt-2 leading-relaxed">
                  Tự động cân bằng các đơn vị công việc dựa trên tốc độ tính toán của từng worker để hạn chế worker chậm chân.
                </p>
              </div>
            </div>
            <div>
              <label htmlFor="work-units-per-step" className="block text-xs text-[#a1a1a8] mb-1">
                Work units per step (K)
              </label>
              <input
                id="work-units-per-step"
                name="work_units_per_step"
                type="number"
                min={1}
                step={1}
                required={workloadPolicy === 'dbs'}
                value={existingWups ?? ''}
                onChange={e => setExistingWups(e.target.value === '' ? undefined : Number(e.target.value))}
                className="w-full px-3 py-1.5 bg-[#171719] border border-white/[0.07] rounded text-xs text-[#f3f3f4] focus:border-blue-500 focus:outline-hidden"
              />
              <p className="text-[11px] text-[#73737c] mt-1">
                {workloadPolicy === 'dbs' ? 'K phải lớn hơn số lượng worker dự kiến.' : 'K phải bằng hoặc lớn hơn số lượng worker dự kiến. Để trống để sử dụng số lượng worker.'}
              </p>
            </div>
          </div>
          )}

          {/* Node Allocation Section */}
          <div className="p-4 bg-[#121214] border border-white/[0.07] rounded space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <span className="text-xs font-semibold text-[#f3f3f4]">
                  Phân bổ Node worker
                </span>
                <p className="text-[11px] text-[#73737c] mt-0.5">
                  Chỉ định các máy thực thi cho {requiredNodes} phân vùng dữ liệu của phiên huấn luyện.
                </p>
              </div>
              <div className="flex items-center gap-1.5 text-xs">
                <span className="text-[11px] text-[#73737c]">
                  Khả dụng:
                </span>
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  {onlineNodes.length} Online
                </span>
                {offlineNodes.length > 0 && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-[#73737c]">
                    · {offlineNodes.length} Offline
                  </span>
                )}
              </div>
            </div>

            {/* Mode Selector Tabs/Pills */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
              <button
                type="button"
                onClick={() => {
                  setNodeSelectionMode('auto');
                  setSelectedNodeIds([]);
                }}
                className={`p-3 rounded border text-left transition-all ${
                  nodeSelectionMode === 'auto'
                    ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                    : 'bg-[#141416] border-white/[0.07] hover:border-white/[0.15]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                      nodeSelectionMode === 'auto' ? 'border-blue-500 bg-blue-600' : 'border-white/20'
                    }`}
                  >
                    {nodeSelectionMode === 'auto' && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="text-xs font-semibold text-[#f3f3f4]">
                    Tự động phân bổ (Khuyên dùng)
                  </span>
                </div>
                <p className="text-[11px] text-[#73737c] mt-1.5 leading-relaxed">
                  Coordinator tự động chọn {requiredNodes} node trực tuyến tối ưu khi khởi chạy.
                </p>
              </button>

              <button
                type="button"
                onClick={() => {
                  setNodeSelectionMode('manual');
                }}
                className={`p-3 rounded border text-left transition-all ${
                  nodeSelectionMode === 'manual'
                    ? 'bg-[#171719] border-blue-500/70 shadow-xs'
                    : 'bg-[#141416] border-white/[0.07] hover:border-white/[0.15]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-3.5 h-3.5 rounded-full border flex items-center justify-center ${
                        nodeSelectionMode === 'manual' ? 'border-blue-500 bg-blue-600' : 'border-white/20'
                      }`}
                    >
                      {nodeSelectionMode === 'manual' && <span className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </span>
                    <span className="text-xs font-semibold text-[#f3f3f4]">
                      Chỉ định node thủ công
                    </span>
                  </div>
                  <span
                    className={`text-[11px] font-mono px-1.5 py-0.5 rounded ${
                      selectedNodeIds.length === requiredNodes
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-white/[0.05] text-[#a1a1a8]'
                    }`}
                  >
                    {selectedNodeIds.length}/{requiredNodes}
                  </span>
                </div>
                <p className="text-[11px] text-[#73737c] mt-1.5 leading-relaxed">
                  Tự chọn chính xác danh sách các node thực thi theo ý bạn.
                </p>
              </button>
            </div>

            {/* Manual Node Selection List */}
            {nodeSelectionMode === 'manual' && (
              <div className="space-y-2 pt-2 border-t border-white/[0.06]">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#a1a1a8]">
                    Chọn {requiredNodes} node trực tuyến ({selectedNodeIds.length} đã chọn):
                  </span>
                  {selectedNodeIds.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setSelectedNodeIds([])}
                      className="text-[11px] text-[#73737c] hover:text-[#f3f3f4] transition-colors"
                    >
                      Bỏ chọn tất cả
                    </button>
                  )}
                </div>

                {nodes.length === 0 ? (
                  <p className="text-xs text-[#73737c] py-2">Chưa có node nào được kết nối</p>
                ) : (
                  <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
                    {/* ONLINE NODES */}
                    {onlineNodes.map(node => {
                      const isChecked = selectedNodeIds.includes(node.node_id);
                      return (
                        <label
                          key={node.node_id}
                          className={`flex items-center justify-between px-3 py-2 rounded border cursor-pointer transition-colors ${
                            isChecked
                              ? 'bg-[#171719] border-blue-500/50'
                              : 'bg-[#141416] border-white/[0.05] hover:border-white/[0.1]'
                          }`}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={e =>
                                setSelectedNodeIds(ids =>
                                  e.target.checked
                                    ? [...ids, node.node_id]
                                    : ids.filter(id => id !== node.node_id)
                                )
                              }
                              className="rounded border-white/20 bg-transparent text-blue-600 focus:ring-0"
                            />
                            <div className="truncate">
                              <span className="text-xs font-medium text-[#f3f3f4]">
                                {node.display_name}
                              </span>
                              <span className="text-[11px] text-[#52525b] font-mono ml-2">
                                #{node.node_id.slice(-8)}
                              </span>
                            </div>
                          </div>
                          <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 shrink-0">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                            Online
                          </span>
                        </label>
                      );
                    })}

                    {/* OFFLINE NODES: Collapsible */}
                    {offlineNodes.length > 0 && (
                      <details className="group/offline pt-1">
                        <summary className="cursor-pointer text-[11px] text-[#73737c] hover:text-[#a1a1a8] py-1 list-none flex items-center gap-1.5 select-none">
                          <ChevronDown className="w-3 h-3 transition-transform group-open/offline:rotate-180" />
                          <span>Node ngoại tuyến ({offlineNodes.length})</span>
                        </summary>
                        <div className="space-y-1 pt-1 opacity-60">
                          {offlineNodes.map(node => (
                            <div
                              key={node.node_id}
                              className="flex items-center justify-between px-3 py-1.5 rounded border border-white/[0.03] bg-[#121214] text-xs text-[#73737c]"
                            >
                              <div className="flex items-center gap-2.5 truncate">
                                <input type="checkbox" disabled className="rounded border-white/10 opacity-30 cursor-not-allowed" />
                                <span className="truncate">{node.display_name}</span>
                                <span className="text-[10px] text-[#52525b] font-mono">#{node.node_id.slice(-8)}</span>
                              </div>
                              <span className="text-[10px] text-[#73737c] shrink-0">Offline</span>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Navigation */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Quay lại</span>
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
                  <span>Đang xác thực hợp đồng...</span>
                </>
              ) : (
                <>
                  <span>Tiếp theo: Xem lại & Xác thực</span>
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
              Xem lại cấu hình huấn luyện
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Đã hoàn tất xác thực hợp đồng với Coordinator Parameter Server.
            </p>
          </div>

          {/* Validation Warnings */}
          {hasValidationWarnings && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded text-xs text-amber-300 space-y-1">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>Cảnh báo hợp đồng</span>
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
                <span>Lỗi xác thực hợp đồng (Không thể bắt đầu)</span>
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
                <div className="text-xs text-[#73737c]">Bản dựng tập dữ liệu</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5 font-mono">
                  {selectedBuildId}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.dataset?.total_train_samples ? `${preview.dataset.total_train_samples.toLocaleString()} mẫu` : 'Sẵn sàng'} · Batch size {preview?.dataset?.batch_size || selectedBuild?.batch_size || 64} · {preview?.dataset?.steps_per_epoch ? `${preview.dataset.steps_per_epoch} bước/epoch` : ''}
              </div>
            </div>

            {/* Model Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Kiến trúc mô hình</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  {preview?.model?.architecture_name || selectedModel}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.model?.parameter_count ? `${(preview.model.parameter_count / 1_000_000).toFixed(1)}M tham số` : 'Mạng nơ-ron'}
              </div>
            </div>

            {/* Training Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Siêu tham số huấn luyện</div>
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
                <div className="text-xs text-[#73737c]">Chiến lược phân tán & Tải công việc</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  Strict BSP · Phân bổ {workloadPolicy === 'dbs' ? 'DBS Adaptive' : 'Equal'}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {preview?.synchronization?.expected_workers || 3} Worker dự kiến
                {preview?.workload?.work_units_per_step ? ` · ${preview.workload.work_units_per_step} đơn vị công việc/bước` : ''} · DTP v{preview?.protocols?.dtp_version ?? 1} / MCP v{preview?.protocols?.mcp_version ?? 1}
              </div>
            </div>

            {/* Node Allocation Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Phân bổ Node worker</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  {selectedNodeIds.length > 0
                    ? `Chỉ định thủ công (${selectedNodeIds.length} node)`
                    : 'Tự động phân bổ'}
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                {selectedNodeIds.length > 0
                  ? selectedNodeIds.map(id => nodes.find(n => n.node_id === id)?.display_name || id.slice(-8)).join(', ')
                  : `Coordinator tự động phân bổ ${requiredNodes} node trực tuyến`}
              </div>
            </div>

            {/* Checkpoint Section */}
            <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <div className="text-xs text-[#73737c]">Lưu checkpoint</div>
                <div className="text-sm font-medium text-[#f3f3f4] mt-0.5">
                  Mỗi {everyNEpochs} epoch
                </div>
              </div>
              <div className="text-xs text-[#a1a1a8] sm:text-right">
                Lưu tại ranh giới epoch và khi hoàn tất huấn luyện
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
              <span>Quay lại</span>
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setStep(5)}
                className="px-3.5 py-1.5 rounded text-xs text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#121214] border border-white/[0.07] transition-colors"
              >
                {isEditMode ? 'Lưu thay đổi' : 'Save as Draft'}
              </button>
              <button
                type="button"
                disabled={hasValidationErrors || actionLoading === 'start' || activeAttempt !== null}
                aria-busy={actionLoading === 'start'}
                onClick={handleStartTraining}
                className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:pointer-events-none"
              >
                {actionLoading === 'start'
                  ? <RefreshCw aria-hidden="true" className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                  : <Play aria-hidden="true" className="w-3.5 h-3.5 fill-current" />}
                <span>{isEditMode ? 'Bắt đầu (Start)' : 'Tạo & Bắt đầu (Start)'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {step >= 4 && activeAttempt === undefined && (
        <p className="text-xs text-amber-400">Chưa xác thực được tính sẵn sàng của phiên chạy. Tải lại trang nếu nút Bắt đầu vẫn bị vô hiệu hóa.</p>
      )}
      {activeAttempt && (
        <p className="text-xs text-amber-400">
          Một lần chạy đang diễn ra. <Link to={`/live?attempt_id=${encodeURIComponent(activeAttempt.attempt_id)}`} className="underline">Xem tiến trình</Link> trước khi bắt đầu huấn luyện mới.
        </p>
      )}

      {/* STEP 5: READY STATE (After Job creation or edit) */}
      {step === 5 && (
        <div className="p-8 bg-[#121214] border border-white/[0.07] rounded text-center space-y-4 max-w-lg mx-auto">
          <div className="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto">
            <Check className="w-5 h-5" />
          </div>

          <div>
            <h2 className="text-base font-semibold text-[#f3f3f4]">
              {isEditMode ? 'Đã cập nhật nhiệm vụ' : 'Đã tạo nhiệm vụ huấn luyện'}
            </h2>
            <p className="text-xs text-[#73737c] mt-1">
              Nhiệm vụ <strong className="text-[#f3f3f4]">{createdJob?.display_name}</strong> {isEditMode ? 'đã được cập nhật và lưu ở trạng thái BẢN NHÁP.' : 'đã được đăng ký trên hệ thống.'}
            </p>
          </div>

          <div className="flex items-center justify-center gap-3 pt-2">
            {(createdJob || jobId) && (
              <Link
                to={`/jobs/${createdJob?.job_id || jobId}`}
                className="px-3.5 py-1.5 rounded text-xs text-[#73737c] hover:text-[#f3f3f4] bg-[#171719] border border-white/[0.07] transition-colors"
              >
                Xem chi tiết nhiệm vụ
              </Link>
            )}
            <button
              type="button"
              disabled={hasValidationErrors || actionLoading === 'start' || activeAttempt !== null}
              aria-busy={actionLoading === 'start'}
              onClick={handleStartTraining}
              className="px-4 py-1.5 rounded text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:pointer-events-none"
            >
              {actionLoading === 'start'
                ? <RefreshCw aria-hidden="true" className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                : <Play aria-hidden="true" className="w-3.5 h-3.5 fill-current" />}
              <span>Bắt đầu (Start)</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
