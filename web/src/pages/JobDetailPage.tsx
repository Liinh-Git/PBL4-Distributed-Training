import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Play,
  Pencil,
  Copy,
  Archive,
  ChevronDown,
  Activity,
  RefreshCw,
  AlertCircle,
  RotateCcw,
  ExternalLink,
  ChevronRight,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { JobStateBadge, AttemptStateBadge } from '../components/common/Badge';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { EditJobModal } from '../components/common/EditJobModal';
import { ResumeCheckpointModal } from '../components/common/ResumeCheckpointModal';
import { EmptyState } from '../components/common/EmptyState';
import { JobRunSummary, formatExecutionMode, formatRunTime } from '../components/training/JobRunSummary';
import { formatDateOnly } from '../utils/date';
import { jobsService, attemptsService, datasetsService, datasetBuildsService } from '../api';
import { isActiveAttempt } from '../api/attempts';
import { JobDetailData, AttemptListItemData } from '../types/api';
import { LiveTrainingPage } from './LiveTrainingPage';

const formatModelName = (modelId?: string | null, archName?: string | null): string => {
  if (archName && archName !== 'resnet18' && archName !== 'neural_network') return archName;
  if (!modelId) return 'ResNet-18';
  if (modelId === 'resnet18_groupnorm') return 'ResNet-18 (GroupNorm)';
  if (modelId === 'resnet18_standard') return 'ResNet-18 (Standard)';
  return modelId
    .replace(/^model_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
};

const formatCheckpointPolicy = (
  policy?: import('../types/api').ResolvedCheckpointPolicyData | null,
  reqCheckpoint?: import('../types/api').RequestedCheckpointPolicyData | null
): string => {
  const n = policy?.every_n_epochs ?? reqCheckpoint?.every_n_epochs;
  if (n) {
    return `Mỗi ${n} epoch`;
  }
  if (!policy?.type) return 'Mỗi 5 epoch';
  return policy.type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
};

const formatStrategy = (strategy?: string | null): string => {
  if (!strategy) return 'Đồng bộ chặt';
  const s = strategy.toLowerCase();
  if (s.includes('bsp') || s.includes('strict')) return 'Đồng bộ chặt';
  if (s === 'dbs') return 'Lập lịch thích ứng (DBS)';
  return 'Đồng bộ chặt';
};

export const JobDetailPage: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedAttemptId = searchParams.get('attempt_id') || searchParams.get('attemptId');
  const { setRawContractModalJob } = useApp();

  const [job, setJob] = useState<JobDetailData | null>(null);
  const [attempts, setAttempts] = useState<AttemptListItemData[]>([]);
  const [historyNextCursor, setHistoryNextCursor] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [systemActiveAttempt, setSystemActiveAttempt] = useState<AttemptListItemData | null | undefined>();
  const launching = useRef(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const [showEditModal, setShowEditModal] = useState(false);
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [showStartDraftConfirm, setShowStartDraftConfirm] = useState(false);
  const [showResumeModal, setShowResumeModal] = useState(false);
  const [datasetInfo, setDatasetInfo] = useState<{
    datasetId: string;
    name: string;
  } | null>(null);

  const loadJobData = useCallback(async () => {
    if (!jobId) return;
    try {
      setLoading(true);
      setSystemActiveAttempt(undefined);
      setError(null);
      setHistoryError(null);

      const [jobRes, attemptsRes, activeRes] = await Promise.allSettled([
        jobsService.getJob(jobId),
        attemptsService.listAttempts({ job_id: jobId, limit: 50 }),
        attemptsService.getActiveAttempt(),
      ]);

      if (jobRes.status === 'fulfilled') {
        const jobData = jobRes.value.data;
        setJob(jobData);
        try {
          sessionStorage.setItem(`pbl4_job_title_${jobId}`, jobData.display_name);
        } catch {}

        const buildId = jobData.requested_contract?.dataset_build_id;
        if (buildId) {
          Promise.allSettled([
            datasetBuildsService.getBuild(buildId),
            datasetsService.listDatasets({ limit: 100 }),
          ]).then(([buildRes, datasetsRes]) => {
            let targetDatasetId: string | null = null;
            if (buildRes.status === 'fulfilled' && buildRes.value.data) {
              targetDatasetId = buildRes.value.data.dataset_id;
            }

            let dsName: string | null = null;
            if (datasetsRes.status === 'fulfilled' && datasetsRes.value.data) {
              const allDatasets = datasetsRes.value.data;
              if (targetDatasetId) {
                const found = allDatasets.find(d => d.dataset_id === targetDatasetId);
                if (found) dsName = found.name;
              }
              if (!dsName) {
                const foundByBuild = allDatasets.find(d => d.dataset_id === buildId);
                if (foundByBuild) {
                  dsName = foundByBuild.name;
                  targetDatasetId = foundByBuild.dataset_id;
                } else {
                  const cifar = allDatasets.find(d => d.dataset_id.toLowerCase().includes('cifar') || d.name.toLowerCase().includes('cifar'));
                  if (cifar) {
                    dsName = cifar.name;
                    targetDatasetId = cifar.dataset_id;
                  }
                }
              }
            }

            if (targetDatasetId || dsName) {
              setDatasetInfo({
                datasetId: targetDatasetId || 'cifar10',
                name: dsName || (targetDatasetId?.toLowerCase().includes('cifar') ? 'CIFAR-10' : targetDatasetId || 'Dataset'),
              });
            }
          }).catch(() => {
            // Gracefully ignore
          });
        }
      } else {
        throw jobRes.reason;
      }

      if (attemptsRes.status === 'fulfilled') {
        setAttempts(attemptsRes.value.data);
        setHistoryNextCursor(attemptsRes.value.page?.next_cursor ?? null);
      } else {
        throw attemptsRes.reason;
      }
      if (activeRes.status === 'fulfilled') {
        setSystemActiveAttempt(activeRes.value);
      } else {
        throw activeRes.reason;
      }
    } catch (err: any) {
      setError(err?.message || `Job specification "${jobId}" could not be loaded`);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const loadMoreHistory = async () => {
    if (!jobId || !historyNextCursor || historyLoading) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await attemptsService.listAttempts({ job_id: jobId, cursor: historyNextCursor, limit: 50 });
      setAttempts(previous => {
        const ids = new Set(previous.map(attempt => attempt.attempt_id));
        return [...previous, ...res.data.filter(attempt => !ids.has(attempt.attempt_id))];
      });
      setHistoryNextCursor(res.page?.next_cursor ?? null);
    } catch (err: any) {
      setHistoryError(err?.message || 'Could not load older attempts. Try again.');
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadJobData();
  }, [loadJobData]);

  if (selectedAttemptId) {
    return (
      <LiveTrainingPage
        attemptIdOverride={selectedAttemptId}
        defaultTab="metrics"
        onBack={() => {
          const next = new URLSearchParams(searchParams);
          next.delete('attempt_id');
          next.delete('attemptId');
          setSearchParams(next);
        }}
        backLabel={`Quay lại ${job?.display_name || 'Nhiệm vụ'}`}
      />
    );
  }

  if (loading && !job) {
    return (
      <div className="py-20 flex flex-col items-center justify-center gap-3 text-xs text-[#73737c]">
        <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
        <span>Loading training job specification...</span>
      </div>
    );
  }

  if (!job) {
    return (
      <EmptyState
        title="Training Job Not Found"
        description={error || `No job specification with identifier "${jobId}" was found.`}
        action={
          <Link
            to="/jobs"
            className="px-3 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-[#f3f3f4] text-xs font-medium border border-white/[0.08]"
          >
            Return to Jobs
          </Link>
        }
      />
    );
  }

  const handleLaunch = async () => {
    if (!job || !canLaunch || launching.current) return;
    launching.current = true;
    try {
      setActionLoading('launch');
      await attemptsService.assertNoActiveAttempt();
      const res = await jobsService.startJob(job.job_id);
      navigate(`/live?attempt_id=${encodeURIComponent(res.data.attempt_id)}`);
    } catch (err: any) {
      alert(`Failed to launch training run: ${err?.message || 'Unknown error'}`);
      void loadJobData();
    } finally {
      launching.current = false;
      setActionLoading(null);
    }
  };

  const handleClone = async () => {
    if (!job) return;
    try {
      setActionLoading('clone');
      const res = await jobsService.cloneJob(job.job_id);
      navigate(`/jobs/${res.data.job_id}`);
    } catch (err: any) {
      alert(`Failed to clone job: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleArchive = async () => {
    if (!job) return;
    try {
      setActionLoading('archive');
      await jobsService.archiveJob(job.job_id);
      setShowArchiveConfirm(false);
      navigate('/jobs');
    } catch (err: any) {
      alert(`Failed to archive job: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const req = job.requested_contract;
  const resv = job.resolved_contract;
  const activeAttempt = attempts.find(a => a.job_id === jobId && isActiveAttempt(a.state))
    ?? (systemActiveAttempt?.job_id === jobId ? systemActiveAttempt : null);
  const hasActiveAttempt = Boolean(activeAttempt);
  const canLaunch = !loading && systemActiveAttempt === null && !activeAttempt && !actionLoading;
  const latestAttempt = attempts[0];

  const handleOpenRawContract = () => {
    // Adapter to legacy format for modal view if requested
    const modalJobAdapter: any = {
      id: job.job_id,
      name: job.display_name,
      jobState: job.state,
      datasetBuildId: req.dataset_build_id,
      datasetName: req.dataset_build_id,
      modelId: req.model_id,
      strategy: req.training_strategy,
      attemptsCount: attempts.length,
      latestAttemptId: latestAttempt?.attempt_id || '',
      latestAttemptState: latestAttempt?.state || 'CREATED',
      createdAt: job.created_at,
      frozenAt: job.frozen_at || null,
      requestedContract: req,
      resolvedContract: resv,
    };
    setRawContractModalJob(modalJobAdapter);
  };

  return (
    <div className="space-y-6 w-full pb-10 font-sans">
      {error && (
        <div className="text-xs text-rose-300" role="alert">
          Không thể xác minh tính khả dụng của lần chạy: {error}{' '}
          <button type="button" onClick={loadJobData} className="underline">Làm mới</button>
        </div>
      )}
      {systemActiveAttempt && systemActiveAttempt.job_id !== jobId && (
        <p className="text-xs text-amber-400">
          Cụm đang có một phiên huấn luyện của nhiệm vụ khác đang hoạt động. <Link to={`/live?attempt_id=${encodeURIComponent(systemActiveAttempt.attempt_id)}`} className="underline">Xem phiên chạy</Link> trước khi khởi chạy nhiệm vụ này.
        </p>
      )}

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.07]">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-lg font-semibold text-[#f3f3f4]">
              {job.display_name}
            </h1>
          </div>
          {job.description && (
            <p className="text-xs text-[#73737c] max-w-2xl">
              {job.description}
            </p>
          )}
          <div className="text-[11px] text-[#73737c] pt-0.5">
            Ngày tạo: {formatDateOnly(job.created_at)}
            {job.frozen_at && ` · Khóa lúc: ${formatDateOnly(job.frozen_at)}`}
          </div>
        </div>

        {/* Action hierarchy */}
        <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
          {(job.state === 'DRAFT' || job.state === 'READY') && !hasActiveAttempt && (
            <button
              type="button"
              onClick={() => setShowEditModal(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-normal rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] transition-colors border border-white/[0.07] cursor-pointer"
            >
              <Pencil className="w-3.5 h-3.5 text-[#73737c]" />
              <span>{job.state === 'DRAFT' ? 'Sửa bản nháp' : 'Chỉnh sửa'}</span>
            </button>
          )}

          <button
            type="button"
            disabled={actionLoading === 'clone'}
            onClick={handleClone}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-normal rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] transition-colors border border-white/[0.07] disabled:opacity-50"
          >
            <Copy className="w-3.5 h-3.5 text-[#73737c]" />
            <span>{actionLoading === 'clone' ? 'Đang clone...' : 'Clone'}</span>
          </button>

          {activeAttempt && (
            <Link to={`/live?attempt_id=${encodeURIComponent(activeAttempt.attempt_id)}`}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white">
              <Activity className="w-3.5 h-3.5" />Xem trực tiếp
            </Link>
          )}
          {job.state === 'READY' && !hasActiveAttempt && (
            <button type="button" disabled={!canLaunch} onClick={() => setShowResumeModal(true)}
              className="inline-flex items-center gap-1.5 rounded border border-white/[0.07] bg-[#171719] px-3 py-1.5 text-xs text-[#f3f3f4] hover:bg-[#202024] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
              <RotateCcw className="h-3.5 w-3.5 text-[#a1a1a8]" />
              Khôi phục từ checkpoint
            </button>
          )}
          {(job.state === 'READY' || job.state === 'DRAFT') && !hasActiveAttempt && (
            <button
              type="button"
              disabled={!canLaunch}
              aria-busy={actionLoading === 'launch'}
              onClick={() => {
                if (job.state === 'DRAFT') {
                  setShowStartDraftConfirm(true);
                } else {
                  handleLaunch();
                }
              }}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              {actionLoading === 'launch'
                ? <RefreshCw aria-hidden="true" className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                : <Play aria-hidden="true" className="w-3.5 h-3.5" />}
              <span>Bắt đầu chạy</span>
            </button>
          )}

          {job.state !== 'ARCHIVED' && (
            <button
              type="button"
              disabled={actionLoading === 'archive'}
              onClick={() => setShowArchiveConfirm(true)}
              className="p-1.5 rounded text-[#73737c] hover:text-rose-400 hover:bg-[#171719] transition-colors border border-transparent hover:border-white/[0.07] disabled:opacity-50"
              title="Lưu trữ nhiệm vụ"
              aria-label="Lưu trữ nhiệm vụ"
            >
              <Archive className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      <JobRunSummary attempt={activeAttempt ?? latestAttempt} jobState={job.state} historyAvailable={!loading && !error} jobId={job.job_id} />

      {/* Section: Configuration */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-xs font-semibold text-[#f3f3f4]">Cấu hình huấn luyện</h2>
          <JobStateBadge state={job.state} />
        </div>
        <p className="text-xs text-[#73737c]">
          {job.state === 'DRAFT'
            ? 'Chỉnh sửa cài đặt huấn luyện trước khi khởi chạy. Khi bắt đầu huấn luyện, cấu hình sẽ được khóa cố định.'
            : 'Mỗi lần chạy sử dụng cấu hình huấn luyện đã khóa này. Clone để điều chỉnh cấu hình.'}
          {' '}Bắt đầu chạy để bắt đầu từ đầu; Khôi phục từ checkpoint để tiếp tục tiến trình huấn luyện đã lưu.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          {/* Card 1: Dữ liệu & Mô hình */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
            <div className="text-[11px] font-medium text-[#73737c] uppercase tracking-wider">
              Dữ liệu & Mô hình
            </div>
            <dl className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <dt className="text-[#73737c] shrink-0">Tập dữ liệu</dt>
                <dd className="font-medium text-[#f3f3f4] text-right">
                  {datasetInfo ? (
                    <Link
                      to={`/datasets/${encodeURIComponent(datasetInfo.datasetId)}`}
                      className="hover:text-blue-400 transition-colors inline-flex items-center gap-1 group/ds"
                      title={`Xem Dataset: ${datasetInfo.name}`}
                    >
                      <span className="break-words">{datasetInfo.name}</span>
                      <ExternalLink className="w-3 h-3 text-[#73737c] opacity-0 group-hover/ds:opacity-100 transition-opacity shrink-0" />
                    </Link>
                  ) : (
                    <span>Dữ liệu phân vùng</span>
                  )}
                </dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Kích thước batch</dt>
                <dd className="font-medium text-[#f3f3f4]">
                  {resv?.dataset?.batch_size ? `${resv.dataset.batch_size} mẫu / bước` : '256 mẫu / bước'}
                </dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Kiến trúc mô hình</dt>
                <dd className="font-medium text-[#f3f3f4]">
                  {formatModelName(req.model_id, resv?.model?.architecture_name)}
                </dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Quy mô tham số</dt>
                <dd className="font-medium text-[#f3f3f4]">
                  {resv?.model?.parameter_count ? `${(resv.model.parameter_count / 1_000_000).toFixed(1)}M tham số` : 'Mạng nơ-ron'}
                </dd>
              </div>
            </dl>
          </div>

          {/* Card 2: Huấn luyện & Phân tán */}
          <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
            <div className="text-[11px] font-medium text-[#73737c] uppercase tracking-wider">
              Huấn luyện & Phân tán
            </div>
            <dl className="space-y-2.5">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-[#73737c]">Số epoch</dt>
                <dd className="font-medium text-[#f3f3f4]">{req.epochs} epochs</dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Learning rate</dt>
                <dd className="font-medium text-[#f3f3f4]">{req.learning_rate}</dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Seed</dt>
                <dd className="font-medium text-[#f3f3f4]">{req.training_seed}</dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Chiến lược phân tán</dt>
                <dd className="font-medium text-[#f3f3f4]">{formatStrategy(req.training_strategy)}</dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Số lượng Worker</dt>
                <dd className="font-medium text-[#f3f3f4]">
                  {resv?.synchronization?.expected_workers != null ? `${resv.synchronization.expected_workers} Workers` : 'Chưa xác định'}
                </dd>
              </div>

              <div className="flex items-center justify-between gap-3 pt-2 border-t border-white/[0.04]">
                <dt className="text-[#73737c]">Lưu checkpoint</dt>
                <dd className="font-medium text-[#f3f3f4] text-right">
                  <span>{formatCheckpointPolicy(resv?.checkpoint_policy, req?.checkpoint)}</span>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </div>

      {/* Execution Attempts History */}
      <details className="group/history space-y-3 border-t border-white/[0.07] pt-4">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded text-xs text-[#f3f3f4] focus-visible:outline-2 focus-visible:outline-blue-500 [&::-webkit-details-marker]:hidden">
          <span className="font-semibold">Lịch sử lần chạy <span className="font-normal text-[#73737c]">· {error || loading ? 'Không khả dụng' : `${attempts.length} ${historyNextCursor ? 'đã tải' : 'lần chạy'}`}</span></span>
          <ChevronDown aria-hidden="true" className="h-3.5 w-3.5 text-[#73737c] transition-transform group-open/history:rotate-180" />
        </summary>
        <p className="text-xs text-[#73737c]">Mỗi lần khởi chạy, thử lại hoặc tiếp tục sẽ tạo một Lần chạy riêng biệt. Lịch sử các lần chạy trước được lưu trữ tại đây.</p>

        <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs min-w-[850px]">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                  <th className="py-2.5 px-3 font-medium">Lần chạy</th>
                  <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                  <th className="py-2.5 px-3 font-medium">Chế độ</th>
                  <th className="py-2.5 px-3 font-medium">Chiến lược</th>
                  <th className="py-2.5 px-3 font-medium">Mã lỗi</th>
                  <th className="py-2.5 px-3 font-medium">Bắt đầu</th>
                  <th className="py-2.5 px-3 font-medium">Kết thúc</th>
                  <th className="py-2.5 px-3 font-medium text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {error || loading ? (
                  <tr><td colSpan={8} className="py-8 text-center text-[#73737c]">{loading ? 'Đang tải lịch sử lần chạy…' : 'Không thể tải lịch sử. Vui lòng thử lại.'}</td></tr>
                ) : attempts.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-[#73737c]">
                      Chưa có lần chạy nào được ghi nhận cho nhiệm vụ này.
                    </td>
                  </tr>
                ) : (
                  attempts.map((att, idx) => (
                    <tr key={att.attempt_id} className="hover:bg-[#171719] transition-colors">
                      <td className="py-2.5 px-3">
                        <Link
                          to={isActiveAttempt(att.state)
                            ? `/live?attempt_id=${encodeURIComponent(att.attempt_id)}&tab=live`
                            : `/jobs/${encodeURIComponent(jobId!)}?attempt_id=${encodeURIComponent(att.attempt_id)}`}
                          className="font-medium text-[#f3f3f4] hover:text-blue-400 transition-colors"
                          title="Xem chi tiết lần chạy"
                        >
                          Lần chạy #{attempts.length - idx}
                        </Link>
                      </td>
                      <td className="py-2.5 px-3">
                        <AttemptStateBadge state={att.state} />
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {formatExecutionMode(att.execution_mode)}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c]">
                        {formatStrategy(att.training_strategy)}
                      </td>
                      <td className="py-2.5 px-3 text-rose-400 font-mono text-[11px]">
                        {att.failure_code || '—'}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-xs">
                        {formatRunTime(att.started_at)}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-xs">
                        {formatRunTime(att.ended_at)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {isActiveAttempt(att.state) ? (
                          <Link
                            to={`/live?attempt_id=${encodeURIComponent(att.attempt_id)}&tab=live`}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 text-xs font-medium transition-colors border border-blue-500/20"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                            <span>Xem trực tiếp</span>
                          </Link>
                        ) : (
                          <Link
                            to={`/jobs/${encodeURIComponent(jobId!)}?attempt_id=${encodeURIComponent(att.attempt_id)}`}
                            className="text-xs text-blue-400 hover:underline"
                          >
                            Xem kết quả
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
        {historyError && <p role="alert" className="text-xs text-rose-300">{historyError}</p>}
        {historyNextCursor && !error && !loading && (
          <button type="button" onClick={loadMoreHistory} disabled={historyLoading}
            className="rounded border border-white/[0.07] px-3 py-1.5 text-xs text-[#a1a1a8] hover:text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
            {historyLoading ? 'Đang tải thêm lần chạy cũ…' : 'Tải thêm lần chạy cũ'}
          </button>
        )}
      </details>

      {/* Start DRAFT Job Confirmation Modal */}
      {showResumeModal && (
        <ResumeCheckpointModal key={job.job_id} jobId={job.job_id}
          canResume={job.state === 'READY' && canLaunch}
          onClose={() => setShowResumeModal(false)}
          onResumed={attemptId => navigate(`/live?attempt_id=${encodeURIComponent(attemptId)}`)}
        />
      )}

      <ConfirmationModal
        isOpen={showStartDraftConfirm}
        isLoading={actionLoading === 'launch'}
        closeOnConfirm={false}
        onClose={() => setShowStartDraftConfirm(false)}
        onConfirm={async () => {
          await handleLaunch();
          setShowStartDraftConfirm(false);
        }}
        title="Bắt đầu chạy huấn luyện?"
        confirmLabel="Khóa & Bắt đầu chạy"
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Nhiệm vụ <strong className="text-[#f3f3f4]">{job.display_name}</strong> đang ở trạng thái <span className="font-mono text-[#f3f3f4]">Bản nháp (DRAFT)</span>.
            </p>
            <p>
              Khởi chạy nhiệm vụ sẽ xác thực và khóa cấu hình chuyển sang trạng thái <span className="font-mono text-[#f3f3f4]">Sẵn sàng (READY)</span>. Khi đã khóa, cấu hình huấn luyện không thể chỉnh sửa trực tiếp mà cần Clone nếu muốn điều chỉnh.
            </p>
          </div>
        }
      />

      {/* Archive Confirmation Modal */}
      <ConfirmationModal
        isOpen={showArchiveConfirm}
        onClose={() => setShowArchiveConfirm(false)}
        onConfirm={handleArchive}
        title="Lưu trữ nhiệm vụ huấn luyện?"
        confirmLabel="Lưu trữ"
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Bạn có chắc chắn muốn lưu trữ nhiệm vụ <strong className="text-[#f3f3f4]">{job.display_name}</strong>?
            </p>
            <p>
              Cấu hình nhiệm vụ sẽ bị ẩn khỏi danh sách khởi chạy mới. Lịch sử các lần chạy và checkpoints đã lưu vẫn được bảo lưu đầy đủ.
            </p>
          </div>
        }
      />

      {/* Edit Job Modal */}
      <EditJobModal
        job={job}
        isOpen={showEditModal}
        onClose={() => setShowEditModal(false)}
        onSuccess={() => {
          setShowEditModal(false);
          loadJobData();
        }}
      />
    </div>
  );
};
