import type { StrategyStateStrictBSPData, WorkerSessionItemData } from '../../types/api';
import { asyncProgressPercent } from '../../utils/asyncMetrics';

const format = (value?: number | null) => value == null ? '—' : value.toLocaleString('vi-VN');

export function AsyncProgressPanel({ progress, workers, totalEpochs, expectedWorkers, attemptState, showWorkers = true }: {
  progress?: StrategyStateStrictBSPData | null;
  workers: WorkerSessionItemData[];
  totalEpochs?: number | null;
  expectedWorkers?: number | null;
  attemptState?: string;
  showWorkers?: boolean;
}) {
  const percent = asyncProgressPercent(progress);
  const completedEpochs = progress?.completed_epochs;
  const terminal = ['COMPLETED', 'FAILED', 'ABORTED'].includes(attemptState ?? '');
  const activeWorkers = progress?.active_workers ?? workers.filter(worker => worker.state === 'READY' && !worker.disconnected_at).length;
  return (
    <section aria-label="Tiến độ Async-SGD" className="bg-[#121214] border border-white/[0.07] rounded p-4 sm:p-5 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{attemptState === 'COMPLETED' ? 'Đã hoàn tất huấn luyện' : 'Tiến độ huấn luyện'}</h2>
        <span className="text-xs text-[#a1a1a8]">Async-SGD · {format(activeWorkers)}{expectedWorkers != null ? ` / ${format(expectedWorkers)}` : ''} Worker sẵn sàng</span>
      </div>
      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 tabular-nums">
          <span className="text-2xl font-semibold">{percent == null ? 'Chờ số liệu' : `${percent.toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%`}</span>
          <span className="text-xs text-[#a1a1a8]">{format(progress?.processed_units)} / {format(progress?.target_units)} Work Unit đã xử lý</span>
        </div>
        {percent != null && <progress aria-label="Dữ liệu đã xử lý" value={progress!.processed_units} max={progress!.target_units}
          className="block h-2 w-full overflow-hidden rounded bg-[#27272a] [&::-webkit-progress-bar]:bg-[#27272a] [&::-webkit-progress-value]:bg-blue-500 [&::-moz-progress-bar]:bg-blue-500" />}
        <div className="flex flex-wrap justify-between gap-2 text-xs text-[#a1a1a8]">
          <span>Epoch hoàn tất: <strong className="font-medium text-[#f3f3f4] tabular-nums">{format(completedEpochs)} / {format(totalEpochs)}</strong></span>
          {!terminal && completedEpochs != null && totalEpochs != null && completedEpochs < totalEpochs
            && <span>Đang hoàn tất epoch {format(completedEpochs + 1)}</span>}
        </div>
        <p className="text-xs text-[#a1a1a8]">Tiến độ tính trên toàn bộ dữ liệu của tất cả epoch, kể cả phần có gradient bị bỏ do quá trễ.</p>
      </div>
      {percent == null && <p role="status" className="text-xs text-blue-300">Chưa nhận được bộ đếm tiến độ từ Runtime. Số liệu sẽ xuất hiện khi nhận snapshot hoặc kết quả xử lý; READY là trạng thái sẵn sàng của Worker.</p>}
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 border-t border-white/[0.07] pt-4 text-xs tabular-nums">
        {[
          ['Loss gần nhất', progress?.loss == null ? 'Chưa có kết quả' : progress.loss.toFixed(4)],
          ['Dùng để cập nhật', `${format(progress?.applied_units)} Work Unit`],
          ['Bỏ do quá trễ', `${format(progress?.dropped_units)} Work Unit`],
          ['Phiên bản mô hình', progress?.model_version == null ? '—' : `v${format(progress.model_version)}`],
        ].map(([label, value]) => <div key={label}><dt className="text-[#a1a1a8]">{label}</dt><dd className="mt-1.5 font-medium">{value}</dd></div>)}
      </dl>
      <details className="text-xs">
        <summary className="w-fit cursor-pointer text-[#a1a1a8] hover:text-[#f3f3f4] focus-visible:outline-2 focus-visible:outline-blue-400">Chi tiết mẫu và độ trễ</summary>
        <dl className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-4 tabular-nums">
          {[
            ['Mẫu đã xử lý', format(progress?.processed_samples)],
            ['Mẫu được áp dụng', format(progress?.applied_samples)],
            ['Mẫu bị bỏ', format(progress?.dropped_samples)],
            ['Độ trễ gradient gần nhất', format(progress?.staleness)],
          ].map(([label, value]) => <div key={label}><dt className="text-[#a1a1a8]">{label}</dt><dd className="mt-1">{value}</dd></div>)}
        </dl>
      </details>
      {showWorkers && workers.length > 0 && <div className="border-t border-white/[0.07] pt-4">
        <h3 className="mb-3 text-xs font-medium">Worker và lịch sử kết nối</h3>
        <ul className="text-xs space-y-3">
          {workers.map(worker => <li key={worker.session_id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <div className="min-w-0"><span className="font-medium">Worker {worker.worker_id}</span>
              <span className="ml-2 text-[#a1a1a8] break-all">{worker.node_label}</span>
              <span className="mt-1 block text-[11px] text-[#a1a1a8] break-all">Session {worker.session_id}</span>
            </div>
            <span className={worker.state === 'READY' && !worker.disconnected_at ? 'text-emerald-400' : 'text-[#a1a1a8]'}>{worker.state}</span>
          </li>)}
        </ul>
      </div>}
    </section>
  );
}
