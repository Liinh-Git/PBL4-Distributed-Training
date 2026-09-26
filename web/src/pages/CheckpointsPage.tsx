import React, { useState, useEffect } from 'react';
import {
  RotateCcw,
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Layers,
} from 'lucide-react';
import { CheckpointStateBadge } from '../components/common/Badge';
import { CheckpointDetailDrawer } from '../components/drawers/CheckpointDetailDrawer';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { CopyableId } from '../components/common/CopyableId';
import { useNavigate } from 'react-router-dom';
import { checkpointsService, jobsService } from '../api';
import { CheckpointListItemData } from '../types/api';

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

export const CheckpointsPage: React.FC = () => {
  const navigate = useNavigate();

  const [checkpoints, setCheckpoints] = useState<CheckpointListItemData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<CheckpointListItemData | null>(null);
  const [checkpointToResume, setCheckpointToResume] = useState<CheckpointListItemData | null>(null);

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
      setError(err?.message || 'Failed to load checkpoints');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchCheckpoints();
  }, []);

  const filteredCheckpoints = checkpoints.filter(cp => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return true;
    return (
      cp.checkpoint_id.toLowerCase().includes(query) ||
      cp.job_id.toLowerCase().includes(query) ||
      cp.created_by_attempt_id.toLowerCase().includes(query) ||
      cp.state.toLowerCase().includes(query) ||
      String(cp.model_version).includes(query) ||
      (cp.source_step_id != null && String(cp.source_step_id).includes(query))
    );
  });

  // Latest usable checkpoint MUST strictly have state === 'COMPLETE'
  const latestUsableCheckpoint = checkpoints.find(cp => cp.state === 'COMPLETE') || null;

  const handleConfirmResume = async () => {
    if (!checkpointToResume || !checkpointToResume.job_id || checkpointToResume.state !== 'COMPLETE') {
      return;
    }
    try {
      await jobsService.resumeJob(checkpointToResume.job_id, {
        checkpoint_id: checkpointToResume.checkpoint_id,
      });
      setCheckpointToResume(null);
      navigate('/live');
    } catch (err: any) {
      alert(`Failed to resume from checkpoint: ${err?.message || 'Unknown error'}`);
    }
  };

  return (
    <div className="space-y-4 w-full pb-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Saved Checkpoints
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 animate-pulse">
                Loading API...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Verified model parameter snapshots, recovery cursors, and cryptographic manifests.
          </p>
        </div>

        <button
          type="button"
          onClick={() => fetchCheckpoints()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#121214] border border-white/[0.07] hover:bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] text-xs font-medium transition-colors self-start sm:self-auto disabled:opacity-50"
          title="Refresh checkpoints"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
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
            Retry
          </button>
        </div>
      )}

      {/* High-level Recovery Status Banner */}
      {latestUsableCheckpoint ? (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-0.5 text-xs">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[#73737c]">Latest usable checkpoint:</span>
              <span className="font-semibold text-[#f3f3f4]">
                {latestUsableCheckpoint.source_step_id != null
                  ? `Step #${latestUsableCheckpoint.source_step_id}`
                  : latestUsableCheckpoint.model_version != null
                  ? `Model v${latestUsableCheckpoint.model_version}`
                  : `Checkpoint ${latestUsableCheckpoint.checkpoint_id.slice(0, 8)}`}
              </span>
              {latestUsableCheckpoint.model_version != null && (
                <span className="text-emerald-400">
                  (v{latestUsableCheckpoint.model_version})
                </span>
              )}
              <span className="text-[#73737c]">·</span>
              <span className="text-[#a1a1a8]">
                Job: {latestUsableCheckpoint.job_id}
              </span>
            </div>
            <p className="text-[11px] text-[#73737c] flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>
                Verified complete · Completed at{' '}
                {formatTimestamp(latestUsableCheckpoint.completed_at || latestUsableCheckpoint.created_at)}
              </span>
            </p>
          </div>

          <button
            type="button"
            onClick={() => setCheckpointToResume(latestUsableCheckpoint)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors self-start sm:self-auto"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Resume from latest</span>
          </button>
        </div>
      ) : !loading && checkpoints.length > 0 ? (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-3 text-xs text-[#73737c] flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
          <span>
            No COMPLETE checkpoints found yet. Ongoing checkpoint writes must finish before recovery is available.
          </span>
        </div>
      ) : null}

      {/* Search Bar */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
          <input
            type="text"
            placeholder="Search by checkpoint ID, job ID, attempt ID, step or model version..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>
      </div>

      {/* Checkpoints Table */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium">Checkpoint ID</th>
                <th className="py-2.5 px-3 font-medium">State</th>
                <th className="py-2.5 px-3 font-medium">Job ID</th>
                <th className="py-2.5 px-3 font-medium">Model version</th>
                <th className="py-2.5 px-3 font-medium">Source step</th>
                <th className="py-2.5 px-3 font-medium">Created</th>
                <th className="py-2.5 px-3.5 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && checkpoints.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#73737c]">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
                      <span>Loading saved checkpoints from API...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredCheckpoints.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-[#73737c]">
                    No checkpoints found matching current query.
                  </td>
                </tr>
              ) : (
                filteredCheckpoints.map(cp => {
                  const isRecoverable = cp.state === 'COMPLETE';
                  return (
                    <tr
                      key={cp.checkpoint_id}
                      className="hover:bg-[#171719] transition-colors"
                    >
                      {/* Checkpoint ID with Step Subtext */}
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4]">
                        <div className="space-y-0.5">
                          <CopyableId value={cp.checkpoint_id} truncateLength={12} className="font-medium text-[#f3f3f4]" />
                          {cp.source_step_id != null && (
                            <div className="text-[11px] text-[#73737c]">
                              Step #{cp.source_step_id}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* State */}
                      <td className="py-2.5 px-3">
                        <CheckpointStateBadge state={cp.state} />
                      </td>

                      {/* Job ID */}
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        <CopyableId value={cp.job_id} truncateLength={16} className="text-[#a1a1a8]" />
                      </td>

                      {/* Model version */}
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {cp.model_version != null ? `v${cp.model_version}` : '—'}
                      </td>

                      {/* Source step */}
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {cp.source_step_id != null ? `#${cp.source_step_id}` : '—'}
                      </td>

                      {/* Created */}
                      <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                        {formatTimestamp(cp.completed_at || cp.created_at)}
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-3.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {isRecoverable && cp.job_id && (
                            <button
                              type="button"
                              onClick={() => setCheckpointToResume(cp)}
                              className="px-2.5 py-1 text-xs rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors"
                            >
                              Resume
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => setSelectedCheckpoint(cp)}
                            className="px-2.5 py-1 text-xs text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] rounded transition-colors"
                          >
                            Inspect
                          </button>
                        </div>
                      </td>
                    </tr>
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
              <span>Load more checkpoints</span>
            </button>
          </div>
        )}
      </div>

      {/* Checkpoint Detail Drawer */}
      <CheckpointDetailDrawer
        checkpoint={selectedCheckpoint}
        onClose={() => setSelectedCheckpoint(null)}
        onResume={cp => {
          setSelectedCheckpoint(null);
          setCheckpointToResume(cp);
        }}
      />

      {/* Resume Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!checkpointToResume}
        title="Resume Training from Checkpoint"
        message={
          checkpointToResume
            ? `Are you sure you want to resume execution from ${
                checkpointToResume.source_step_id != null
                  ? `Step #${checkpointToResume.source_step_id}`
                  : `Checkpoint ${checkpointToResume.checkpoint_id.slice(0, 8)}`
              } (Model v${checkpointToResume.model_version}) for job ${
                checkpointToResume.job_id
              }? A new attempt will be created with restored model weights and optimizer state.`
            : ''
        }
        confirmText="Confirm & Resume"
        confirmVariant="primary"
        onConfirm={handleConfirmResume}
        onCancel={() => setCheckpointToResume(null)}
      />
    </div>
  );
};
