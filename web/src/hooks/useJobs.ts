import { useState, useEffect, useCallback } from 'react';
import { jobsApi } from '../api/jobs';
import type { JobListItem, JobDetail } from '../domain/types';

interface UseJobListResult {
  jobs: JobListItem[];
  loading: boolean;
  error: string | null;
  nextCursor: string | null;
  refresh: () => void;
  loadMore: () => void;
}

export function useJobList(state?: string): UseJobListResult {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const fetch = useCallback(async (cursor?: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await jobsApi.list({ state, limit: 50, cursor });
      if (cursor) {
        setJobs(prev => [...prev, ...res.data]);
      } else {
        setJobs(res.data);
      }
      setNextCursor(res.page.next_cursor);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [state]);

  useEffect(() => { fetch(); }, [fetch]);

  return {
    jobs,
    loading,
    error,
    nextCursor,
    refresh: () => fetch(),
    loadMore: () => nextCursor ? fetch(nextCursor) : undefined,
  };
}

interface UseJobDetailResult {
  job: JobDetail | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useJobDetail(jobId: string | null): UseJobDetailResult {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!jobId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await jobsApi.get(jobId);
      // API returns { data: JobDetail } or JobDetail directly based on our router
      const detail = (res as unknown as { data?: JobDetail }).data ?? (res as unknown as JobDetail);
      setJob(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setJob(null);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => { fetch(); }, [fetch]);

  return { job, loading, error, refresh: fetch };
}
