import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  RotateCcw,
  Search,
  RefreshCw,
  AlertCircle,
  ChevronRight,
} from 'lucide-react';
import { CheckpointStateBadge } from '../components/common/Badge';
import { ModelDownloadLink } from '../components/common/ModelDownloadLink';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { useNavigate, Link } from 'react-router-dom';
import { attemptsService, checkpointsService, jobsService } from '../api';
import { CheckpointListItemData } from '../types/api';
import { formatDateTime } from '../utils/date';

function formatTimestamp(isoString?: string | null): string {
  return formatDateTime(isoString);
}

interface JobCheckpointGroup {
  jobId: string;
  jobName: string;
  latestCheckpoint: CheckpointListItemData;
  allCheckpoints: CheckpointListItemData[];
}

export const CheckpointsPage: React.FC = () => {
  const navigate = useNavigate();

  const [checkpoints, setCheckpoints] = useState<CheckpointListItemData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [checkpointToResume, setCheckpointToResume] = useState<CheckpointListItemData | null>(null);
  const [resuming, setResuming] = useState(false);
  const [jobNames, setJobNames] = useState<Record<string, string>>({});
  const [expandedJobIds, setExpandedJobIds] = useState<Set<string>>(new Set());
  const resumingRef = useRef(false);

  useEffect(() => {
    jobsService.listJobs({ limit: 100 }).then(res => {
      const map: Record<string, string> = {};
      res.data?.forEach(j => {
        map[j.job_id] = j.display_name;
      });
      setJobNames(map);
    }).catch(() => {});
  }, []);

  const fetchCheckpoints = async (cursor?: string | null, append = false) => {
    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const res = await checkpointsService.listCheckpoints({ cursor, limit: 50 });
      const data = res.data || [];
      setCheckpoints(prev => {
        if (!append) return data;
        const existingIds = new Set(prev.map(c => c.checkpoint_id));
        const newItems = data.filter(c => !existingIds.has(c.checkpoint_id));
        return [...prev, ...newItems];
      });
      setNextCursor(res.page?.next_cursor || null);
    } catch (err: any) {
      setError(err?.message || 'Không thể tải danh sách checkpoint');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchCheckpoints();
  }, []);

  const filteredCheckpoints = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return checkpoints;
    return checkpoints.filter(cp => {
      const jName = (jobNames[cp.job_id] || '').toLowerCase();
      return (
        cp.checkpoint_id.toLowerCase().includes(query) ||
        cp.job_id.toLowerCase().includes(query) ||
        jName.includes(query) ||
        cp.created_by_attempt_id.toLowerCase().includes(query) ||
        cp.state.toLowerCase().includes(query) ||
        (cp.epoch != null && `epoch ${cp.epoch}`.includes(query)) ||
        (cp.epoch != null && String(cp.epoch).includes(query))
      );
    });
  }, [checkpoints, searchQuery, jobNames]);

  // Group checkpoints by job_id, sorted latest first
  const jobGroups = useMemo(() => {
    const map = new Map<string, CheckpointListItemData[]>();
    for (const cp of filteredCheckpoints) {
      const list = map.get(cp.job_id);
      if (!list) {
        map.set(cp.job_id, [cp]);
      } else {
        list.push(cp);
      }
    }

    const groups: JobCheckpointGroup[] = [];
    for (const [jobId, list] of map.entries()) {
      list.sort((a, b) => {
        const timeA = new Date(a.completed_at || a.created_at).getTime();
        const timeB = new Date(b.completed_at || b.created_at).getTime();
        return timeB - timeA;
      });
      groups.push({
        jobId,
        jobName: jobNames[jobId] || jobId,
        latestCheckpoint: list[0],
        allCheckpoints: list,
      });
    }

    groups.sort((a, b) => {
      const timeA = new Date(a.latestCheckpoint.completed_at || a.latestCheckpoint.created_at).getTime();
      const timeB = new Date(b.latestCheckpoint.completed_at || b.latestCheckpoint.created_at).getTime();
      return timeB - timeA;
    });

    return groups;
  }, [filteredCheckpoints, jobNames]);

  const toggleJobExpand = (jobId: string) => {
    setExpandedJobIds(prev => {
      const next = new Set(prev);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
      }
      return next;
    });
  };

  const handleConfirmResume = async () => {
    if (resumingRef.current || !checkpointToResume || !checkpointToResume.job_id || checkpointToResume.state !== 'COMPLETE') {
      return;
    }
    resumingRef.current = true;
    setResuming(true);
    try {
      await attemptsService.assertNoActiveAttempt();
      const response = await jobsService.resumeJob(checkpointToResume.job_id, {
        checkpoint_id: checkpointToResume.checkpoint_id,
      });
      setCheckpointToResume(null);
      navigate(`/live?attempt_id=${encodeURIComponent(response.data.attempt_id)}`);
    } catch (err: any) {
      alert(`Không thể tiếp tục từ checkpoint: ${err?.message || 'Lỗi không xác định'}`);
    } finally {
      resumingRef.current = false;
      setResuming(false);
    }
  };

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Danh sách Checkpoints đã lưu
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Đang tải...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Ảnh chụp nhanh tham số mô hình đã xác thực, con trỏ phục hồi và chứng chỉ toàn vẹn.
          </p>
        </div>

        <button
          type="button"
          onClick={() => fetchCheckpoints()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#121214] border border-white/[0.07] hover:bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] text-xs font-medium transition-colors self-start sm:self-auto disabled:opacity-50"
          title="Làm mới danh sách"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Làm mới</span>
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => fetchCheckpoints()}
            className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs transition-colors"
          >
            Thử lại
          </button>
        </div>
      )}

      {/* Search Bar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
          <input
            type="text"
            placeholder="Tìm kiếm theo nhiệm vụ, epoch hoặc trạng thái..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>
      </div>

      {/* Checkpoints Table: Grouped by Job with Job column at the start */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs min-w-[760px]">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium">Nhiệm vụ</th>
                <th className="py-2.5 px-3 font-medium">Epoch</th>
                <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                <th className="py-2.5 px-3 font-medium">Thời gian hoàn tất</th>
                <th className="py-2.5 px-3.5 font-medium text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && checkpoints.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-[#73737c]">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
                      <span>Đang tải danh sách checkpoints từ API...</span>
                    </div>
                  </td>
                </tr>
              ) : jobGroups.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-10 text-center text-[#73737c]">
                    Không tìm thấy checkpoint nào phù hợp với tìm kiếm.
                  </td>
                </tr>
              ) : (
                jobGroups.map(group => {
                  const cp = group.latestCheckpoint;
                  const isRecoverable = cp.state === 'COMPLETE';
                  const isExpanded = expandedJobIds.has(group.jobId);
                  const hasMultiple = group.allCheckpoints.length > 1;

                  return (
                    <React.Fragment key={group.jobId}>
                      {/* Main row: Latest checkpoint for this Job */}
                      <tr className="hover:bg-[#171719] transition-colors">
                        {/* Column 1: Job (At the very front) */}
                        <td className="py-3 px-3.5">
                          <div className="flex items-center gap-2">
                            {hasMultiple ? (
                              <button
                                type="button"
                                onClick={() => toggleJobExpand(group.jobId)}
                                className="p-1 rounded hover:bg-white/[0.08] text-[#73737c] hover:text-[#f3f3f4] transition-colors shrink-0"
                                title={isExpanded ? 'Thu gọn các epoch cũ' : `Mở rộng xem tất cả ${group.allCheckpoints.length} epoch`}
                              >
                                <ChevronRight
                                  className={`w-3.5 h-3.5 transition-transform ${
                                    isExpanded ? 'rotate-90 text-[#f3f3f4]' : ''
                                  }`}
                                />
                              </button>
                            ) : (
                              <span className="w-5 shrink-0" />
                            )}
                            <div>
                              <Link
                                to={`/jobs/${group.jobId}`}
                                className="text-[#f3f3f4] hover:text-blue-400 font-medium transition-colors"
                                title="Xem chi tiết nhiệm vụ"
                              >
                                {group.jobName}
                              </Link>
                              {hasMultiple && (
                                <button
                                  type="button"
                                  onClick={() => toggleJobExpand(group.jobId)}
                                  className="block text-[11px] text-[#73737c] hover:text-blue-400 transition-colors mt-0.5 text-left"
                                >
                                  {isExpanded
                                    ? `Đang hiện toàn bộ ${group.allCheckpoints.length} epoch`
                                    : `+ ${group.allCheckpoints.length - 1} epoch trước đó (bấm để xem)`}
                                </button>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Column 2: Epoch */}
                        <td className="py-3 px-3 font-medium text-[#f3f3f4]">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-[#f3f3f4]">
                              {cp.epoch != null ? `Epoch ${cp.epoch}` : '—'}
                            </span>
                            {hasMultiple && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-normal">
                                Gần nhất
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Column 3: Trạng thái */}
                        <td className="py-3 px-3">
                          <CheckpointStateBadge state={cp.state} />
                        </td>

                        {/* Column 4: Thời gian hoàn tất */}
                        <td className="py-3 px-3 text-[#73737c] text-[11px]">
                          {formatTimestamp(cp.completed_at || cp.created_at)}
                        </td>

                        <td className="py-3 px-3.5 text-right">
                          <div className="flex items-center justify-end gap-2">
                            {isRecoverable && (
                              <ModelDownloadLink checkpointId={cp.checkpoint_id} />
                            )}
                            {isRecoverable && cp.job_id ? (
                              <button
                                type="button"
                                onClick={() => setCheckpointToResume(cp)}
                                className="px-3 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors inline-flex items-center gap-1.5"
                              >
                                <RotateCcw className="w-3 h-3" />
                                <span>Tiếp tục</span>
                              </button>
                            ) : (
                              <span className="text-[11px] text-[#52525b]">—</span>
                            )}
                          </div>
                        </td>
                      </tr>

                      {/* Sub-rows: Expanded remaining checkpoints */}
                      {isExpanded &&
                        group.allCheckpoints.slice(1).map((subCp, subIdx) => {
                          const subRecoverable = subCp.state === 'COMPLETE';
                          return (
                            <tr
                              key={subCp.checkpoint_id}
                              className="bg-[#0e0e10] hover:bg-[#141416] transition-colors border-l-2 border-blue-500/40"
                            >
                              {/* Indented Job sub-indicator */}
                              <td className="py-2.5 px-3.5 pl-11 text-[#73737c] text-[11px]">
                                <span className="font-mono text-[#52525b]">└</span> Checkpoint #{subIdx + 2}
                              </td>

                              {/* Epoch */}
                              <td className="py-2.5 px-3 font-medium text-[#f3f3f4]">
                                <span className="text-[#a1a1a8]">
                                  {subCp.epoch != null ? `Epoch ${subCp.epoch}` : '—'}
                                </span>
                              </td>

                              {/* State */}
                              <td className="py-2.5 px-3">
                                <CheckpointStateBadge state={subCp.state} />
                              </td>

                              {/* Time */}
                              <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                                {formatTimestamp(subCp.completed_at || subCp.created_at)}
                              </td>

                              <td className="py-2.5 px-3.5 text-right">
                                <div className="flex items-center justify-end gap-2">
                                  {subRecoverable && (
                                    <ModelDownloadLink checkpointId={subCp.checkpoint_id} />
                                  )}
                                  {subRecoverable && subCp.job_id ? (
                                    <button
                                      type="button"
                                      onClick={() => setCheckpointToResume(subCp)}
                                      className="px-2.5 py-1 text-xs rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors inline-flex items-center gap-1.5"
                                    >
                                      <RotateCcw className="w-3 h-3" />
                                      <span>Tiếp tục</span>
                                    </button>
                                  ) : (
                                    <span className="text-[11px] text-[#52525b]">—</span>
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Cursor Pagination Load More */}
        {nextCursor && (
          <div className="p-3 border-t border-white/[0.07] flex justify-center">
            <button
              type="button"
              onClick={() => fetchCheckpoints(nextCursor, true)}
              disabled={loadingMore}
              className="px-4 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] transition-colors flex items-center gap-2"
            >
              {loadingMore && <RefreshCw className="w-3 h-3 animate-spin" />}
              <span>Tải thêm checkpoints</span>
            </button>
          </div>
        )}
      </div>

      {/* Resume Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!checkpointToResume}
        isLoading={resuming}
        closeOnConfirm={false}
        isDestructive={false}
        title="Tiếp tục huấn luyện từ Checkpoint"
        message={
          checkpointToResume
            ? `Bạn có chắc chắn muốn tiếp tục huấn luyện từ ${
                checkpointToResume.epoch != null
                  ? `Epoch ${checkpointToResume.epoch}`
                  : 'checkpoint đã chọn'
              } cho nhiệm vụ ${
                jobNames[checkpointToResume.job_id] || checkpointToResume.job_id
              }? Một phiên chạy mới sẽ được tạo với trọng số mô hình và trạng thái optimizer đã lưu.`
            : ''
        }
        confirmLabel="Xác nhận & Tiếp tục"
        onConfirm={handleConfirmResume}
        onClose={() => setCheckpointToResume(null)}
      />
    </div>
  );
};
