import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Plus,
  Play,
  Copy,
  Archive,
  Search,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  ChevronLeft,
} from 'lucide-react';
import { JobStateBadge, AttemptStateBadge } from '../components/common/Badge';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { jobsService } from '../api';
import { JobListItemData, JobState } from '../types/api';

export const JobsPage: React.FC = () => {
  const navigate = useNavigate();

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

  // Confirmation Modal
  const [jobToArchive, setJobToArchive] = useState<JobListItemData | null>(null);

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
      setJobs(res.data || []);
      setNextCursor(res.page?.next_cursor || null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load training jobs');
    } finally {
      setLoading(false);
    }
  }, [stateFilter, searchQuery]);

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
      const attemptId = res.data.attempt_id;
      // Navigate to job detail or live attempt
      navigate(`/jobs/${jobId}`);
    } catch (err: any) {
      alert(`Failed to start job: ${err?.message || 'Unknown error'}`);
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

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="text-[11px] text-[#73737c]">Jobs</div>
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

        <div className="flex items-center gap-2">
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
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                stateFilter === st
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
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium">Job Name</th>
                <th className="py-2.5 px-3 font-medium">State</th>
                <th className="py-2.5 px-3 font-medium">Dataset Build</th>
                <th className="py-2.5 px-3 font-medium">Model</th>
                <th className="py-2.5 px-3 font-medium">Strategy</th>
                <th className="py-2.5 px-3 font-medium text-center">Attempts</th>
                <th className="py-2.5 px-3 font-medium">Latest Run</th>
                <th className="py-2.5 px-3 font-medium">Created</th>
                <th className="py-2.5 px-3.5 font-medium text-right">Actions</th>
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

                    <td className="py-2.5 px-3 text-[#a1a1a8] font-mono text-[11px]">
                      {job.dataset_build_id || '—'}
                    </td>

                    <td className="py-2.5 px-3 text-[#a1a1a8]">
                      {(job.model_id || 'ResNet-18').replace('model_', '').replace('_standard', '').replace('_', ' ')}
                    </td>

                    <td className="py-2.5 px-3 text-[#73737c]">
                      {job.training_strategy === 'strict_bsp' ? 'Strict BSP' : (job.training_strategy || 'Strict BSP')}
                    </td>

                    <td className="py-2.5 px-3 text-center text-[#f3f3f4]">
                      {job.attempt_count}
                    </td>

                    <td className="py-2.5 px-3">
                      {job.latest_attempt ? (
                        <AttemptStateBadge state={job.latest_attempt.state} />
                      ) : (
                        <span className="text-[#73737c]">None</span>
                      )}
                    </td>

                    <td className="py-2.5 px-3 text-[#73737c] text-[11px]">
                      {job.created_at ? job.created_at.slice(0, 10) : '—'}
                    </td>

                    <td className="py-2.5 px-3.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {job.state === 'READY' && (
                          <button
                            type="button"
                            disabled={actionLoading === `launch_${job.job_id}`}
                            onClick={() => handleLaunch(job.job_id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors disabled:opacity-50"
                            title="Launch Training Run"
                          >
                            <Play className="w-3 h-3 text-[#73737c]" />
                            <span>{actionLoading === `launch_${job.job_id}` ? 'Starting...' : 'Run'}</span>
                          </button>
                        )}

                        <button
                          type="button"
                          disabled={actionLoading === `clone_${job.job_id}`}
                          onClick={() => handleClone(job.job_id)}
                          className="p-1 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.05] transition-colors disabled:opacity-50"
                          title="Clone Job Specification"
                        >
                          <Copy className="w-3.5 h-3.5" />
                        </button>

                        {job.state !== 'ARCHIVED' && (
                          <button
                            type="button"
                            disabled={actionLoading === `archive_${job.job_id}`}
                            onClick={() => setJobToArchive(job)}
                            className="p-1 rounded text-[#73737c] hover:text-rose-400 hover:bg-white/[0.05] transition-colors disabled:opacity-50"
                            title="Archive Job"
                          >
                            <Archive className="w-3.5 h-3.5" />
                          </button>
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

      {/* Confirmation Modal */}
      <ConfirmationModal
        isOpen={!!jobToArchive}
        onClose={() => setJobToArchive(null)}
        onConfirm={handleArchiveConfirm}
        title="Archive Training Job"
        message={
          <div className="space-y-2 text-xs text-[#B4B4BA]">
            <p>
              Are you sure you want to archive job <strong className="text-[#F5F5F5]">{jobToArchive?.display_name}</strong>?
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
