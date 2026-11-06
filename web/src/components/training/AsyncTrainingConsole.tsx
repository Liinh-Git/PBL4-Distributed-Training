import { Terminal } from 'lucide-react';
import type { StrategyStateStrictBSPData } from '../../types/api';
import type { EpochMetricData } from '../charts/LiveTrainingCharts';

/** The same epoch-by-epoch Training Output presentation used by the sync view. */
export function AsyncTrainingConsole({ progress, epochMetrics, totalEpochs, attemptState, isStale, jobDisplayName }: {
  progress?: StrategyStateStrictBSPData | null;
  epochMetrics: EpochMetricData[];
  totalEpochs?: number | null;
  attemptState: string;
  isStale?: boolean;
  jobDisplayName?: string | null;
}) {
  const current = progress?.epoch_progress;
  const completed = progress?.completed_epochs;
  const running = !['COMPLETED', 'FAILED', 'ABORTED'].includes(attemptState);
  const digits = String(totalEpochs ?? 1).length;
  const epochLabel = (index: number) => `Epoch ${String(index + 1).padStart(digits, '0')}/${totalEpochs ?? '—'}`;
  const percent = current && current.target_units > 0 ? Math.min(100, current.processed_units / current.target_units * 100) : null;
  const filled = percent == null ? 0 : Math.round(percent / 10);
  const metrics = new Map(epochMetrics.map(metric => [metric.epoch_index, metric]));
  const completedIndices = new Set(metrics.keys());
  // Old Attempts may have completed epochs without the previously omitted events.
  const firstVisible = Math.max(0, (completed ?? 0) - 100);
  for (let epoch = firstVisible; epoch < (completed ?? 0); epoch++) completedIndices.add(epoch);
  return <section aria-label="Training Output Async-SGD" className="min-w-0 overflow-hidden rounded border border-white/[0.08] bg-[#0b0c0e] font-mono text-xs text-zinc-300">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] bg-[#121317] px-4 py-2">
      <h2 className="flex items-center gap-2 text-xs font-medium"><Terminal aria-hidden="true" className="h-3.5 w-3.5 text-zinc-400" />Training Output</h2>
      <span className="text-[11px] text-zinc-400">Async-SGD · {attemptState}{isStale ? ' · số liệu chưa cập nhật' : ''}</span>
    </div>
    <div className="max-h-[360px] overflow-y-auto p-4 leading-6 space-y-1.5 break-words" tabIndex={0} aria-label="Nhật ký tiến độ epoch">
      <p className="border-b border-white/[0.04] pb-2 text-zinc-200">Huấn luyện: {jobDisplayName ?? 'Mô hình phân tán'} · {totalEpochs ?? '—'} epoch</p>
      {firstVisible > 0 && <p className="text-zinc-400">Đang hiển thị 100 epoch hoàn tất gần nhất.</p>}
      {[...completedIndices].sort((a, b) => a - b).map(epoch => {
        const metric = metrics.get(epoch);
        return <p key={epoch}>{epochLabel(epoch)}: hoàn tất
          {metric ? <> · loss = {metric.training_loss == null ? 'chưa có số liệu' : metric.training_loss.toFixed(4)}
            {' · accuracy = '}{metric.training_accuracy == null ? 'chưa có số liệu' : `${metric.training_accuracy.toFixed(2)}%`}
            {' · số mẫu: '}{metric.sample_count.toLocaleString('vi-VN')}</>
            : ' · phiên Runtime này chưa ghi metrics epoch'}</p>;
      })}
      {running && current && <div className="text-emerald-400">
        <span>{epochLabel(current.epoch_index)}: </span>
        {percent != null && <><span aria-hidden="true" className="text-zinc-400">[{'█'.repeat(filled)}{'░'.repeat(10 - filled)}]</span>
          <span className="font-semibold"> {percent.toLocaleString('vi-VN', { maximumFractionDigits: 1 })}%</span></>}
        {' · Work Unit '}{current.processed_units.toLocaleString('vi-VN')}/{current.target_units.toLocaleString('vi-VN')}
        {' · số mẫu: '}{current.sample_count.toLocaleString('vi-VN')}
        {current.training_loss != null && <> · loss tạm tính = {current.training_loss.toFixed(4)}</>}
        {current.training_accuracy != null && <> · accuracy tạm tính = {current.training_accuracy.toFixed(2)}%</>}
      </div>}
      {running && !current && <p className="text-emerald-400">
        {completed != null && (totalEpochs == null || completed < totalEpochs) ? `${epochLabel(completed)}: ` : ''}
        Đang chờ bộ đếm riêng theo epoch từ Runtime; chưa thể hiển thị % và loss của epoch này.
      </p>}
      {running && <p className="text-zinc-400">Worker chạy độc lập; dòng tiến độ theo dõi epoch đầu tiên chưa hoàn tất. Epoch sau có thể đang được xử lý song song.</p>}
      {attemptState === 'COMPLETED' && <p className="text-emerald-400">Quá trình huấn luyện đã hoàn tất.</p>}
      {['FAILED', 'ABORTED'].includes(attemptState) && <p className="text-amber-300">Quá trình huấn luyện đã dừng ({attemptState}); giữ nguyên các số liệu đã ghi nhận.</p>}
    </div>
  </section>;
}
