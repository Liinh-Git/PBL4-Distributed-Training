import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, RotateCcw, X } from 'lucide-react';
import { attemptsService, checkpointsService, jobsService } from '../../api';
import type { CheckpointListItemData } from '../../types/api';

interface ResumeCheckpointModalProps {
  jobId: string;
  canResume: boolean;
  onClose: () => void;
  onResumed: (attemptId: string) => void;
}

export const ResumeCheckpointModal: React.FC<ResumeCheckpointModalProps> = ({
  jobId, canResume, onClose, onResumed,
}) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const submittingRef = useRef(false);
  const [checkpoints, setCheckpoints] = useState<CheckpointListItemData[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedCheckpoint = checkpoints.find(cp => cp.checkpoint_id === selectedId);

  const loadCheckpoints = useCallback(async (cursor: string | null = null) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const response = await checkpointsService.listCheckpoints(
        { job_id: jobId, state: 'COMPLETE', limit: 50, cursor },
        { signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      const items = response.data.filter(cp => cp.job_id === jobId && cp.state === 'COMPLETE');
      setCheckpoints(previous => {
        if (!cursor) return items;
        const ids = new Set(previous.map(cp => cp.checkpoint_id));
        return [...previous, ...items.filter(cp => !ids.has(cp.checkpoint_id))];
      });
      if (!cursor) setSelectedId(items[0]?.checkpoint_id ?? '');
      setNextCursor(response.page?.next_cursor ?? null);
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : 'Unable to load checkpoints.');
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    void loadCheckpoints();
    return () => {
      requestRef.current?.abort();
      dialog?.close();
    };
  }, [loadCheckpoints]);

  const handleResume = async () => {
    if (!canResume || loading || submittingRef.current || !selectedCheckpoint
      || selectedCheckpoint.job_id !== jobId || selectedCheckpoint.state !== 'COMPLETE') return;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await attemptsService.assertNoActiveAttempt();
      const response = await jobsService.resumeJob(jobId, {
        checkpoint_id: selectedCheckpoint.checkpoint_id,
      });
      onResumed(response.data.attempt_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to resume training.');
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const close = () => {
    if (!submittingRef.current) onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="resume-checkpoint-title"
      aria-describedby="resume-checkpoint-description"
      onCancel={event => { event.preventDefault(); close(); }}
      className="m-auto w-[calc(100%-2rem)] max-w-lg max-h-[90vh] overflow-y-auto rounded border border-white/[0.08] bg-[#121214] p-0 text-[#f3f3f4] shadow-2xl backdrop:bg-black/80 font-sans"
    >
      <div className="flex items-center justify-between gap-3 border-b border-white/[0.08] px-5 py-4">
        <h2 id="resume-checkpoint-title" className="text-sm font-semibold">Resume from checkpoint</h2>
        <button type="button" aria-label="Close checkpoint selection" onClick={close} disabled={submitting}
          className="rounded p-1 text-[#a1a1a8] hover:text-white disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-4 p-5 text-xs">
        <p id="resume-checkpoint-description" className="leading-relaxed text-[#a1a1a8]">
          Create a new attempt using the model weights and data position saved in a checkpoint from this job.
        </p>
        {error && <p role="alert" className="break-words text-rose-300">{error}</p>}
        {loading && <p role="status" className="text-[#a1a1a8]">Loading checkpoints…</p>}
        {!loading && checkpoints.length === 0 && !error && (
          <p className="rounded border border-white/[0.08] p-3 text-[#a1a1a8]">
            No complete checkpoints are available for this job. Use Launch Run to start from the beginning.
          </p>
        )}
        {checkpoints.length > 0 && (
          <div className="space-y-2">
            <label htmlFor="resume-checkpoint-selection" className="block font-medium">Checkpoint</label>
            <select id="resume-checkpoint-selection" value={selectedId}
              onChange={event => setSelectedId(event.target.value)} disabled={loading || submitting}
              className="w-full rounded border border-white/[0.12] bg-[#171719] px-3 py-2 text-xs focus-visible:outline-2 focus-visible:outline-blue-500">
              {checkpoints.map(cp => (
                <option key={cp.checkpoint_id} value={cp.checkpoint_id}>
                  Model v{cp.model_version}{cp.source_step_id != null ? ` · Step ${cp.source_step_id}` : ''}
                  {' · '}{new Date(cp.completed_at || cp.created_at).toLocaleString()}
                  {' · '}{cp.checkpoint_id}
                </option>
              ))}
            </select>
            {selectedCheckpoint && (
              <p className="break-all text-[#a1a1a8]">
                Source attempt: <span className="font-mono">{selectedCheckpoint.created_by_attempt_id}</span>
              </p>
            )}
          </div>
        )}
        {nextCursor && (
          <button type="button" onClick={() => void loadCheckpoints(nextCursor)} disabled={loading || submitting}
            className="text-blue-400 hover:underline disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
            Load older checkpoints
          </button>
        )}
        {error && !submitting && (
          <button type="button" onClick={() => void loadCheckpoints()} disabled={loading}
            className="text-blue-400 hover:underline disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
            Reload checkpoints
          </button>
        )}
        {!canResume && <p role="status" className="text-amber-300">Resume is unavailable while a run is active or run availability is being checked.</p>}
      </div>
      <div className="flex justify-end gap-2 border-t border-white/[0.08] px-5 py-4">
        <button type="button" onClick={close} disabled={submitting}
          className="rounded border border-white/[0.08] bg-[#171719] px-3 py-2 text-xs hover:bg-[#202024] disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">Cancel</button>
        <button type="button" onClick={() => void handleResume()}
          aria-busy={submitting}
          disabled={!canResume || loading || submitting || !selectedCheckpoint}
          className="inline-flex items-center gap-2 rounded bg-blue-600 px-3 py-2 text-xs font-medium hover:bg-blue-500 disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-blue-500">
          {submitting
            ? <RefreshCw aria-hidden="true" className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
            : <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />}Resume training
        </button>
      </div>
    </dialog>
  );
};
