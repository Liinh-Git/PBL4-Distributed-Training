import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Plus,
  Play,
  Pencil,
  Copy,
  Archive,
  Search,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
  Square,
  Activity,
  ExternalLink,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { JobStateBadge, AttemptStateBadge } from '../components/common/Badge';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { EditJobModal } from '../components/common/EditJobModal';
import { jobsService, attemptsService, datasetsService, datasetBuildsService } from '../api';
import {
  JobListItemData,
  JobState,
  isActiveAttemptState,
  isAbortableAttemptState,
  isTerminalAttemptState,
} from '../types/api';

const formatModelName = (modelId?: string | null): string => {
  if (!modelId) return 'ResNet-18';
  if (modelId === 'resnet18_groupnorm') return 'ResNet-18 (GroupNorm)';
  if (modelId === 'resnet18_standard') return 'ResNet-18 (Standard)';
  return modelId
    .replace(/^model_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
};

export const JobsPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    clusterActiveAttempt,
    isClusterActiveLoading,
    clusterActiveError,
    refreshClusterActiveAttempt,
    isAttemptAborting,
    markAttemptAborting,
    unmarkAttemptAborting,
  } = useApp();

  // API State
  const [jobs, setJobs] = useState<JobListItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Filter and Pagination State
  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<string>('ALL');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);

  // Modals
  const [jobToEdit, setJobToEdit] = useState<JobListItemData | null>(null);
  const [jobToArchive, setJobToArchive] = useState<JobListItemData | null>(null);
  const [jobToStart, setJobToStart] = useState<JobListItemData | null>(null);
  const [attemptToAbort, setAttemptToAbort] = useState<{
    jobId: string;
    attemptId: string;
    displayName: string;
  } | null>(null);

  // Datasets and Builds Mapping for Display
  const [datasetsMap, setDatasetsMap] = useState<Map<string, string>>(new Map());
  const [buildsMap, setBuildsMap] = useState<Map<string, string>>(new Map());
  const [defaultDatasetId, setDefaultDatasetId] = useState<string>('cifar10');

  useEffect(() => {
    const loadDatasetsAndBuilds = async () => {
      try {
        const [dsRes, buildsRes] = await Promise.allSettled([
          datasetsService.listDatasets({ limit: 100 }),
          datasetBuildsService.listBuilds({ limit: 100 }),
        ]);

        const dsMap = new Map<string, string>();
        if (dsRes.status === 'fulfilled' && dsRes.value.data) {
          for (const ds of dsRes.value.data) {
            dsMap.set(ds.dataset_id, ds.name);
          }
          if (dsRes.value.data.length > 0) {
            setDefaultDatasetId(dsRes.value.data[0].dataset_id);
          }
        }

        const bMap = new Map<string, string>();
        if (buildsRes.status === 'fulfilled' && buildsRes.value.data) {
          for (const b of buildsRes.value.data) {
            bMap.set(b.dataset_build_id, b.dataset_id);
          }
        }

        setDatasetsMap(dsMap);
        setBuildsMap(bMap);
      } catch {
        // Fallback gracefully
      }
    };

    loadDatasetsAndBuilds();
  }, []);

  const resolveDataset = (buildId?: string | null) => {
    if (!buildId) return null;
    let datasetId = buildsMap.get(buildId) || (datasetsMap.has(buildId) ? buildId : null);
    if (!datasetId) {
      datasetId = defaultDatasetId;
    }
    const rawName = datasetsMap.get(datasetId) || (datasetId.toLowerCase().includes('cifar') ? 'CIFAR-10' : datasetId);
    return {
      datasetId,
      name: rawName,
    };
  };



  const fetchJobs = useCallback(async (cursor?: string | null) => {
    try {
      setLoading(true);
      setError(null);

      const params = {
        state: stateFilter !== 'ALL' ? (stateFilter as JobState) : undefined,
        q: searchQuery.trim() || undefined,
        cursor: cursor || undefined,
        limit: 20,
      };

      const res = await jobsService.listJobs(params);
      const jobsList = res.data || [];
      setJobs(jobsList);
      setNextCursor(res.page?.next_cursor || null);

      // Clean up aborting state for attempts that have reached a terminal state
      for (const j of jobsList) {
        if (j.latest_attempt && isTerminalAttemptState(j.latest_attempt.state)) {
          unmarkAttemptAborting(j.latest_attempt.attempt_id);
        }
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load training jobs');
    } finally {
      setLoading(false);
    }
  }, [stateFilter, searchQuery, unmarkAttemptAborting]);

  useEffect(() => {
    setCursorHistory([]);
    fetchJobs();
  }, [fetchJobs]);

  const handleNextPage = () => {
    if (!nextCursor) return;
    setCursorHistory(prev => [...prev, nextCursor]);
    fetchJobs(nextCursor);
  };

  const handlePrevPage = () => {
    if (cursorHistory.length === 0) return;
    const newHistory = [...cursorHistory];
    newHistory.pop();
    const prevCursor = newHistory.length > 0 ? newHistory[newHistory.length - 1] : null;
    setCursorHistory(newHistory);
    fetchJobs(prevCursor);
  };

  const handleLaunch = async (jobId: string) => {
    try {
      setActionLoading(`launch_${jobId}`);
      const res = await jobsService.startJob(jobId);
      const attemptId = res.data?.attempt_id;
      await refreshClusterActiveAttempt();
      if (attemptId) {
        navigate(`/live?attempt_id=${encodeURIComponent(attemptId)}`);
      } else {
        navigate(`/jobs/${jobId}`);
      }
    } catch (err: any) {
      await refreshClusterActiveAttempt();
      await fetchJobs();
      const isConflict =
        err?.status === 409 ||
        err?.code === 'ACTIVE_ATTEMPT_EXISTS' ||
        err?.isConflict ||
        err?.message?.includes('ACTIVE_ATTEMPT_EXISTS');
      if (isConflict) {
        alert(
          `Cannot launch training: ${
            err?.message ||
            'The cluster is currently busy with another active training attempt. Only one attempt can run globally at a time.'
          }`
        );
      } else {
        alert(`Failed to start job: ${err?.message || 'Unknown error'}`);
      }
    } finally {
      setActionLoading(null);
    }
  };

  const handleClone = async (jobId: string) => {
    try {
      setActionLoading(`clone_${jobId}`);
      const res = await jobsService.cloneJob(jobId);
      const newJobId = res.data.job_id;
      navigate(`/jobs/${newJobId}`);
    } catch (err: any) {
      alert(`Failed to clone job: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleArchiveConfirm = async () => {
    if (!jobToArchive) return;
    try {
      setActionLoading(`archive_${jobToArchive.job_id}`);
      await jobsService.archiveJob(jobToArchive.job_id);
      setJobToArchive(null);
      await fetchJobs();
    } catch (err: any) {
      alert(`Failed to archive job: ${err?.message || 'Unknown error'}`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleAbortConfirm = async () => {
    if (!attemptToAbort) return;
    const attemptId = attemptToAbort.attemptId;
    markAttemptAborting(attemptId);
    setActionLoading(`abort_${attemptId}`);
    try {
      await attemptsService.abortAttempt(attemptId, {
        reason: 'Operator aborted attempt from jobs dashboard',
      });
      // HTTP 202 Accepted means the abort request was accepted by Runtime.
      // Do NOT set ABORTED state immediately; the attempt is shutting down.
      setAttemptToAbort(null);
      await refreshClusterActiveAttempt();
      await fetchJobs();
    } catch (err: any) {
      unmarkAttemptAborting(attemptId);
      const isConflict =
        err?.status === 409 ||
        err?.code === 'ATTEMPT_NOT_ABORTABLE' ||
        err?.code === 'ATTEMPT_ALREADY_TERMINAL' ||
        err?.message?.includes('409') ||
        err?.message?.includes('conflict');
      if (isConflict) {
        alert(
          `Cannot abort attempt: ${
            err?.message ||
            'Attempt is not in an abortable state or has already ended.'
          }`
        );
      } else {
        alert(`Failed to abort attempt: ${err?.message || 'Unknown error'}`);
      }
      await refreshClusterActiveAttempt();
      await fetchJobs();
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Training Jobs
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Loading API...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Saved training configurations and execution history.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={() => fetchJobs()}
            disabled={loading}
            className="p-1.5 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] transition-colors border border-white/[0.07]"
            title="Refresh job list"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors w-fit"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New training</span>
          </Link>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => fetchJobs()}
            className="px-2 py-1 bg-rose-500/20 hover:bg-rose-500/30 rounded text-rose-200 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Cluster Busy Banner */}
      {clusterActiveAttempt && (
        <div className="p-3 bg-amber-500/10 border border-amber-500/25 rounded flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 text-xs text-amber-200">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 shrink-0 text-amber-400" />
            <div className="space-y-0.5">
              <div>
                <span className="font-semibold text-amber-100">Cluster Busy:</span>{' '}
                <span>
                  Job <strong className="text-white">"{clusterActiveAttempt.job_name || clusterActiveAttempt.job_id}"</strong> is actively executing training attempt ({clusterActiveAttempt.attempt_id} · {clusterActiveAttempt.state}).
                </span>
              </div>
              <div className="text-[11px] text-amber-300/80">
                The cluster allows at most one active attempt across all jobs. Launching other jobs is disabled until this run completes.
              </div>
            </div>
          </div>
          <Link
            to={`/live?attempt_id=${encodeURIComponent(clusterActiveAttempt.attempt_id)}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 border border-amber-500/30 text-xs font-medium transition-colors shrink-0 self-start sm:self-auto"
          >
            <Activity className="w-3.5 h-3.5 text-amber-300" />
            <span>View Active Run</span>
            <ExternalLink className="w-3 h-3 text-amber-300/70" />
          </Link>
        </div>
      )}

      {/* Cluster Status Unverified Banner */}
      {clusterActiveError && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between gap-2 text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>Cluster status unverified: {clusterActiveError}. Launching new runs is disabled until cluster status is confirmed.</span>
          </div>
          <button
            type="button"
            onClick={() => refreshClusterActiveAttempt()}
            className="px-2 py-1 bg-rose-500/20 hover:bg-rose-500/30 rounded text-rose-200 transition-colors shrink-0"
          >
            Retry Verification
          </button>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-2">
        <div className="relative flex-1 w-full">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
          <input
            type="text"
            placeholder="Search jobs, models, datasets..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="flex items-center gap-0.5 bg-[#121214] border border-white/[0.07] rounded p-0.5 self-start sm:self-auto">
          {['ALL', 'READY', 'DRAFT', 'ARCHIVED'].map(st => (
            <button
              key={st}
              type="button"
              onClick={() => setStateFilter(st)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${stateFilter === st
                  ? 'bg-white/[0.08] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#a1a1a8]'
                }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Jobs Directory Table */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs table-auto">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium w-[24%] min-w-[160px]">Job Name</th>
                <th className="py-2.5 px-3 font-medium w-[9%] min-w-[80px]">State</th>
                <th className="py-2.5 px-3 font-medium w-[18%] min-w-[150px]">Dataset</th>
                <th className="py-2.5 px-3 font-medium w-[13%] min-w-[110px]">Model</th>
                <th className="py-2.5 px-3 font-medium w-[11%] min-w-[100px]">Strategy</th>
                <th className="py-2.5 px-3 font-medium text-center w-[7%] min-w-[70px]">Attempts</th>
                <th className="py-2.5 px-3 font-medium w-[10%] min-w-[90px]">Latest Run</th>
                <th className="py-2.5 px-3 font-medium w-[8%] min-w-[85px]">Created</th>
                <th className="py-2.5 px-3.5 font-medium text-left w-[190px] min-w-[190px] shrink-0">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && jobs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-[#73737c]">
                    <div className="flex items-center justify-center gap-2">
                      <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
                      <span>Loading training jobs...</span>
                    </div>
                  </td>
                </tr>
              ) : jobs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-10 text-center text-[#73737c]">
                    No training jobs found matching the selected filter.
                  </td>
                </tr>
              ) : (
                jobs.map(job => (
                  <tr
                    key={job.job_id}
                    className="hover:bg-[#171719] transition-colors group"
                  >
                    <td className="py-2.5 px-3.5">
                      <Link
                        to={`/jobs/${job.job_id}`}
                        className="font-medium text-[#f3f3f4] hover:text-blue-400 flex items-center gap-1 transition-colors"
                      >
                        <span>{job.display_name}</span>
                        <ChevronRight className="w-3 h-3 opacity-0 group-hover:opacity-100 text-[#73737c] transition-opacity" />
                      </Link>
                    </td>

                    <td className="py-2.5 px-3">
                      <JobStateBadge state={job.state} />
                    </td>

                    <td className="py-2.5 px-3">
                      {(() => {
                        const ds = resolveDataset(job.dataset_build_id);
                        if (ds) {
                          return (
                            <Link
                              to={`/datasets/${encodeURIComponent(ds.datasetId)}`}
                              className="font-medium text-[#f3f3f4] hover:text-blue-400 transition-colors inline-flex items-center gap-1 group/ds"
                              title={`View Dataset: ${ds.name}`}
                            >
                              <span>{ds.name}</span>
                              <ChevronRight className="w-3 h-3 text-[#73737c] opacity-0 group-hover/ds:opacity-100 transition-opacity" />
                            </Link>
                          );
                        }
                        return <span className="text-[#73737c]">—</span>;
                      })()}
                    </td>

                    <td className="py-2.5 px-3 text-[#a1a1a8]">
                      {formatModelName(job.model_id)}
                    </td>

                    <td className="py-2.5 px-3 text-[#73737c]">
                      {job.training_strategy === 'strict_bsp' ? 'Strict BSP' : (job.training_strategy || 'Strict BSP')}
                    </td>

                    <td className="py-2.5 px-3 text-center text-[#f3f3f4]">
                      {job.attempt_count}
                    </td>

                    <td className="py-2.5 px-3">
                      {job.latest_attempt ? (
                        <Link
                          to={`/live?attempt_id=${job.latest_attempt.attempt_id}`}
                          title="Inspect live training attempt"
                          className="hover:opacity-85 transition-opacity inline-flex items-center"
                        >
                          <AttemptStateBadge
                            state={job.latest_attempt.state}
                            isAborting={isAttemptAborting(job.latest_attempt.attempt_id)}
                          />
                        </Link>
                      ) : (
                        <span className="text-[#73737c]">None</span>
                      )}
                    </td>

                    <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                      {job.created_at ? job.created_at.slice(0, 10) : '—'}
                    </td>

                    <td className="py-2.5 px-3.5 text-left w-[190px] min-w-[190px] shrink-0">
                      <div className="flex items-center justify-start gap-1.5">
                        {/* Slot 1: Run or Abort */}
                        {(() => {
                          const isThisJobActive = Boolean(
                            (clusterActiveAttempt && clusterActiveAttempt.job_id === job.job_id) ||
                            (job.latest_attempt && isActiveAttemptState(job.latest_attempt.state))
                          );
                          const isAnotherJobActive = Boolean(
                            clusterActiveAttempt && clusterActiveAttempt.job_id !== job.job_id
                          );
                          const activeAttemptId =
                            (clusterActiveAttempt && clusterActiveAttempt.job_id === job.job_id
                              ? clusterActiveAttempt.attempt_id
                              : null) || job.latest_attempt?.attempt_id;

                          if (job.latest_attempt && isAttemptAborting(job.latest_attempt.attempt_id)) {
                            return (
                              <button
                                type="button"
                                disabled
                                className="inline-flex items-center justify-center gap-1 w-20 py-1 text-xs rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 cursor-wait shrink-0"
                                title="Abort request accepted; waiting for attempt to terminate..."
                              >
                                <RefreshCw className="w-3 h-3 animate-spin text-amber-400" />
                                <span>Aborting...</span>
                              </button>
                            );
                          }

                          if (job.latest_attempt && isAbortableAttemptState(job.latest_attempt.state)) {
                            return (
                              <button
                                type="button"
                                disabled={actionLoading === `abort_${job.latest_attempt.attempt_id}`}
                                onClick={() => setAttemptToAbort({
                                  jobId: job.job_id,
                                  attemptId: job.latest_attempt!.attempt_id,
                                  displayName: job.display_name,
                                })}
                                className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 transition-colors shrink-0"
                                title="Abort running attempt"
                              >
                                <Square className="w-3 h-3 fill-rose-400 text-rose-400" />
                                <span>{actionLoading === `abort_${job.latest_attempt.attempt_id}` ? '...' : 'Abort'}</span>
                              </button>
                            );
                          }

                          if (isThisJobActive && activeAttemptId) {
                            return (
                              <Link
                                to={`/live?attempt_id=${encodeURIComponent(activeAttemptId)}`}
                                className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors shrink-0"
                                title={`View active running attempt (${activeAttemptId})`}
                              >
                                <Activity className="w-3 h-3" />
                                <span>View</span>
                              </Link>
                            );
                          }

                          if (job.state === 'READY' || job.state === 'DRAFT') {
                            if (isAnotherJobActive) {
                              return (
                                <button
                                  type="button"
                                  disabled
                                  className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-[#171719]/40 text-[#73737c]/50 border border-white/[0.04] cursor-not-allowed shrink-0"
                                  title={`Cluster is busy: Job "${clusterActiveAttempt?.job_name || clusterActiveAttempt?.job_id}" currently has an active training attempt.`}
                                >
                                  <Play className="w-3 h-3 opacity-30" />
                                  <span>Run</span>
                                </button>
                              );
                            }

                            if (isClusterActiveLoading) {
                              return (
                                <button
                                  type="button"
                                  disabled
                                  className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-[#171719]/40 text-[#73737c]/50 border border-white/[0.04] cursor-wait shrink-0"
                                  title="Checking cluster status..."
                                >
                                  <RefreshCw className="w-3 h-3 animate-spin text-blue-400/60" />
                                  <span>Run</span>
                                </button>
                              );
                            }

                            if (clusterActiveError) {
                              return (
                                <button
                                  type="button"
                                  disabled
                                  className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-[#171719]/40 text-rose-400/50 border border-rose-500/20 cursor-not-allowed shrink-0"
                                  title={`Cluster status unverified: ${clusterActiveError}`}
                                >
                                  <AlertCircle className="w-3 h-3 opacity-40 text-rose-400" />
                                  <span>Run</span>
                                </button>
                              );
                            }

                            return (
                              <button
                                type="button"
                                disabled={actionLoading === `launch_${job.job_id}`}
                                onClick={() => {
                                  if (job.state === 'DRAFT') {
                                    setJobToStart(job);
                                  } else {
                                    handleLaunch(job.job_id);
                                  }
                                }}
                                className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors disabled:opacity-50 shrink-0"
                                title={job.state === 'DRAFT' ? "Start Training (freeze draft to READY)" : "Launch Training Run"}
                              >
                                <Play className="w-3 h-3 text-[#73737c]" />
                                <span>{actionLoading === `launch_${job.job_id}` ? '...' : 'Run'}</span>
                              </button>
                            );
                          }

                          return (
                            <button
                              type="button"
                              disabled
                              className="inline-flex items-center justify-center gap-1 w-16 py-1 text-xs rounded bg-[#171719]/40 text-[#73737c]/30 border border-white/[0.03] cursor-not-allowed shrink-0"
                              title="Archived jobs cannot be run"
                            >
                              <Play className="w-3 h-3 opacity-30" />
                              <span>Run</span>
                            </button>
                          );
                        })()}

                        {/* Slot 2: Edit */}
                        {job.state === 'DRAFT' || job.state === 'READY' ? (
                          <button
                            type="button"
                            onClick={() => setJobToEdit(job)}
                            className="w-7 h-7 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] transition-colors inline-flex items-center justify-center shrink-0 cursor-pointer"
                            title={job.state === 'DRAFT' ? "Edit Draft Job" : "Edit Job"}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <span
                            className="w-7 h-7 rounded text-[#73737c]/20 inline-flex items-center justify-center cursor-not-allowed shrink-0"
                            title="Archived jobs cannot be edited"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </span>
                        )}

                        {/* Slot 3: Clone */}
                        <button
                          type="button"
                          disabled={actionLoading === `clone_${job.job_id}`}
                          onClick={() => handleClone(job.job_id)}
                          className="w-7 h-7 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] transition-colors disabled:opacity-50 inline-flex items-center justify-center shrink-0"
                          title="Clone Job Specification"
                        >
                          <Copy className="w-3.5 h-3.5" />
                        </button>

                        {/* Slot 4: Archive */}
                        {job.state !== 'ARCHIVED' ? (
                          <button
                            type="button"
                            disabled={actionLoading === `archive_${job.job_id}`}
                            onClick={() => setJobToArchive(job)}
                            className="w-7 h-7 rounded text-[#73737c] hover:text-rose-400 hover:bg-white/[0.05] transition-colors disabled:opacity-50 inline-flex items-center justify-center shrink-0"
                            title="Archive Job"
                          >
                            <Archive className="w-3.5 h-3.5" />
                          </button>
                        ) : (
                          <span
                            className="w-7 h-7 rounded text-[#73737c]/20 inline-flex items-center justify-center cursor-not-allowed shrink-0"
                            title="Job is already archived"
                          >
                            <Archive className="w-3.5 h-3.5" />
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        <div className="px-3.5 py-2.5 border-t border-white/[0.07] flex items-center justify-between text-xs text-[#73737c]">
          <span>Showing {jobs.length} jobs</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handlePrevPage}
              disabled={cursorHistory.length === 0 || loading}
              className="px-2.5 py-1 rounded bg-[#171719] border border-white/[0.07] text-[#f3f3f4] hover:bg-[#202024] disabled:opacity-30 disabled:pointer-events-none flex items-center gap-1 transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous</span>
            </button>
            <button
              type="button"
              onClick={handleNextPage}
              disabled={!nextCursor || loading}
              className="px-2.5 py-1 rounded bg-[#171719] border border-white/[0.07] text-[#f3f3f4] hover:bg-[#202024] disabled:opacity-30 disabled:pointer-events-none flex items-center gap-1 transition-colors"
            >
              <span>Next</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Start DRAFT Job Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!jobToStart}
        onClose={() => setJobToStart(null)}
        onConfirm={async () => {
          if (!jobToStart) return;
          const targetId = jobToStart.job_id;
          setJobToStart(null);
          await handleLaunch(targetId);
        }}
        title="Start Training Run?"
        confirmLabel="Start Training"
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Job <strong className="text-[#f3f3f4]">{jobToStart?.display_name}</strong> is currently in <span className="font-mono text-[#f3f3f4]">DRAFT</span>.
            </p>
            <p>
              Starting the job will validate and freeze its configuration into <span className="font-mono text-[#f3f3f4]">READY</span> state and launch a training attempt. Once frozen, training settings cannot be edited directly.
            </p>
          </div>
        }
      />

      {/* Archive Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!jobToArchive}
        onClose={() => setJobToArchive(null)}
        onConfirm={handleArchiveConfirm}
        title="Archive Training Job"
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Are you sure you want to archive job <strong className="text-[#f3f3f4]">{jobToArchive?.display_name}</strong>?
            </p>
            <p>
              The job specification will be hidden from new executions. Historical attempts and checkpoints will remain securely accessible.
            </p>
          </div>
        }
      />

      {/* Abort Attempt Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!attemptToAbort}
        onClose={() => setAttemptToAbort(null)}
        onConfirm={handleAbortConfirm}
        isLoading={Boolean(attemptToAbort && actionLoading === `abort_${attemptToAbort.attemptId}`)}
        title="Abort Training Attempt"
        confirmLabel="Abort Attempt"
        isDestructive={true}
        message={
          <div className="space-y-2 text-xs text-[#a1a1a8]">
            <p>
              Are you sure you want to abort the active training attempt for job <strong className="text-[#f3f3f4]">{attemptToAbort?.displayName}</strong>?
            </p>
            <p>
              The coordinator will signal all participating workers to stop immediately. The attempt will finalize and transition to <span className="text-rose-400 font-mono">ABORTED</span>.
            </p>
          </div>
        }
      />

      {/* Edit Job Modal */}
      <EditJobModal
        job={jobToEdit}
        isOpen={!!jobToEdit}
        onClose={() => setJobToEdit(null)}
        onSuccess={() => {
          setJobToEdit(null);
          fetchJobs(cursorHistory.length > 0 ? cursorHistory[cursorHistory.length - 1] : undefined);
        }}
      />
    </div>
  );
};
