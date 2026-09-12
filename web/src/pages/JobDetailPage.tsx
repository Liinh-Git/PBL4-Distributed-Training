import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  Play,
  Copy,
  FileCode,
  Archive,
  ArrowLeft,
  ChevronDown,
  Activity,
  RefreshCw,
  AlertCircle,
  RotateCcw,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { JobStateBadge, AttemptStateBadge } from '../components/common/Badge';
import { CopyableId } from '../components/common/CopyableId';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { EmptyState } from '../components/common/EmptyState';
import { jobsService, attemptsService } from '../api';
import { JobDetailData, AttemptListItemData } from '../types/api';

export const JobDetailPage: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const { setRawContractModalJob } = useApp();

  const [job, setJob] = useState<JobDetailData | null>(null);
  const [attempts, setAttempts] = useState<AttemptListItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  const loadJobData = useCallback(async () => {
    if (!jobId) return;
    try {
      setLoading(true);
      setError(null);

      const [jobRes, attemptsRes] = await Promise.allSettled([
        jobsService.getJob(jobId),
        attemptsService.listAttempts({ job_id: jobId, limit: 50 }),
      ]);

      if (jobRes.status === 'fulfilled') {
        setJob(jobRes.value.data);
      } else {
        throw jobRes.reason;
      }

      if (attemptsRes.status === 'fulfilled') {
        setAttempts(attemptsRes.value.data || []);
      }
    } catch (err: any) {
      setError(err?.message || `Job specification "${jobId}" could not be loaded`);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadJobData();
  }, [loadJobData]);

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
    if (!job) return;
    try {
      setActionLoading('launch');
      const res = await jobsService.startJob(job.job_id);
      await loadJobData();
      navigate('/live');
    } catch (err: any) {
      alert(`Failed to launch training run: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRetry = async () => {
    if (!job) return;
    try {
      setActionLoading('retry');
      await jobsService.retryJob(job.job_id, { note: 'Retry from job detail' });
      await loadJobData();
      navigate('/live');
    } catch (err: any) {
      alert(`Failed to retry training run: ${err?.message || 'Unknown error'}`);
    } finally {
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
  const isRunning = attempts.some(a => a.state === 'RUNNING');
  const latestAttempt = attempts[0];
  const canRetry = latestAttempt && (latestAttempt.state === 'FAILED' || latestAttempt.state === 'ABORTED');

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
    <div className="space-y-6 w-full pb-10 select-none font-sans">
      {/* Top Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-[#73737c]">
        <Link to="/jobs" className="hover:text-[#f3f3f4] flex items-center gap-1 transition-colors">
          <ArrowLeft className="w-3 h-3" />
          <span>Jobs</span>
        </Link>
        <span>/</span>
        <span className="text-[#a1a1a8]">{job.display_name}</span>
      </div>

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-4 pb-4 border-b border-white/[0.07]">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-lg font-semibold text-[#f3f3f4]">
              {job.display_name}
            </h1>
            <JobStateBadge state={job.state} />
          </div>
          {job.description && (
            <p className="text-xs text-[#73737c] max-w-2xl">
              {job.description}
            </p>
          )}
          <div className="text-[11px] text-[#73737c] pt-0.5">
            Created on {job.created_at ? job.created_at.slice(0, 10) : '—'}
            {job.frozen_at && ` · Frozen at ${job.frozen_at.slice(0, 10)}`}
          </div>
        </div>

        {/* Action hierarchy */}
        <div className="flex items-center gap-2 self-start sm:self-center">
          <button
            type="button"
            disabled={actionLoading === 'clone'}
            onClick={handleClone}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-normal rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] transition-colors border border-white/[0.07] disabled:opacity-50"
          >
            <Copy className="w-3.5 h-3.5 text-[#73737c]" />
            <span>{actionLoading === 'clone' ? 'Cloning...' : 'Clone'}</span>
          </button>

          {canRetry && !isRunning && (
            <button
              type="button"
              disabled={actionLoading === 'retry'}
              onClick={handleRetry}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-normal rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] transition-colors border border-white/[0.07] disabled:opacity-50"
            >
              <RotateCcw className="w-3.5 h-3.5 text-[#73737c]" />
              <span>{actionLoading === 'retry' ? 'Retrying...' : 'Retry Run'}</span>
            </button>
          )}

          {job.state === 'READY' && !isRunning && (
            <button
              type="button"
              disabled={actionLoading === 'launch'}
              onClick={handleLaunch}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              <span>{actionLoading === 'launch' ? 'Starting...' : 'Launch Run'}</span>
            </button>
          )}

          {job.state !== 'ARCHIVED' && (
            <button
              type="button"
              disabled={actionLoading === 'archive'}
              onClick={() => setShowArchiveConfirm(true)}
              className="p-1.5 rounded text-[#73737c] hover:text-rose-400 hover:bg-[#171719] transition-colors border border-transparent hover:border-white/[0.07] disabled:opacity-50"
              title="Archive Job"
            >
              <Archive className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Section: Configuration */}
      <div className="space-y-3">
        <h2 className="text-xs font-semibold text-[#f3f3f4]">
          Configuration
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.07] bg-[#121214] rounded border border-white/[0.07]">
          {/* Dataset Build */}
          <div className="p-3.5 space-y-1">
            <div className="text-[11px] text-[#73737c]">Dataset Build</div>
            <div className="text-xs font-medium text-[#f3f3f4] font-mono truncate" title={req.dataset_build_id}>
              {req.dataset_build_id}
            </div>
            <div className="text-[11px] text-[#73737c]">
              {resv?.dataset?.batch_size ? `Batch ${resv.dataset.batch_size}` : 'Partitioned'}
            </div>
          </div>

          {/* Model */}
          <div className="p-3.5 space-y-1">
            <div className="text-[11px] text-[#73737c]">Model</div>
            <div className="text-xs font-medium text-[#f3f3f4]">
              {resv?.model?.architecture_name || req.model_id}
            </div>
            <div className="text-[11px] text-[#73737c]">
              {resv?.model?.parameter_count ? `${(resv.model.parameter_count / 1_000_000).toFixed(1)}M params` : 'Neural Network'}
            </div>
          </div>

          {/* Training */}
          <div className="p-3.5 space-y-1">
            <div className="text-[11px] text-[#73737c]">Training</div>
            <div className="text-xs font-medium text-[#f3f3f4]">
              {req.epochs} Epochs
            </div>
            <div className="text-[11px] text-[#73737c]">
              LR: {req.learning_rate} · Seed {req.training_seed}
            </div>
          </div>

          {/* Distributed training */}
          <div className="p-3.5 space-y-1">
            <div className="text-[11px] text-[#73737c]">Distributed Training</div>
            <div className="text-xs font-medium text-[#f3f3f4]">
              {req.training_strategy === 'strict_bsp' ? 'Strict BSP' : req.training_strategy}
            </div>
            <div className="text-[11px] text-[#73737c]">
              {resv?.synchronization?.expected_workers || 3} Workers
            </div>
          </div>

          {/* Checkpoint */}
          <div className="p-3.5 space-y-1">
            <div className="text-[11px] text-[#73737c]">Checkpoint Policy</div>
            <div className="text-xs font-medium text-[#f3f3f4]">
              {resv?.checkpoint_policy?.type || 'epoch_end'}
            </div>
            <div className="text-[11px] text-[#73737c]">
              Schema v{resv?.checkpoint_policy?.schema_version || 1}
            </div>
          </div>
        </div>

        {/* Collapsed Technical details */}
        <div>
          <button
            type="button"
            onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            className="flex items-center gap-1.5 text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors py-1"
          >
            <ChevronDown
              className={`w-3 h-3 transition-transform ${
                showTechnicalDetails ? 'rotate-180' : ''
              }`}
            />
            <span>Technical details</span>
          </button>

          {showTechnicalDetails && (
            <div className="mt-2 p-3.5 bg-[#121214] rounded border border-white/[0.07] space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Job ID</span>
                <CopyableId value={job.job_id} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Contract Hash</span>
                <CopyableId value={job.contract_hash || 'Unresolved'} />
              </div>
              {job.cloned_from_job_id && (
                <div className="flex items-center justify-between">
                  <span className="text-[#73737c]">Cloned From</span>
                  <Link to={`/jobs/${job.cloned_from_job_id}`} className="text-blue-400 hover:underline">
                    {job.cloned_from_job_id}
                  </Link>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Protocols</span>
                <span className="text-[#a1a1a8]">
                  DTP v{resv?.protocols?.dtp_version ?? 1} · MCP v{resv?.protocols?.mcp_version ?? 1}
                </span>
              </div>
              <div className="pt-2 border-t border-white/[0.07] flex justify-end">
                <button
                  type="button"
                  onClick={handleOpenRawContract}
                  className="inline-flex items-center gap-1 text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors"
                >
                  <FileCode className="w-3 h-3" />
                  <span>View raw configuration JSON</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Execution Attempts History */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Execution Attempts ({attempts.length})
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              History of distributed training runs executed for this job
            </p>
          </div>
        </div>

        <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                  <th className="py-2.5 px-3 font-medium">Attempt ID</th>
                  <th className="py-2.5 px-3 font-medium">State</th>
                  <th className="py-2.5 px-3 font-medium">Mode</th>
                  <th className="py-2.5 px-3 font-medium">Strategy</th>
                  <th className="py-2.5 px-3 font-medium">Failure Code</th>
                  <th className="py-2.5 px-3 font-medium">Started</th>
                  <th className="py-2.5 px-3 font-medium">Ended</th>
                  <th className="py-2.5 px-3 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {attempts.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-[#73737c]">
                      No execution attempts recorded for this job.
                    </td>
                  </tr>
                ) : (
                  attempts.map(att => (
                    <tr key={att.attempt_id} className="hover:bg-[#171719] transition-colors">
                      <td className="py-2.5 px-3 font-mono font-medium text-[#f3f3f4]">
                        {att.attempt_id}
                      </td>
                      <td className="py-2.5 px-3">
                        <AttemptStateBadge state={att.state} />
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {att.execution_mode}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c]">
                        {att.training_strategy || 'strict_bsp'}
                      </td>
                      <td className="py-2.5 px-3 text-rose-400 font-mono text-[11px]">
                        {att.failure_code || '—'}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                        {att.started_at ? att.started_at.slice(0, 19).replace('T', ' ') : '—'}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                        {att.ended_at ? att.ended_at.slice(0, 19).replace('T', ' ') : '—'}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {att.state === 'RUNNING' ? (
                          <Link
                            to="/live"
                            className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 font-medium"
                          >
                            <Activity className="w-3 h-3" />
                            <span>Live Run</span>
                          </Link>
                        ) : (
                          <span className="text-[#73737c] text-xs">
                            {att.state === 'COMPLETED' ? 'Finished' : att.state}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Confirmation Modal */}
      <ConfirmationModal
        isOpen={showArchiveConfirm}
        onClose={() => setShowArchiveConfirm(false)}
        onConfirm={handleArchive}
        title="Archive Training Job"
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Are you sure you want to archive <strong className="text-[#f3f3f4]">{job.display_name}</strong>?
            </p>
            <p>
              The job specification will be hidden from new executions. Historical attempts and checkpoints will remain securely accessible.
            </p>
          </div>
        }
      />
    </div>
  );
};
