import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ChevronRight,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { AttemptStateBadge } from '../components/common/Badge';
import {
  jobsService,
  datasetsService,
  datasetBuildsService,
  checkpointsService,
  attemptsService,
  systemService,
} from '../api';
import { AttemptListItemData, HealthData } from '../types/api';
import { deriveHealthState } from '../utils/health';
import { formatDateTime, formatStrategy } from '../utils/date';

interface ResourceState<T> {
  loading: boolean;
  error: boolean;
  data: T | null;
}

export const OverviewPage: React.FC = () => {
  const [jobsState, setJobsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [datasetsState, setDatasetsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [buildsState, setBuildsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [checkpointsState, setCheckpointsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [runningAttempt, setRunningAttempt] = useState<ResourceState<AttemptListItemData>>({ loading: true, error: false, data: null });
  const [healthState, setHealthState] = useState<ResourceState<HealthData>>({ loading: true, error: false, data: null });
  const [jobsMap, setJobsMap] = useState<Record<string, string>>({});

  const fetchOverviewData = async () => {
    setJobsState(prev => ({ ...prev, loading: true, error: false }));
    setDatasetsState(prev => ({ ...prev, loading: true, error: false }));
    setBuildsState(prev => ({ ...prev, loading: true, error: false }));
    setCheckpointsState(prev => ({ ...prev, loading: true, error: false }));
    setRunningAttempt(prev => ({ ...prev, loading: true, error: false }));
    setHealthState(prev => ({ ...prev, loading: true, error: false }));

    const [
      jobsRes,
      datasetsRes,
      buildsRes,
      checkpointsRes,
      attemptsRes,
      healthRes,
    ] = await Promise.allSettled([
      jobsService.listJobs({ limit: 100 }),
      datasetsService.listDatasets({ limit: 100 }),
      datasetBuildsService.listBuilds({ limit: 100 }),
      checkpointsService.listCheckpoints({ limit: 100 }),
      attemptsService.listAttempts({ state: 'RUNNING', limit: 1 }),
      systemService.getHealth(),
    ]);

    // Jobs
    if (jobsRes.status === 'fulfilled') {
      const data = jobsRes.value.data || [];
      setJobsState({ loading: false, error: false, data: data.length });
      const map: Record<string, string> = {};
      data.forEach(j => { map[j.job_id] = j.display_name; });
      setJobsMap(map);
    } else {
      setJobsState({ loading: false, error: true, data: null });
    }

    // Datasets
    if (datasetsRes.status === 'fulfilled') {
      setDatasetsState({ loading: false, error: false, data: datasetsRes.value.data?.length ?? 0 });
    } else {
      setDatasetsState({ loading: false, error: true, data: null });
    }

    // Builds
    if (buildsRes.status === 'fulfilled') {
      setBuildsState({ loading: false, error: false, data: buildsRes.value.data?.length ?? 0 });
    } else {
      setBuildsState({ loading: false, error: true, data: null });
    }

    // Checkpoints
    if (checkpointsRes.status === 'fulfilled') {
      setCheckpointsState({ loading: false, error: false, data: checkpointsRes.value.data?.length ?? 0 });
    } else {
      setCheckpointsState({ loading: false, error: true, data: null });
    }

    // Running attempt
    if (attemptsRes.status === 'fulfilled') {
      const active = attemptsRes.value.data && attemptsRes.value.data.length > 0 ? attemptsRes.value.data[0] : null;
      setRunningAttempt({ loading: false, error: false, data: active });
    } else {
      setRunningAttempt({ loading: false, error: true, data: null });
    }

    // Health
    if (healthRes.status === 'fulfilled') {
      setHealthState({ loading: false, error: false, data: healthRes.value.data });
    } else {
      setHealthState({ loading: false, error: true, data: null });
    }
  };

  useEffect(() => {
    fetchOverviewData();
  }, []);

  const isHealthy =
    deriveHealthState(healthState.data, { hasNetworkError: healthState.error }) === 'healthy';

  const isTrainingActive = runningAttempt.data !== null && runningAttempt.data.state === 'RUNNING';

  return (
    <div className="w-full space-y-8 pb-12 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#f3f3f4]">
            Tổng quan
          </h1>
          <p className="text-xs text-[#73737c] mt-0.5">
            Trạng thái cụm phân tán và tiến trình huấn luyện
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isTrainingActive && (
            <Link
              to={`/live?attempt_id=${encodeURIComponent(runningAttempt.data?.attempt_id || '')}`}
              className="px-3 py-1.5 rounded text-xs font-normal text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              Huấn luyện trực tiếp
            </Link>
          )}
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Tạo huấn luyện mới</span>
          </Link>
        </div>
      </div>

      {/* Cluster Health Summary Row */}
      <div className="flex items-center justify-between py-2.5 px-3 bg-[#121214] rounded border border-white/[0.07] text-xs">
        <div className="flex items-center gap-2">
          {healthState.loading ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 text-blue-400 animate-spin" />
              <span className="text-[#a1a1a8]">Đang kiểm tra kết nối cụm...</span>
            </>
          ) : (
            <>
              <span className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className="text-[#f3f3f4] font-medium">
                {isHealthy ? 'Cụm hoạt động bình thường' : 'Cụm cần chú ý'}
              </span>
              <span className="text-[#73737c]">·</span>
              <span className="text-[#a1a1a8]">
                {isHealthy
                  ? 'Tất cả dịch vụ đã kết nối và phản hồi'
                  : healthState.error
                  ? 'Không thể kết nối API Coordinator'
                  : 'Phát hiện hệ thống phụ đang suy giảm'}
              </span>
            </>
          )}
        </div>
        <Link to="/system" className="text-[#73737c] hover:text-[#f3f3f4] transition-colors text-xs">
          Chi tiết hệ thống →
        </Link>
      </div>

      {/* Active Training Run Section OR Getting Started Guide */}
      {!isTrainingActive ? (
        <div className="p-6 bg-[#121214] border border-white/[0.07] rounded space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Bắt đầu huấn luyện
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Thực hiện ba bước đơn giản để khởi chạy huấn luyện phân tán trên cụm worker.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">1</span>
                <span>Chọn tập dữ liệu</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Chọn dữ liệu huấn luyện đã xác thực và bản dựng phân vùng.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">2</span>
                <span>Cấu hình mô hình & huấn luyện</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Chọn kiến trúc mạng nơ-ron và thiết lập siêu tham số.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">3</span>
                <span>Bắt đầu huấn luyện phân tán</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Khởi chạy thực thi đồng bộ và theo dõi tiến trình trực tiếp.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 pt-1">
            <Link
              to="/training/new"
              className="px-3.5 py-1.5 rounded text-xs font-normal text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5 text-[#73737c]" />
              <span>Bắt đầu cấu hình</span>
            </Link>
            <Link
              to="/datasets"
              className="px-3.5 py-1.5 rounded text-xs text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              Xem tập dữ liệu
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.07] pb-2">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-[#f3f3f4]">
                {jobsMap[runningAttempt.data?.job_id || ''] || 'Tiến trình huấn luyện đang chạy'}
              </h2>
              <AttemptStateBadge state={runningAttempt.data?.state || 'RUNNING'} />
            </div>

            <Link
              to={`/live?attempt_id=${encodeURIComponent(runningAttempt.data?.attempt_id || '')}`}
              className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
            >
              Xem trực tiếp
            </Link>
          </div>

          {/* Quick Attempt Info */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 pt-2">
            <div>
              <div className="text-xs text-[#73737c]">Nhiệm vụ (Job)</div>
              <div className="text-xs font-medium text-[#f3f3f4] mt-0.5 truncate">
                {jobsMap[runningAttempt.data?.job_id || ''] || 'Đang huấn luyện'}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Chiến lược</div>
              <div className="text-xs font-medium text-[#f3f3f4] mt-0.5 truncate">
                {formatStrategy(runningAttempt.data?.training_strategy)}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Chế độ thực thi</div>
              <div className="text-xs font-semibold text-[#f3f3f4] mt-0.5">
                {runningAttempt.data?.execution_mode || 'FRESH'}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Thời gian bắt đầu</div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                {formatDateTime(runningAttempt.data?.started_at)}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cluster Resources Quick Strip */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-[#f3f3f4]">
          Tài nguyên
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Link
            to="/jobs"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Nhiệm vụ huấn luyện</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {jobsState.loading ? 'Đang tải...' : jobsState.error ? 'Không khả dụng' : `${jobsState.data} đã đăng ký`}
              </div>
            </div>

            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/datasets"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Tập dữ liệu</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {datasetsState.loading || buildsState.loading
                  ? 'Đang tải...'
                  : datasetsState.error && buildsState.error
                  ? 'Không khả dụng'
                  : `${datasetsState.data ?? 0} tập dữ liệu · ${buildsState.data ?? 0} bản dựng`}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/checkpoints"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Checkpoints</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {checkpointsState.loading ? 'Đang tải...' : checkpointsState.error ? 'Không khả dụng' : `${checkpointsState.data} bản lưu`}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/system"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Node cụm</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {healthState.loading ? 'Đang kiểm tra...' : healthState.error ? 'Không khả dụng' : isHealthy ? 'Hoạt động tốt' : 'Cần chú ý'}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>
        </div>
      </div>
    </div>
  );
};
