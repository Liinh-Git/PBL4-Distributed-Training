import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Search, RotateCcw, Plus, Activity } from 'lucide-react';
import { attemptsService, jobsService, datasetsService, datasetBuildsService, systemService } from '../api';
import {
  AttemptListItemData,
  JobListItemData,
  DatasetItemData,
  CapabilitiesData,
  AttemptState,
} from '../types/api';
import { AttemptStateBadge } from '../components/common/Badge';
import { formatDateTime, formatStrategy } from '../utils/date';
import { LiveTrainingPage } from './LiveTrainingPage';

export interface EnrichedRunItem {
  attemptId: string;
  jobId: string;
  jobName: string;
  runNumber: number | null;
  state: AttemptState;
  executionMode: string;
  trainingStrategy?: string | null;
  modelId?: string | null;
  modelDisplayName: string;
  datasetId?: string | null;
  datasetName: string;
  batchSize?: number | null;
  createdAt: string;
  startedAt?: string | null;
  endedAt?: string | null;
  durationText: string;
  failureCode?: string | null;
}

export const TrainingRunsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Raw API state
  const [attempts, setAttempts] = useState<AttemptListItemData[]>([]);
  const [jobs, setJobs] = useState<JobListItemData[]>([]);
  const [datasets, setDatasets] = useState<DatasetItemData[]>([]);
  const [buildDatasetIds, setBuildDatasetIds] = useState<Record<string, string>>({});
  const [capabilities, setCapabilities] = useState<CapabilitiesData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [nextRunsCursor, setNextRunsCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const historyControllerRef = useRef<AbortController | null>(null);
  const loadingMoreRef = useRef(false);

  // Filter state
  const [searchQuery, setSearchQuery] = useState<string>(searchParams.get('q') || '');
  const [selectedJobId, setSelectedJobId] = useState<string>(searchParams.get('job') || 'all');
  const [selectedModel, setSelectedModel] = useState<string>(searchParams.get('model') || 'all');
  const [selectedDataset, setSelectedDataset] = useState<string>(searchParams.get('data') || 'all');
  const [selectedState, setSelectedState] = useState<string>(searchParams.get('state') || 'all');

  // Load all initial data
  useEffect(() => {
    let isMounted = true;
    const controller = new AbortController();
    historyControllerRef.current = controller;
    loadingMoreRef.current = false;
    const loadAll = async () => {
      try {
        setLoading(true);
        setError(null);
        const options = { signal: controller.signal };
        const [attemptsRes, jobsRes, datasetsRes, capsRes, buildsRes] = await Promise.all([
          attemptsService.listAttempts({ limit: 200 }, options),
          jobsService.listJobs({ limit: 100 }, options),
          datasetsService.listDatasets({ limit: 100 }, options),
          systemService.getCapabilities().catch(() => ({ data: null })),
          datasetBuildsService.listBuilds({ limit: 200 }, options).catch(() => ({ data: [] })),
        ]);

        if (isMounted) {
          setAttempts(attemptsRes.data || []);
          setJobs(jobsRes.data || []);
          setDatasets(datasetsRes.data || []);
          setCapabilities(capsRes.data || null);
          setBuildDatasetIds(Object.fromEntries(buildsRes.data.map(build => [build.dataset_build_id, build.dataset_id])));
          setNextRunsCursor(attemptsRes.page?.next_cursor ?? null);
          setHistoryError(null);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Không thể tải danh sách các lần huấn luyện.');
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    loadAll();
    return () => {
      isMounted = false;
      controller.abort();
    };
  }, []);

  const loadMoreRuns = async () => {
    const signal = historyControllerRef.current?.signal;
    if (!nextRunsCursor || loadingMoreRef.current || signal?.aborted) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setHistoryError(null);
    try {
      const page = await attemptsService.listAttempts({ limit: 200, cursor: nextRunsCursor }, { signal });
      if (signal?.aborted) return;
      if (page.page?.next_cursor === nextRunsCursor) throw new Error('Cursor lịch sử không tiến lên.');
      setAttempts(previous => {
        const ids = new Set(previous.map(attempt => attempt.attempt_id));
        return [...previous, ...page.data.filter(attempt => !ids.has(attempt.attempt_id))];
      });
      setNextRunsCursor(page.page?.next_cursor ?? null);
    } catch (err) {
      if (!signal?.aborted) setHistoryError(err instanceof Error ? err.message : 'Không thể tải thêm lịch sử.');
    } finally {
      if (!signal?.aborted) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  };

  const selectedAttemptId = searchParams.get('attempt_id') || searchParams.get('attemptId');

  // Sync filters with URL query parameters
  useEffect(() => {
    if (selectedAttemptId) return;
    const params = new URLSearchParams();
    if (searchQuery) params.set('q', searchQuery);
    if (selectedJobId !== 'all') params.set('job', selectedJobId);
    if (selectedModel !== 'all') params.set('model', selectedModel);
    if (selectedDataset !== 'all') params.set('data', selectedDataset);
    if (selectedState !== 'all') params.set('state', selectedState);
    setSearchParams(params, { replace: true });
  }, [searchQuery, selectedJobId, selectedModel, selectedDataset, selectedState, selectedAttemptId, setSearchParams]);

  // Compute Job map and Dataset map
  const jobMap = useMemo(() => {
    const map = new Map<string, JobListItemData>();
    jobs.forEach((j) => map.set(j.job_id, j));
    return map;
  }, [jobs]);

  // Format model display name
  const formatModel = (modelId?: string | null) => {
    if (!modelId) return 'Không khả dụng';
    const found = capabilities?.supported_models?.find((m) => m.model_id === modelId);
    if (found?.display_name) return found.display_name;
    return modelId
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  };

  // Format duration
  const formatDuration = (startedAt?: string | null, endedAt?: string | null, state?: AttemptState) => {
    if (!startedAt) return 'Chưa bắt đầu';
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start)) return 'Không khả dụng';
    if (state === 'RUNNING' || state === 'INITIALIZING' || state === 'WAITING_WORKERS' || state === 'PROVISIONING') {
      const diffSec = Math.max(0, Math.round((Date.now() - start) / 1000));
      const mins = Math.floor(diffSec / 60);
      const secs = diffSec % 60;
      return `${mins}m ${secs}s (Đang chạy)`;
    }
    if (!endedAt) return 'Không khả dụng';
    const end = new Date(endedAt).getTime();
    if (!Number.isFinite(end) || end < start) return 'Không khả dụng';
    const diffSec = Math.max(0, Math.round((end - start) / 1000));
    const mins = Math.floor(diffSec / 60);
    const secs = diffSec % 60;
    return `${mins}m ${secs}s`;
  };

  // Group attempts by job to compute chronological Run #1, Run #2 ...
  const enrichedRuns = useMemo((): EnrichedRunItem[] => {
    const byJob = new Map<string, AttemptListItemData[]>();
    attempts.forEach((att) => {
      const list = byJob.get(att.job_id) || [];
      list.push(att);
      byJob.set(att.job_id, list);
    });

    const runNumMap = new Map<string, number>();
    byJob.forEach((list, jobId) => {
      list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      const job = jobMap.get(jobId);
      if (!job || !Number.isInteger(job.attempt_count) || job.attempt_count < list.length
        || job.latest_attempt?.attempt_id !== list[0]?.attempt_id) return;
      list.forEach((att, idx) => {
        runNumMap.set(att.attempt_id, job.attempt_count - idx);
      });
    });

    return attempts
      .map((att) => {
        const job = jobMap.get(att.job_id);
        const jobName = job?.display_name || att.job_id;
        const runNumber = runNumMap.get(att.attempt_id) ?? null;
        const modelDisplayName = formatModel(job?.model_id);
        const datasetId = job?.dataset_build_id ? buildDatasetIds[job.dataset_build_id] : undefined;
        const ds = datasets.find(d => d.dataset_id === datasetId);
        const datasetName = ds?.name || 'Không khả dụng';
        const durationText = formatDuration(att.started_at, att.ended_at, att.state);

        return {
          attemptId: att.attempt_id,
          jobId: att.job_id,
          jobName,
          runNumber,
          state: att.state,
          executionMode: att.execution_mode,
          trainingStrategy: att.training_strategy,
          modelId: job?.model_id,
          modelDisplayName,
          datasetId,
          datasetName,
          createdAt: att.created_at,
          startedAt: att.startedAt || att.started_at,
          endedAt: att.endedAt || att.ended_at,
          durationText,
          failureCode: att.failure_code,
        };
      })
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [attempts, jobMap, datasets, buildDatasetIds, capabilities]);

  // Unique lists for filter dropdowns
  const availableModels = useMemo(() => {
    const set = new Set<string>();
    enrichedRuns.forEach((r) => {
      if (r.modelDisplayName) set.add(r.modelDisplayName);
    });
    return Array.from(set).sort();
  }, [enrichedRuns]);

  const availableDatasets = useMemo(() => {
    const set = new Set<string>();
    enrichedRuns.forEach((r) => {
      if (r.datasetName) set.add(r.datasetName);
    });
    return Array.from(set).sort();
  }, [enrichedRuns]);

  // Apply filters
  const filteredRuns = useMemo(() => {
    return enrichedRuns.filter((r) => {
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        const matchJob = r.jobName.toLowerCase().includes(query);
        const matchModel = r.modelDisplayName.toLowerCase().includes(query);
        const matchData = r.datasetName.toLowerCase().includes(query);
        const matchRun = r.runNumber != null
          && (`lần ${r.runNumber}`.includes(query) || `#${r.runNumber}`.includes(query));
        if (!matchJob && !matchModel && !matchData && !matchRun) {
          return false;
        }
      }

      if (selectedJobId !== 'all' && r.jobId !== selectedJobId) {
        return false;
      }

      if (selectedModel !== 'all' && r.modelDisplayName !== selectedModel) {
        return false;
      }

      if (selectedDataset !== 'all' && r.datasetName !== selectedDataset) {
        return false;
      }

      if (selectedState !== 'all') {
        if (selectedState === 'ACTIVE') {
          if (!['RUNNING', 'INITIALIZING', 'WAITING_WORKERS', 'PROVISIONING'].includes(r.state)) {
            return false;
          }
        } else if (r.state !== selectedState) {
          return false;
        }
      }

      return true;
    });
  }, [enrichedRuns, searchQuery, selectedJobId, selectedModel, selectedDataset, selectedState]);

  // Quick stats counters
  const totalCount = enrichedRuns.length;
  const runningCount = enrichedRuns.filter((r) =>
    ['RUNNING', 'INITIALIZING', 'WAITING_WORKERS', 'PROVISIONING'].includes(r.state)
  ).length;
  const completedCount = enrichedRuns.filter((r) => r.state === 'COMPLETED').length;
  const failedCount = enrichedRuns.filter((r) => r.state === 'FAILED' || r.state === 'ABORTED').length;

  const isAnyFilterActive =
    searchQuery.trim() !== '' ||
    selectedJobId !== 'all' ||
    selectedModel !== 'all' ||
    selectedDataset !== 'all' ||
    selectedState !== 'all';

  const handleResetFilters = () => {
    setSearchQuery('');
    setSelectedJobId('all');
    setSelectedModel('all');
    setSelectedDataset('all');
    setSelectedState('all');
  };

  const handleBackToRuns = () => {
    const next = new URLSearchParams(searchParams);
    next.delete('attempt_id');
    next.delete('attemptId');
    setSearchParams(next);
  };

  if (selectedAttemptId) {
    return (
      <LiveTrainingPage
        attemptIdOverride={selectedAttemptId}
        defaultTab="metrics"
        onBack={handleBackToRuns}
        backLabel="Quay lại Lịch sử Huấn luyện"
      />
    );
  }

  return (
    <div className="space-y-6 w-full pb-10 font-sans select-none">
      {/* 1. Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <h1 className="text-base font-semibold text-[#f3f3f4]">
            Lịch sử huấn luyện
          </h1>
          <p className="text-xs text-[#73737c] mt-0.5">
            Toàn bộ các phiên huấn luyện trên cụm phân tán. Nhấp vào bất kỳ lần chạy nào để xem kết quả chi tiết.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Tạo Job mới</span>
          </Link>
          <Link
            to="/live"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#a1a1a8] hover:text-[#f3f3f4] text-xs font-normal transition-colors border border-white/[0.07]"
          >
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            <span>Huấn luyện trực tiếp</span>
          </Link>
        </div>
      </div>

      {/* 2. Stats summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-3.5 rounded bg-[#121214] border border-white/[0.07] space-y-1">
          <div className="text-[11px] text-[#73737c]">Số lần chạy đã tải</div>
          <div className="text-xl font-mono font-semibold text-[#f3f3f4]">{totalCount}</div>
        </div>

        <div className="p-3.5 rounded bg-[#121214] border border-white/[0.07] space-y-1">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
            <span>Đang chạy trực tiếp</span>
          </div>
          <div className="text-xl font-mono font-semibold text-blue-400">{runningCount}</div>
        </div>

        <div className="p-3.5 rounded bg-[#121214] border border-white/[0.07] space-y-1">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span>Hoàn tất thành công</span>
          </div>
          <div className="text-xl font-mono font-semibold text-emerald-400">{completedCount}</div>
        </div>

        <div className="p-3.5 rounded bg-[#121214] border border-white/[0.07] space-y-1">
          <div className="text-[11px] text-[#73737c] flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
            <span>Thất bại / Đã dừng</span>
          </div>
          <div className="text-xl font-mono font-semibold text-rose-400">{failedCount}</div>
        </div>
      </div>

      {/* 3. Filter Bar */}
      <div className="p-3.5 rounded bg-[#121214] border border-white/[0.07] space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-[#f3f3f4]">
            Bộ lọc trên các lần chạy đã tải
          </span>
          {isAnyFilterActive && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="inline-flex items-center gap-1 text-[11px] text-[#73737c] hover:text-[#f3f3f4] transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Đặt lại bộ lọc</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5 text-xs">
          {/* Search Input */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#73737c] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              aria-label="Tìm kiếm lượt huấn luyện"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm kiếm Job, Mô hình..."
              className="w-full pl-8 pr-3 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] placeholder-[#73737c] focus:outline-none focus:border-blue-500 transition-colors"
            />
          </div>

          {/* Job Filter */}
          <select
            aria-label="Lọc theo Job"
            value={selectedJobId}
            onChange={(e) => setSelectedJobId(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
          >
            <option value="all">Tất cả Job ({jobs.length})</option>
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>
                {j.display_name}
              </option>
            ))}
          </select>

          {/* Model Filter */}
          <select
            aria-label="Lọc theo mô hình"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
          >
            <option value="all">Tất cả Mô hình</option>
            {availableModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>

          {/* Dataset Filter */}
          <select
            aria-label="Lọc theo dataset"
            value={selectedDataset}
            onChange={(e) => setSelectedDataset(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
          >
            <option value="all">Tất cả Dữ liệu</option>
            {availableDatasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>

          {/* State Filter */}
          <select
            aria-label="Lọc theo trạng thái"
            value={selectedState}
            onChange={(e) => setSelectedState(e.target.value)}
            className="w-full px-2.5 py-1.5 rounded bg-[#171719] border border-white/[0.08] text-[#f3f3f4] focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
          >
            <option value="all">Tất cả Trạng thái</option>
            <option value="ACTIVE">Đang chạy</option>
            <option value="COMPLETED">Hoàn tất</option>
            <option value="FAILED">Thất bại</option>
            <option value="ABORTED">Đã hủy</option>
          </select>
        </div>
      </div>

      {/* 4. Table */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        {loading ? (
          <div className="py-16 text-center text-xs text-[#73737c]">
            Đang tải danh sách các lần huấn luyện...
          </div>
        ) : error ? (
          <div className="py-12 text-center text-xs text-rose-300">
            {error}
          </div>
        ) : filteredRuns.length === 0 ? (
          <div className="py-16 text-center text-xs text-[#73737c] space-y-2">
            <div>Không tìm thấy lần chạy nào phù hợp với bộ lọc hiện tại.</div>
            {isAnyFilterActive && (
              <button
                type="button"
                onClick={handleResetFilters}
                className="px-3 py-1 bg-white/[0.04] hover:bg-white/[0.08] text-xs text-[#f3f3f4] rounded border border-white/[0.08] transition-colors"
              >
                Xóa bộ lọc
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs min-w-[1080px]">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                  <th className="py-2.5 px-3.5 font-medium min-w-[180px]">Nhiệm vụ</th>
                  <th className="py-2.5 px-3 font-medium min-w-[75px] w-[75px] whitespace-nowrap">Lần chạy</th>
                  <th className="py-2.5 px-3 font-medium min-w-[110px] whitespace-nowrap">Trạng thái</th>
                  <th className="py-2.5 px-3 font-medium min-w-[150px] whitespace-nowrap">Mô hình</th>
                  <th className="py-2.5 px-3 font-medium min-w-[120px] whitespace-nowrap">Chiến lược</th>
                  <th className="py-2.5 px-3 font-medium min-w-[200px]">Tập dữ liệu</th>
                  <th className="py-2.5 px-3 font-medium min-w-[145px] whitespace-nowrap">Thời gian bắt đầu</th>
                  <th className="py-2.5 px-3 font-medium min-w-[95px] whitespace-nowrap">Thời lượng</th>
                  <th className="py-2.5 px-3.5 font-medium text-right min-w-[110px] whitespace-nowrap">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {filteredRuns.map((run) => {
                  const isRunning = ['RUNNING', 'INITIALIZING', 'WAITING_WORKERS', 'PROVISIONING'].includes(run.state);
                  const targetUrl = isRunning
                    ? `/live?attempt_id=${encodeURIComponent(run.attemptId)}&tab=live`
                    : `/runs?${(() => {
                        const next = new URLSearchParams(searchParams);
                        next.set('attempt_id', run.attemptId);
                        return next.toString();
                      })()}`;

                  return (
                    <tr
                      key={run.attemptId}
                      onClick={() => navigate(targetUrl)}
                      className="hover:bg-[#171719] cursor-pointer transition-colors group"
                    >
                      {/* Job Column */}
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                        <Link
                          to={`/jobs/${run.jobId}`}
                          onClick={(e) => e.stopPropagation()}
                          className="hover:underline"
                        >
                          {run.jobName}
                        </Link>
                      </td>

                      {/* Run Number Column */}
                      <td className="py-2.5 px-3 whitespace-nowrap font-medium text-[#f3f3f4]">
                        {run.runNumber != null ? `Lần #${run.runNumber}` : 'Lượt chạy'}
                      </td>

                      {/* State */}
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <AttemptStateBadge state={run.state} />
                      </td>

                      {/* Model (No icon) */}
                      <td className="py-2.5 px-3 text-[#f3f3f4] whitespace-nowrap">
                        {run.modelDisplayName}
                      </td>

                      {/* Strategy (No icon) */}
                      <td className="py-2.5 px-3 text-[#73737c] whitespace-nowrap">
                        {formatStrategy(run.trainingStrategy)}
                      </td>

                      {/* Dataset (No icon) */}
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {run.datasetName}
                      </td>

                      {/* Started At (dd/mm/yyyy HH:mm:ss, No icon) */}
                      <td className="py-2.5 px-3 text-[#73737c] text-xs whitespace-nowrap">
                        {formatDateTime(run.startedAt)}
                      </td>

                      {/* Duration (No icon) */}
                      <td className="py-2.5 px-3 text-[#a1a1a8] text-xs whitespace-nowrap">
                        {run.durationText}
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3.5 text-right whitespace-nowrap">
                        {isRunning ? (
                          <Link
                            to={targetUrl}
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 text-xs font-medium border border-blue-500/20 transition-colors"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            <span>Xem trực tiếp</span>
                          </Link>
                        ) : (
                          <Link
                            to={targetUrl}
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#171719] hover:bg-[#202024] text-[#a1a1a8] hover:text-[#f3f3f4] text-xs transition-colors border border-white/[0.07]"
                          >
                            <span>Xem kết quả</span>
                          </Link>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {historyError && <p role="alert" className="text-xs text-rose-300">{historyError}</p>}
      {nextRunsCursor && !loading && (
        <button type="button" onClick={() => void loadMoreRuns()} disabled={loadingMore}
          aria-busy={loadingMore}
          className="rounded border border-white/[0.08] px-3 py-2 text-xs text-blue-400 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-400">
          {loadingMore ? 'Đang tải…' : 'Tải thêm lịch sử'}
        </button>
      )}
    </div>
  );
};
