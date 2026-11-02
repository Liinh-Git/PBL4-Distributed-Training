import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { AttemptStateBadge } from '../common/Badge';
import { isActiveAttempt } from '../../api/attempts';
import { formatDateTime } from '../../utils/date';
import type { AttemptListItemData, ExecutionMode, JobState } from '../../types/api';

export function formatExecutionMode(mode?: ExecutionMode | null): string {
  switch (mode) {
    case 'FRESH': return 'Bắt đầu từ đầu';
    case 'RETRY_FROM_START': return 'Thử lại từ đầu';
    case 'RESUME': return 'Tiếp tục từ checkpoint';
    default: return 'Không khả dụng';
  }
}

export function formatRunTime(value?: string | null): string {
  return formatDateTime(value);
}

export const JobRunSummary: React.FC<{
  attempt?: AttemptListItemData | null;
  jobState: JobState;
  historyAvailable: boolean;
  jobId?: string;
}> = ({ attempt, jobState, historyAvailable, jobId }) => {
  if (!historyAvailable) {
    return (
      <section aria-label="Lần chạy gần nhất" className="rounded border border-white/[0.07] bg-[#121214] p-4 text-xs text-[#a1a1a8]">
        Trạng thái lần chạy không khả dụng. Làm mới để tải lại.
      </section>
    );
  }

  if (!attempt) {
    return (
      <section aria-label="Lần chạy gần nhất" className="rounded border border-white/[0.07] bg-[#121214] p-4">
        <h2 className="text-sm font-medium text-[#f3f3f4]">Chưa có lần chạy nào</h2>
        <p className="mt-1 text-xs text-[#a1a1a8]">
          {jobState === 'ARCHIVED'
            ? 'Nhiệm vụ này đã lưu trữ và chưa có lần chạy nào. Clone để tạo nhiệm vụ mới.'
            : jobState === 'DRAFT'
              ? 'Xem lại cấu hình và bắt đầu chạy. Cấu hình sẽ được khóa khi huấn luyện bắt đầu.'
              : 'Khởi chạy huấn luyện để bắt đầu từ đầu với cấu hình này.'}
        </p>
      </section>
    );
  }

  const active = isActiveAttempt(attempt.state);
  const targetUrl = active
    ? `/live?attempt_id=${encodeURIComponent(attempt.attempt_id)}`
    : jobId
    ? `/jobs/${encodeURIComponent(jobId)}?attempt_id=${encodeURIComponent(attempt.attempt_id)}`
    : `/live?attempt_id=${encodeURIComponent(attempt.attempt_id)}`;

  return (
    <section aria-labelledby="job-run-heading" className="rounded border border-white/[0.07] bg-[#121214]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <h2 id="job-run-heading" className="text-sm font-medium text-[#f3f3f4]">{active ? 'Tiến trình đang chạy' : 'Lần chạy gần nhất'}</h2>
          <AttemptStateBadge state={attempt.state} />
        </div>
        <Link to={targetUrl}
          className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 focus-visible:outline-2 focus-visible:outline-blue-500">
          {active ? 'Xem trực tiếp' : 'Xem chi tiết'}
        </Link>
      </div>
      <dl className="grid grid-cols-1 gap-4 px-4 py-3 text-xs sm:grid-cols-3">
        <div><dt className="text-[#73737c]">Chế độ thực thi</dt><dd className="mt-1 text-[#f3f3f4]">{formatExecutionMode(attempt.execution_mode)}</dd></div>
        <div><dt className="text-[#73737c]">Thời gian bắt đầu</dt><dd className="mt-1 text-[#a1a1a8] text-xs">{formatRunTime(attempt.started_at)}</dd></div>
        <div><dt className="text-[#73737c]">{active ? 'Thời gian tạo' : 'Thời gian kết thúc'}</dt><dd className="mt-1 text-[#a1a1a8] text-xs">{formatRunTime(active ? attempt.created_at : attempt.ended_at)}</dd></div>
      </dl>
      {attempt.failure_code && (
        <p className="border-t border-white/[0.07] px-4 py-3 text-xs text-rose-300">
          Mã lỗi: <span className="break-all font-mono">{attempt.failure_code}</span>. Mở chi tiết lần chạy để kiểm tra.
        </p>
      )}
    </section>
  );
};
