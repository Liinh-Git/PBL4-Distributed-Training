import React, { useState, useEffect, useCallback } from 'react';
import { Drawer } from '../common/Drawer';
import { CheckpointStateBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { ChevronDown, RotateCcw, RefreshCw, AlertCircle, Layers } from 'lucide-react';
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
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
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
  const sourceStep =
    detailData?.source_step_id ??
    getCheckpointProp<number>(checkpoint, 'source_step_id') ??
    getCheckpointProp<number>(checkpoint, 'sourceStepId');
  const modelVersion =
    detailData?.model_version ??
    getCheckpointProp<number>(checkpoint, 'model_version');
  const jobId =
    detailData?.job_id ||
    getCheckpointProp<string>(checkpoint, 'job_id') ||
    getCheckpointProp<string>(checkpoint, 'jobId') ||
    '—';

  const handleResume = () => {
    if (!detailData || detailData.state !== 'COMPLETE') return;
    const cpItem: CheckpointListItemData = {
      checkpoint_id: detailData.checkpoint_id,
      job_id: detailData.job_id,
      created_by_attempt_id: detailData.created_by_attempt_id,
      state: detailData.state,
      model_version: detailData.model_version,
      source_step_id: detailData.source_step_id,
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
            {sourceStep != null
              ? `Checkpoint Step #${sourceStep}`
              : modelVersion != null
              ? `Checkpoint v${modelVersion}`
              : `Checkpoint ${resolvedCheckpointId ? resolvedCheckpointId.slice(0, 10) : ''}`}
          </span>
        </div>
      }
      subtitle={`Job: ${jobId}`}
      widthClass="max-w-md"
    >
      <div className="space-y-5 font-sans select-none text-xs">
        {/* Loading state */}
        {loading && (
          <div className="py-6 flex items-center justify-center gap-2 text-[#73737c]">
            <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
            <span>Loading checkpoint metadata...</span>
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
              Retry
            </button>
          </div>
        )}

        {/* Header summary: State */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Status</span>
          {currentState && <CheckpointStateBadge state={currentState} />}
        </div>

        {/* Resume Parameters Section */}
        <div className="space-y-2 pb-3 border-b border-white/[0.07]">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Recovery Snapshot Parameters
          </h3>
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Epoch</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {detailData?.recovery_cursor?.epoch ?? '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Next batch ordinal</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {detailData?.recovery_cursor?.next_batch_ordinal ?? '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Step in epoch</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {detailData?.recovery_cursor?.step_in_epoch ?? '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Model version</span>
              <span className="text-emerald-400 font-medium font-mono">
                {modelVersion != null ? `v${modelVersion}` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Source step</span>
              <span className="text-[#f3f3f4] font-medium font-mono">
                {sourceStep != null ? `#${sourceStep}` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Timestamps */}
        <div className="space-y-1.5 pb-3 border-b border-white/[0.07]">
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Created</span>
            <span className="text-[#f3f3f4] font-mono text-[11px]">
              {formatTimestamp(
                detailData?.created_at ||
                  getCheckpointProp<string>(checkpoint, 'created_at') ||
                  getCheckpointProp<string>(checkpoint, 'createdAt')
              )}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Completed</span>
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
              <span>Resume training from this checkpoint</span>
            </button>
          </div>
        )}

        {/* Collapsible Technical Details */}
        <div className="pt-2">
          <button
            type="button"
            onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            className="w-full flex items-center justify-between text-left text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors py-1"
          >
            <span>Technical identifiers & cryptographic integrity</span>
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${
                showTechnicalDetails ? 'rotate-180' : ''
              }`}
            />
          </button>

          {showTechnicalDetails && (
            <div className="mt-2.5 p-3 bg-[#171719] rounded border border-white/[0.04] space-y-2 text-xs divide-y divide-white/[0.04]">
              <div className="flex items-center justify-between pt-1">
                <span className="text-[#73737c]">Checkpoint ID</span>
                <CopyableId value={detailData?.checkpoint_id || resolvedCheckpointId || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Created by attempt</span>
                <CopyableId
                  value={
                    detailData?.created_by_attempt_id ||
                    getCheckpointProp<string>(checkpoint, 'created_by_attempt_id') ||
                    getCheckpointProp<string>(checkpoint, 'attemptId') ||
                    '—'
                  }
                  truncateLength={16}
                />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Source operation</span>
                <span className="text-[#f3f3f4] font-mono">
                  {detailData?.source_operation_id != null ? `#${detailData.source_operation_id}` : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Training strategy</span>
                <span className="text-[#a1a1a8] font-mono">
                  {detailData?.training_strategy || '—'}
                </span>
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Contract hash</span>
                <CopyableId value={detailData?.contract_hash || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Dataset build ID</span>
                <CopyableId value={detailData?.dataset_build_id || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Dataset manifest hash</span>
                <CopyableId value={detailData?.dataset_manifest_hash || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Parameter manifest hash</span>
                <CopyableId value={detailData?.parameter_manifest_hash || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Model SHA-256</span>
                <CopyableId value={detailData?.integrity?.model_sha256 || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Metadata SHA-256</span>
                <CopyableId value={detailData?.integrity?.metadata_sha256 || '—'} truncateLength={16} />
              </div>
              <div className="flex items-center justify-between pt-1.5">
                <span className="text-[#73737c]">Artifact size</span>
                <span className="text-[#f3f3f4] font-mono">
                  {detailData?.integrity?.artifact_size_bytes != null
                    ? `${(detailData.integrity.artifact_size_bytes / (1024 * 1024)).toFixed(2)} MB (${detailData.integrity.artifact_size_bytes.toLocaleString()} bytes)`
                    : '—'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </Drawer>
  );
};
