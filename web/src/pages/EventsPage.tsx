import React, { useState, useMemo, useEffect } from 'react';
import {
  Search,
  Activity,
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  ChevronRight,
  Filter,
  Check,
  X,
  Radio,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { SeverityBadge, Badge } from '../components/common/Badge';
import { formatDiagnosticEvent, EventIconType } from '../utils/eventFormatter';
import { DiagnosticEvent } from '../types';
import { eventsService } from '../api';
import { EventListItemData, EventSeverity, ScopeType } from '../types/api';

export const EventsPage: React.FC = () => {
  const { setSelectedEvent, currentAttempt } = useApp();

  const [apiEvents, setApiEvents] = useState<EventListItemData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [scopeFilter, setScopeFilter] = useState<string>('ALL');

  const fetchEvents = async (cursor?: string | null, append = false) => {
    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const params = {
        severity: severityFilter === 'ALL' ? undefined : (severityFilter.toLowerCase() as EventSeverity),
        scope_type: scopeFilter === 'ALL' ? undefined : (scopeFilter.toUpperCase() as ScopeType),
        cursor,
        limit: 50,
      };

      const res = await eventsService.listEvents(params);
      const data = res.data || [];
      setApiEvents(prev => (append ? [...prev, ...data] : data));
      setNextCursor(res.page?.next_cursor || null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load audit events');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchEvents();
  }, [severityFilter, scopeFilter]);

  // Convert API events to DiagnosticEvent format
  const events: DiagnosticEvent[] = useMemo(() => {
    return apiEvents.map((evt, idx) => ({
      id: evt.event_id,
      runtimeSeq: idx + 1,
      time: evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : 'now',
      scope: (evt.scope_type || 'SYSTEM').toLowerCase() as any,
      event: evt.event_type,
      severity: (evt.severity?.toUpperCase() || 'INFO') as any,
      actor: evt.scope_id || 'system',
      payloadSummary: evt.payload ? JSON.stringify(evt.payload) : undefined,
      humanText: evt.event_type.replace(/_/g, ' '),
    }));
  }, [apiEvents]);

  // Convert CamelCase/snake_case event names to human-readable strings
  const formatEventName = (rawName: string): string => {
    if (!rawName) return 'Event';
    const mapping: Record<string, string> = {
      GradientContributionAccepted: 'Gradient contribution accepted',
      GRADIENT_CONTRIBUTION_ACCEPTED: 'Gradient contribution accepted',
      StepCommitted: 'Step completed',
      STEP_COMMITTED: 'Step completed',
      StepStarted: 'Step started',
      STEP_STARTED: 'Step started',
      OptimizerUpdateComplete: 'Optimizer updated weights',
      OPTIMIZER_UPDATE_COMPLETE: 'Optimizer updated weights',
      WaitingForWorker: 'Waiting for worker',
      HeartbeatDelayed: 'Worker heartbeat delayed',
      WorkerHeartbeatWarning: 'Worker heartbeat delayed',
      CheckpointComplete: 'Checkpoint saved',
      CHECKPOINT_COMPLETE: 'Checkpoint saved',
      CheckpointStarted: 'Checkpoint started',
      CHECKPOINT_STARTED: 'Checkpoint started',
      AttemptStarted: 'Training attempt started',
      ATTEMPT_STARTED: 'Training attempt started',
      AttemptFinished: 'Training attempt completed',
      ATTEMPT_COMPLETED: 'Training attempt completed',
      AttemptFailed: 'Training attempt failed',
      ATTEMPT_FAILED: 'Training attempt failed',
      BarrierTimeoutWarning: 'Barrier threshold warning',
      DatasetBuildCompleted: 'Dataset build verified',
      DATASET_BUILD_READY: 'Dataset build verified',
      WorkerConnected: 'Worker connected',
      WORKER_CONNECTED: 'Worker connected',
      WorkerDisconnected: 'Worker disconnected',
      WORKER_DISCONNECTED: 'Worker disconnected',
    };

    if (mapping[rawName]) {
      return mapping[rawName];
    }

    return rawName
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .replace(/^./, str => str.toUpperCase())
      .trim();
  };

  const warningCount = useMemo(
    () => events.filter(e => e.severity === 'WARN').length,
    [events]
  );
  const errorCount = useMemo(
    () => events.filter(e => e.severity === 'ERROR' || e.severity === 'CRITICAL').length,
    [events]
  );

  const filteredEvents = useMemo(() => {
    return events.filter(evt => {
      const formatted = formatDiagnosticEvent(evt);
      const matchesSearch =
        evt.event.toLowerCase().includes(searchQuery.toLowerCase()) ||
        evt.scope.toLowerCase().includes(searchQuery.toLowerCase()) ||
        formatted.humanText.toLowerCase().includes(searchQuery.toLowerCase());

      return matchesSearch;
    });
  }, [events, searchQuery]);

  const renderStatusIcon = (type: EventIconType) => {
    switch (type) {
      case 'success':
        return (
          <span className="w-4 h-4 rounded-full bg-emerald-500/10 text-emerald-400 flex items-center justify-center shrink-0">
            <Check className="w-2.5 h-2.5 stroke-[2.5]" />
          </span>
        );
      case 'warning':
        return (
          <span className="w-4 h-4 rounded-full bg-amber-500/10 text-amber-400 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-2.5 h-2.5 stroke-[2.5]" />
          </span>
        );
      case 'error':
        return (
          <span className="w-4 h-4 rounded-full bg-rose-500/10 text-rose-400 flex items-center justify-center shrink-0">
            <X className="w-2.5 h-2.5 stroke-[2.5]" />
          </span>
        );
      case 'normal':
      default:
        return (
          <span className="w-4 h-4 flex items-center justify-center shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
          </span>
        );
    }
  };

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="text-[11px] text-[#73737c]">Diagnostics</div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Events
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Loading API...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Runtime events, worker sync states, and system notifications
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="text-xs text-[#73737c]">
            {events.length} total events
          </div>
          <button
            type="button"
            onClick={() => fetchEvents()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#121214] border border-white/[0.07] hover:bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] text-xs font-medium transition-colors"
            title="Refresh events"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
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
            onClick={() => fetchEvents()}
            className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Summary Strip */}
      <div className="bg-[#121214] border border-white/[0.07] rounded grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.07]">
        <div className="p-3">
          <div className="text-[11px] text-[#73737c]">Total Events</div>
          <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
            {events.length}
          </div>
        </div>

        <div className="p-3">
          <div className="text-[11px] text-[#73737c]">Warnings</div>
          <div className={`text-sm font-semibold mt-0.5 ${warningCount > 0 ? 'text-amber-400' : 'text-[#f3f3f4]'}`}>
            {warningCount}
          </div>
        </div>

        <div className="p-3">
          <div className="text-[11px] text-[#73737c]">Errors</div>
          <div className={`text-sm font-semibold mt-0.5 ${errorCount > 0 ? 'text-rose-400' : 'text-[#f3f3f4]'}`}>
            {errorCount}
          </div>
        </div>

        <div className="p-3">
          <div className="text-[11px] text-[#73737c]">Live Stream</div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="text-xs text-[#a1a1a8]">
              {currentAttempt.state === 'RUNNING' ? 'Active' : 'Idle'}
            </span>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col lg:flex-row items-center gap-2">
        {/* Search */}
        <div className="relative flex-1 w-full">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
          <input
            type="text"
            placeholder="Search events by message or topic..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>

        {/* Severity Filter */}
        <div className="flex items-center gap-0.5 bg-[#121214] border border-white/[0.07] rounded p-0.5 self-start lg:self-auto">
          {['ALL', 'INFO', 'WARN', 'ERROR'].map(sev => (
            <button
              key={sev}
              type="button"
              onClick={() => setSeverityFilter(sev)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                severityFilter === sev
                  ? 'bg-white/[0.08] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#a1a1a8]'
              }`}
            >
              {sev}
            </button>
          ))}
        </div>

        {/* Scope Filter */}
        <div className="flex items-center gap-0.5 bg-[#121214] border border-white/[0.07] rounded p-0.5 self-start lg:self-auto">
          {['ALL', 'JOB', 'WORKER', 'SYSTEM', 'DATASET'].map(scope => (
            <button
              key={scope}
              type="button"
              onClick={() => setScopeFilter(scope)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                scopeFilter === scope
                  ? 'bg-white/[0.08] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#a1a1a8]'
              }`}
            >
              {scope}
            </button>
          ))}
        </div>
      </div>

      {/* Main Events Table */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium w-24">Time</th>
                <th className="py-2.5 px-3 font-medium w-20">Severity</th>
                <th className="py-2.5 px-3 font-medium w-52">Event</th>
                <th className="py-2.5 px-3 font-medium w-24">Scope</th>
                <th className="py-2.5 px-3 font-medium">Summary</th>
                <th className="py-2.5 px-3.5 font-medium text-right w-20">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && events.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-[#73737c]">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
                      <span>Loading audit events...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredEvents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-[#73737c]">
                    No events found matching the active filters.
                  </td>
                </tr>
              ) : (
                filteredEvents.map((evt, idx) => {
                  const formatted = formatDiagnosticEvent(evt);
                  const displayTime = evt.time && evt.time.length > 8 ? evt.time.slice(0, 8) : evt.time;

                  return (
                    <tr
                      key={`${evt.id}-${evt.runtimeSeq ?? idx}`}
                      onClick={() => setSelectedEvent(evt)}
                      className="hover:bg-[#171719] cursor-pointer transition-colors group"
                    >
                      <td className="py-2.5 px-3.5 text-[#73737c] font-mono text-[11px] whitespace-nowrap">
                        {displayTime}
                      </td>

                      <td className="py-2.5 px-3">
                        <SeverityBadge severity={evt.severity} />
                      </td>

                      <td className="py-2.5 px-3">
                        <span className="font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                          {formatEventName(evt.event)}
                        </span>
                      </td>

                      <td className="py-2.5 px-3">
                        <span className="text-[#73737c] text-[11px] capitalize">
                          {evt.scope.replace('scope.', '').replace('_', ' ')}
                        </span>
                      </td>

                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-2 min-w-0">
                          {renderStatusIcon(formatted.iconType)}
                          <span className="text-[#a1a1a8] truncate">
                            {formatted.humanText}
                          </span>
                        </div>
                      </td>

                      <td className="py-2.5 px-3.5 text-right">
                        <span className="text-xs text-blue-400 group-hover:text-blue-300 transition-colors inline-flex items-center gap-0.5">
                          Details <ChevronRight className="w-3 h-3" />
                        </span>
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
              onClick={() => fetchEvents(nextCursor, true)}
              disabled={loadingMore}
              className="px-4 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] transition-colors flex items-center gap-2"
            >
              {loadingMore && <RefreshCw className="w-3 h-3 animate-spin" />}
              <span>Load more events</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
