import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Play,
  Layers,
  Server,
  Database,
  ShieldCheck,
  Check,
  X,
  Save,
  Briefcase,
  ChevronRight,
  Plus,
  RefreshCw,
} from 'lucide-react';
import { AttemptStateBadge, Badge } from '../components/common/Badge';
import { formatDiagnosticEvent, EventIconType } from '../utils/eventFormatter';
import { EventDetailDrawer } from '../components/drawers/EventDetailDrawer';
import { DiagnosticEvent } from '../types';
import {
  jobsService,
  datasetsService,
  datasetBuildsService,
  checkpointsService,
  eventsService,
  attemptsService,
  systemService,
} from '../api';
import { AttemptListItemData, HealthData } from '../types/api';

interface ResourceState<T> {
  loading: boolean;
  error: boolean;
  data: T | null;
}

export const OverviewPage: React.FC = () => {
  const [jobsState, setJobsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [datasetsState, setDatasetsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [buildsState, setBuildsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [checkpointsState, setCheckpointsState] = useState<ResourceState<number>>({ loading: true, error: false, data: null });
  const [runningAttempt, setRunningAttempt] = useState<ResourceState<AttemptListItemData>>({ loading: true, error: false, data: null });
  const [eventsState, setEventsState] = useState<ResourceState<DiagnosticEvent[]>>({ loading: true, error: false, data: [] });
  const [healthState, setHealthState] = useState<ResourceState<HealthData>>({ loading: true, error: false, data: null });

  const [inspectEvent, setInspectEvent] = useState<DiagnosticEvent | null>(null);

  const fetchOverviewData = async () => {
    setJobsState(prev => ({ ...prev, loading: true, error: false }));
    setDatasetsState(prev => ({ ...prev, loading: true, error: false }));
    setBuildsState(prev => ({ ...prev, loading: true, error: false }));
    setCheckpointsState(prev => ({ ...prev, loading: true, error: false }));
    setRunningAttempt(prev => ({ ...prev, loading: true, error: false }));
    setEventsState(prev => ({ ...prev, loading: true, error: false }));
    setHealthState(prev => ({ ...prev, loading: true, error: false }));

    const [
      jobsRes,
      datasetsRes,
      buildsRes,
      checkpointsRes,
      attemptsRes,
      eventsRes,
      healthRes,
    ] = await Promise.allSettled([
      jobsService.listJobs({ limit: 100 }),
      datasetsService.listDatasets({ limit: 100 }),
      datasetBuildsService.listBuilds({ limit: 100 }),
      checkpointsService.listCheckpoints({ limit: 100 }),
      attemptsService.listAttempts({ state: 'RUNNING', limit: 1 }),
      eventsService.listEvents({ limit: 5 }),
      systemService.getHealth(),
    ]);

    // Jobs
    if (jobsRes.status === 'fulfilled') {
      setJobsState({ loading: false, error: false, data: jobsRes.value.data?.length ?? 0 });
    } else {
      setJobsState({ loading: false, error: true, data: null });
    }

    // Datasets
    if (datasetsRes.status === 'fulfilled') {
      setDatasetsState({ loading: false, error: false, data: datasetsRes.value.data?.length ?? 0 });
    } else {
      setDatasetsState({ loading: false, error: true, data: null });
    }

    // Builds
    if (buildsRes.status === 'fulfilled') {
      setBuildsState({ loading: false, error: false, data: buildsRes.value.data?.length ?? 0 });
    } else {
      setBuildsState({ loading: false, error: true, data: null });
    }

    // Checkpoints
    if (checkpointsRes.status === 'fulfilled') {
      setCheckpointsState({ loading: false, error: false, data: checkpointsRes.value.data?.length ?? 0 });
    } else {
      setCheckpointsState({ loading: false, error: true, data: null });
    }

    // Running attempt
    if (attemptsRes.status === 'fulfilled') {
      const active = attemptsRes.value.data && attemptsRes.value.data.length > 0 ? attemptsRes.value.data[0] : null;
      setRunningAttempt({ loading: false, error: false, data: active });
    } else {
      setRunningAttempt({ loading: false, error: true, data: null });
    }

    // Events
    if (eventsRes.status === 'fulfilled') {
      const rawEvents = eventsRes.value.data || [];
      const mappedEvents: DiagnosticEvent[] = rawEvents.map((evt, idx) => ({
        id: evt.event_id,
        time: evt.occurred_at ? new Date(evt.occurred_at).toLocaleTimeString() : 'now',
        scope: evt.scope?.type || 'SYSTEM',
        event: evt.event_type,
        severity: (evt.severity?.toUpperCase() || 'INFO') as any,
        runtimeSeq: idx + 1,
        source: evt.scope?.id || 'system',
        attemptId: evt.scope?.id || '',
        payload: { summary: evt.summary || evt.event_type },
        technicalCorrelationId: evt.event_id,
      }));
      setEventsState({ loading: false, error: false, data: mappedEvents });
    } else {
      setEventsState({ loading: false, error: true, data: [] });
    }

    // Health
    if (healthRes.status === 'fulfilled') {
      setHealthState({ loading: false, error: false, data: healthRes.value.data });
    } else {
      setHealthState({ loading: false, error: true, data: null });
    }
  };

  useEffect(() => {
    fetchOverviewData();
  }, []);

  const isHealthy =
    !healthState.error &&
    (healthState.data?.status === 'ok' || (healthState.data?.status as unknown as string) === 'healthy');

  const isTrainingActive = runningAttempt.data !== null && runningAttempt.data.state === 'RUNNING';

  const renderStatusIcon = (type: EventIconType) => {
    switch (type) {
      case 'success':
        return <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />;
      case 'warning':
        return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />;
      case 'error':
        return <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />;
      case 'normal':
      default:
        return <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0" />;
    }
  };

  return (
    <div className="w-full space-y-8 pb-12 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#f3f3f4]">
            Overview
          </h1>
          <p className="text-xs text-[#73737c] mt-0.5">
            Distributed cluster state and active training execution
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isTrainingActive && (
            <Link
              to={`/live?attemptId=${runningAttempt.data?.attempt_id}`}
              className="px-3 py-1.5 rounded text-xs font-normal text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              Live training
            </Link>
          )}
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New training</span>
          </Link>
        </div>
      </div>

      {/* Cluster Health Summary Row */}
      <div className="flex items-center justify-between py-2.5 px-3 bg-[#121214] rounded border border-white/[0.07] text-xs">
        <div className="flex items-center gap-2">
          {healthState.loading ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 text-blue-400 animate-spin" />
              <span className="text-[#a1a1a8]">Checking cluster connectivity...</span>
            </>
          ) : (
            <>
              <span className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className="text-[#f3f3f4] font-medium">
                {isHealthy ? 'Cluster operational' : 'Cluster attention needed'}
              </span>
              <span className="text-[#73737c]">·</span>
              <span className="text-[#a1a1a8]">
                {isHealthy
                  ? 'All services connected and responsive'
                  : healthState.error
                  ? 'Coordinator API unreachable'
                  : 'Degraded subsystems detected'}
              </span>
            </>
          )}
        </div>
        <Link to="/system" className="text-[#73737c] hover:text-[#f3f3f4] transition-colors text-xs">
          System details →
        </Link>
      </div>

      {/* Active Training Run Section OR Getting Started Guide */}
      {!isTrainingActive ? (
        <div className="p-6 bg-[#121214] border border-white/[0.07] rounded space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Start a training run
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Follow three simple steps to launch deterministic distributed training across your worker cluster.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">1</span>
                <span>Choose a dataset</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Select verified training data and a partitioned dataset build.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">2</span>
                <span>Configure model & training</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Select a neural network architecture and set hyperparameters.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">3</span>
                <span>Start distributed training</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Launch synchronized execution and monitor live progress.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 pt-1">
            <Link
              to="/training/new"
              className="px-3.5 py-1.5 rounded text-xs font-normal text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5 text-[#73737c]" />
              <span>Start configuration wizard</span>
            </Link>
            <Link
              to="/datasets"
              className="px-3.5 py-1.5 rounded text-xs text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              View datasets
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.07] pb-2">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-[#f3f3f4]">
                {runningAttempt.data?.attempt_id}
              </h2>
              <AttemptStateBadge state={runningAttempt.data?.state || 'RUNNING'} />
            </div>

            <Link
              to={`/live?attemptId=${runningAttempt.data?.attempt_id}`}
              className="text-xs text-blue-400 hover:text-blue-300 font-normal inline-flex items-center gap-1 transition-colors"
            >
              <span>Open live view</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {/* Quick Attempt Info */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 pt-2">
            <div>
              <div className="text-xs text-[#73737c]">Attempt ID</div>
              <div className="text-xs font-mono font-semibold text-[#f3f3f4] mt-0.5 truncate">
                {runningAttempt.data?.attempt_id}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Job ID</div>
              <div className="text-xs font-mono font-semibold text-[#f3f3f4] mt-0.5 truncate">
                {runningAttempt.data?.job_id}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Execution Mode</div>
              <div className="text-xs font-semibold text-[#f3f3f4] mt-0.5">
                {runningAttempt.data?.execution_mode || 'FRESH'}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Started At</div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                {runningAttempt.data?.started_at ? new Date(runningAttempt.data.started_at).toLocaleTimeString() : 'Recently'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cluster Resources Quick Strip */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-[#f3f3f4]">
          Resources
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Link
            to="/jobs"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Training Jobs</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {jobsState.loading ? 'Loading...' : jobsState.error ? 'Unavailable' : `${jobsState.data} registered`}
              </div>
            </div>

            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/datasets"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Datasets</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {datasetsState.loading || buildsState.loading
                  ? 'Loading...'
                  : datasetsState.error && buildsState.error
                  ? 'Unavailable'
                  : `${datasetsState.data ?? 0} datasets · ${buildsState.data ?? 0} builds`}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/checkpoints"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Checkpoints</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {checkpointsState.loading ? 'Loading...' : checkpointsState.error ? 'Unavailable' : `${checkpointsState.data} saved snapshots`}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/system"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Cluster Nodes</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {healthState.loading ? 'Checking...' : healthState.error ? 'Unavailable' : isHealthy ? 'Operational' : 'Attention needed'}
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>
        </div>
      </div>

      {/* Recent Activity Section (Flat List) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-white/[0.07] pb-2">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Recent Activity
            </h2>
          </div>
          <Link
            to="/events"
            className="text-xs text-blue-400 hover:text-blue-300 font-normal inline-flex items-center gap-1 transition-colors"
          >
            <span>All events</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {eventsState.loading ? (
          <div className="py-6 text-center text-xs text-[#73737c]">
            Loading audit activity...
          </div>
        ) : eventsState.error ? (
          <div className="py-4 text-center text-xs text-[#73737c]">
            Audit events unavailable from backend.
          </div>
        ) : (eventsState.data || []).length === 0 ? (
          <div className="py-6 text-center text-xs text-[#73737c]">
            No recent platform activity recorded.
          </div>
        ) : (
          <div className="divide-y divide-white/[0.05]">
            {(eventsState.data || []).slice(0, 5).map((evt, idx) => {
              const formatted = formatDiagnosticEvent(evt);
              const displayTime = evt.time && evt.time.length > 8 ? evt.time.slice(0, 8) : evt.time;

              return (
                <div
                  key={`${evt.id}-${evt.runtimeSeq ?? idx}`}
                  onClick={() => setInspectEvent(evt)}
                  className="py-2 flex items-center justify-between text-xs hover:bg-white/[0.02] cursor-pointer transition-colors px-1"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {renderStatusIcon(formatted.iconType)}
                    <span className="text-[#f3f3f4] font-normal truncate">
                      {formatted.humanText}
                    </span>
                  </div>

                  <div className="text-[#73737c] text-xs shrink-0 pl-3">
                    {displayTime}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Event Inspect Drawer */}
      <EventDetailDrawer
        event={inspectEvent}
        onClose={() => setInspectEvent(null)}
      />
    </div>
  );
};
