import React, { useState, useEffect, useCallback } from 'react';
import { Drawer } from '../common/Drawer';
import { CheckpointStateBadge } from '../common/Badge';
import { RotateCcw, RefreshCw, AlertCircle, Layers } from 'lucide-react';
import { checkpointsService } from '../../api';
import { CheckpointDetailData, CheckpointListItemData } from '../../types/api';
import { Checkpoint } from '../../types';

function getCheckpointProp<T>(cp: unknown, key: string): T | undefined {
  if (cp && typeof cp === 'object' && key in cp) {
    return (cp as Record<string, any>)[key] as T;
  }
  return undefined;
}

function formatTimestamp(isoString?: string | null): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return isoString;
  }
}

interface CheckpointDetailDrawerProps {
  checkpoint: (Checkpoint | CheckpointListItemData | CheckpointDetailData) | null;
  checkpointId?: string | null;
  onClose: () => void;
  onResume?: (checkpoint: CheckpointListItemData) => void;
}

export const CheckpointDetailDrawer: React.FC<CheckpointDetailDrawerProps> = ({
  checkpoint,
  checkpointId,
  onClose,
  onResume,
}) => {
  const [detailData, setDetailData] = useState<CheckpointDetailData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const resolvedCheckpointId =
    checkpointId ||
    getCheckpointProp<string>(checkpoint, 'checkpoint_id') ||
    getCheckpointProp<string>(checkpoint, 'id') ||
    null;

  const loadDetail = useCallback(async () => {
    if (!resolvedCheckpointId) {
      setDetailData(null);
      setError(null);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const res = await checkpointsService.getCheckpoint(resolvedCheckpointId);
      setDetailData(res.data);
    } catch (err: any) {
      setError(err?.message || `Failed to load details for checkpoint ${resolvedCheckpointId}`);
    } finally {
      setLoading(false);
    }
  }, [resolvedCheckpointId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  if (!checkpoint && !checkpointId) return null;

  const currentState = detailData?.state || getCheckpointProp<string>(checkpoint, 'state');
  const isComplete = currentState === 'COMPLETE';
  const epochNumber =
    detailData?.recovery_cursor?.epoch ??
    getCheckpointProp<number>(checkpoint, 'epoch');
  const jobId =
    detailData?.job_id ||
    getCheckpointProp<string>(checkpoint, 'job_id') ||
    getCheckpointProp<string>(checkpoint, 'jobId') ||
    '—';

  const jobTitle = (() => {
    try {
      const cached = sessionStorage.getItem(`pbl4_job_title_${jobId}`);
      if (cached) return cached;
    } catch {}
    return jobId.startsWith('job_') ? 'Nhiệm vụ huấn luyện' : jobId;
  })();

  const handleResume = () => {
    if (!detailData || detailData.state !== 'COMPLETE') return;
    const cpItem: CheckpointListItemData = {
      checkpoint_id: detailData.checkpoint_id,
      job_id: detailData.job_id,
      created_by_attempt_id: detailData.created_by_attempt_id,
      state: detailData.state,
      model_version: detailData.model_version,
      source_step_id: detailData.source_step_id,
      epoch: detailData.recovery_cursor?.epoch,
      created_at: detailData.created_at,
      completed_at: detailData.completed_at,
    };
    onResume?.(cpItem);
    onClose();
  };

  return (
    <Drawer
      isOpen={!!checkpoint || !!checkpointId}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-blue-400" />
          <span>
            {epochNumber != null
              ? `Checkpoint Epoch ${epochNumber}`
              : `Mốc Checkpoint`}
          </span>
        </div>
      }
      subtitle={`Nhiệm vụ: ${jobTitle}`}
      widthClass="max-w-md"
    >
      <div className="space-y-5 font-sans select-none text-xs">
        {/* Loading state */}
        {loading && (
          <div className="py-6 flex items-center justify-center gap-2 text-[#73737c]">
            <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
            <span>Đang tải thông tin checkpoint...</span>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-rose-300">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              type="button"
              onClick={loadDetail}
              className="px-2 py-0.5 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 transition-colors"
            >
              Thử lại
            </button>
          </div>
        )}

        {/* Header summary: State */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Trạng thái</span>
          {currentState && <CheckpointStateBadge state={currentState} />}
        </div>

        {/* Resume Parameters Section */}
        <div className="space-y-2 pb-3 border-b border-white/[0.07]">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Thông số phục hồi Checkpoint
          </h3>
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Epoch</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {epochNumber ?? '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Thứ tự batch tiếp theo</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {detailData?.recovery_cursor?.next_batch_ordinal ?? '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Timestamps */}
        <div className="space-y-1.5 pb-3 border-b border-white/[0.07]">
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Khởi tạo</span>
            <span className="text-[#f3f3f4] font-mono text-[11px]">
              {formatTimestamp(
                detailData?.created_at ||
                  getCheckpointProp<string>(checkpoint, 'created_at') ||
                  getCheckpointProp<string>(checkpoint, 'createdAt')
              )}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Hoàn tất</span>
            <span className="text-[#a1a1a8] font-mono text-[11px]">
              {formatTimestamp(
                detailData?.completed_at ||
                  getCheckpointProp<string>(checkpoint, 'completed_at')
              )}
            </span>
          </div>
        </div>

        {/* Action Button: Resume training */}
        {isComplete && (
          <div className="pt-1">
            <button
              type="button"
              onClick={handleResume}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Tiếp tục huấn luyện từ checkpoint này</span>
            </button>
          </div>
        )}
      </div>
    </Drawer>
  );
};
