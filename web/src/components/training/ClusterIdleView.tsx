import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { jobsService, attemptsService } from '../../api';
import { JobListItemData, AttemptListItemData } from '../../types/api';
import { AttemptStateBadge } from '../common/Badge';
import { formatDateTime, formatStrategy } from '../../utils/date';

export const ClusterIdleView: React.FC = () => {
  const navigate = useNavigate();
  const [readyJobs, setReadyJobs] = useState<JobListItemData[]>([]);
  const [recentRuns, setRecentRuns] = useState<AttemptListItemData[]>([]);
  const [jobsMap, setJobsMap] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [launchingId, setLaunchingId] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setLaunchError(null);
      const [jobsRes, attemptsRes] = await Promise.allSettled([
        jobsService.listJobs({ limit: 50 }),
        attemptsService.listAttempts({ limit: 5 }),
      ]);

      if (jobsRes.status === 'fulfilled') {
        const allJobs = jobsRes.value.data || [];
        const ready = allJobs.filter((j) => j.state === 'READY' || j.state === 'DRAFT');
        setReadyJobs(ready.slice(0, 4));

        const map: Record<string, string> = {};
        allJobs.forEach((j) => {
          map[j.job_id] = j.display_name;
        });
        setJobsMap(map);
      }

      if (attemptsRes.status === 'fulfilled') {
        setRecentRuns(attemptsRes.value.data || []);
      }
    } catch {
      // Best-effort load
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleLaunch = async (jobId: string) => {
    try {
      setLaunchingId(jobId);
      setLaunchError(null);
      await attemptsService.assertNoActiveAttempt();
      const res = await jobsService.startJob(jobId);
      navigate(`/live?attempt_id=${encodeURIComponent(res.data.attempt_id)}&tab=live`);
    } catch (err: any) {
      setLaunchError(err?.message || 'Không thể khởi chạy nhiệm vụ. Vui lòng thử lại.');
      setLaunchingId(null);
    }
  };

  return (
    <div className="w-full space-y-6 font-sans select-none">
      {/* Hero Section (căn giữa, không đặt trong card hộp) */}
      <div className="py-6 flex flex-col items-center justify-center text-center space-y-2">
        <h1 className="text-lg font-semibold text-[#f3f3f4]">
          Không có tiến trình huấn luyện nào đang diễn ra
        </h1>
        <p className="text-xs text-[#73737c] max-w-lg">
          Tạo phiên huấn luyện mới, chạy nhiệm vụ sẵn sàng bên dưới hoặc xem lại lịch sử các lần chạy.
        </p>
        <div className="flex items-center justify-center gap-3 pt-2">
          <Link
            to="/training/new"
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
          >
            Tạo huấn luyện mới
          </Link>
          <Link
            to="/runs"
            className="px-4 py-2 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] text-xs font-medium transition-colors border border-white/[0.07]"
          >
            Lịch sử các lần chạy
          </Link>
        </div>
      </div>

      {launchError && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded text-xs text-rose-300">
          {launchError}
        </div>
      )}

      {/* Ready Jobs Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#f3f3f4]">
            Nhiệm vụ sẵn sàng khởi chạy
          </h2>
          <Link
            to="/jobs"
            className="text-xs text-blue-400 hover:underline"
          >
            Xem tất cả Jobs
          </Link>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-[#73737c] flex items-center justify-center gap-2 border border-white/[0.06] rounded bg-[#121214]">
            <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
            <span>Đang tải danh sách nhiệm vụ...</span>
          </div>
        ) : readyJobs.length === 0 ? (
          <div className="p-6 text-center text-xs text-[#73737c] border border-white/[0.06] rounded bg-[#121214]">
            Chưa có nhiệm vụ nào sẵn sàng. Hãy bấm &quot;Tạo huấn luyện mới&quot; để thiết lập.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {readyJobs.map((job) => (
              <div
                key={job.job_id}
                className="p-4 rounded bg-[#141416] border border-white/[0.07] hover:border-white/[0.14] transition-all flex flex-col justify-between gap-3 group"
              >
                <div className="space-y-1">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                      {job.display_name}
                    </h3>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-[#a1a1a8]">
                      {job.state}
                    </span>
                  </div>
                  <p className="text-[11px] text-[#73737c] line-clamp-1">
                    {job.description || 'Chưa có mô tả chi tiết'}
                  </p>
                </div>

                <div className="pt-2 border-t border-white/[0.05] flex items-center justify-between text-[11px]">
                  <span className="text-[#73737c]">
                    {job.attempt_count ? `${job.attempt_count} lần chạy trước` : 'Chưa chạy lần nào'}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleLaunch(job.job_id)}
                    disabled={launchingId === job.job_id}
                    className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors disabled:opacity-50"
                  >
                    {launchingId === job.job_id ? 'Đang khởi chạy...' : 'Khởi chạy'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Recent Runs Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#f3f3f4]">
            Các lần chạy gần nhất
          </h2>
          <Link
            to="/runs"
            className="text-xs text-blue-400 hover:underline"
          >
            Xem toàn bộ lịch sử
          </Link>
        </div>

        {recentRuns.length === 0 ? (
          <div className="p-6 text-center text-xs text-[#73737c] border border-white/[0.06] rounded bg-[#121214]">
            Chưa có lịch sử chạy nào được ghi nhận.
          </div>
        ) : (
          <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs min-w-[650px]">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] text-[11px] bg-[#141416]">
                    <th className="py-2.5 px-3.5 font-medium">Nhiệm vụ</th>
                    <th className="py-2.5 px-3 font-medium whitespace-nowrap">Trạng thái</th>
                    <th className="py-2.5 px-3 font-medium whitespace-nowrap">Chiến lược</th>
                    <th className="py-2.5 px-3 font-medium whitespace-nowrap">Thời gian bắt đầu</th>
                    <th className="py-2.5 px-3 font-medium whitespace-nowrap">Thời gian kết thúc</th>
                    <th className="py-2.5 px-3.5 font-medium text-right whitespace-nowrap">Xem lại</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {recentRuns.map((att) => (
                    <tr
                      key={att.attempt_id}
                      onClick={() => navigate(`/live?attempt_id=${encodeURIComponent(att.attempt_id)}`)}
                      className="hover:bg-[#171719] transition-colors cursor-pointer group"
                    >
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                        {jobsMap[att.job_id] || 'Nhiệm vụ'}
                      </td>
                      <td className="py-2.5 px-3 whitespace-nowrap">
                        <AttemptStateBadge state={att.state} />
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8] whitespace-nowrap">
                        {formatStrategy(att.training_strategy)}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-xs whitespace-nowrap">
                        {formatDateTime(att.started_at)}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-xs whitespace-nowrap">
                        {formatDateTime(att.ended_at)}
                      </td>
                      <td className="py-2.5 px-3.5 text-right whitespace-nowrap">
                        <span className="text-xs text-blue-400 group-hover:underline">
                          Xem kết quả
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
