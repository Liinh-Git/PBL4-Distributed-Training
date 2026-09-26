import React, { useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ChevronDown,
  ChevronRight,
  Search,
  CheckCircle2,
  AlertTriangle,
  AlertOctagon,
  Radio,
  RefreshCw,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { SubsystemHealthBadge, SeverityBadge } from '../components/common/Badge';
import { formatDiagnosticEvent, EventIconType } from '../utils/eventFormatter';
import { EventDetailDrawer } from '../components/drawers/EventDetailDrawer';
import { DiagnosticEvent, WorkerSession } from '../types';
import { systemService, eventsService, attemptsService, workersService } from '../api';
import { HealthData, CapabilitiesData, EventListItemData, WorkerSessionItemData } from '../types/api';
import { deriveHealthState, mapSubsystemStatus } from '../utils/health';
import { config } from '../config';

export const SystemPage: React.FC = () => {
  const { isRuntimeStale, setSelectedWorker } = useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') === 'diagnostics' ? 'diagnostics' : 'overview';

  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [inspectEvent, setInspectEvent] = useState<DiagnosticEvent | null>(null);

  // System API states
  const [healthData, setHealthData] = useState<HealthData | null>(null);
  const [capabilitiesData, setCapabilitiesData] = useState<CapabilitiesData | null>(null);
  const [apiEvents, setApiEvents] = useState<EventListItemData[]>([]);
  const [liveWorkers, setLiveWorkers] = useState<WorkerSessionItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Diagnostics filters
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');

  const fetchSystemData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [healthRes, capRes, evRes, attemptRes] = await Promise.allSettled([
        systemService.getHealth(),
        systemService.getCapabilities(),
        eventsService.listEvents({ limit: 50 }),
        attemptsService.listAttempts({ state: 'RUNNING', limit: 1 }),
      ]);

      if (healthRes.status === 'fulfilled') {
        setHealthData(healthRes.value.data);
      }
      if (capRes.status === 'fulfilled') {
        setCapabilitiesData(capRes.value.data);
      }
      if (evRes.status === 'fulfilled') {
        setApiEvents(evRes.value.data || []);
      }
      if (attemptRes.status === 'fulfilled' && attemptRes.value.data && attemptRes.value.data.length > 0) {
        const activeAttemptId = attemptRes.value.data[0].attempt_id;
        try {
          const wRes = await workersService.listWorkers(activeAttemptId);
          setLiveWorkers(wRes.data || []);
        } catch {
          setLiveWorkers([]);
        }
      } else {
        setLiveWorkers([]);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load system data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSystemData();
  }, []);

  const isHealthy = deriveHealthState(healthData, { isRuntimeStale }) === 'healthy';

  // Map dependencies from real Health API fields
  const coreServices = useMemo(() => {
    const backendStatus = mapSubsystemStatus(healthData?.backend);
    const postgresStatus = mapSubsystemStatus(healthData?.postgres);
    const runtimeStatus = isRuntimeStale ? 'DEGRADED' : mapSubsystemStatus(healthData?.runtime_mcp);
    const dmStatus = mapSubsystemStatus(healthData?.dataset_manager);

    return [
      {
        id: 'backend',
        name: 'Backend API',
        status: backendStatus,
        lastSeen: 'now',
        latency: '< 2 ms',
        protocol: 'HTTP/2 REST',
      },
      {
        id: 'runtime',
        name: 'Coordinator Runtime',
        status: runtimeStatus,
        lastSeen: isRuntimeStale ? 'Stale' : 'now',
        latency: '< 3 ms',
        protocol: 'WebSocket v1.2 / DTP/1',
      },
      {
        id: 'database',
        name: 'PostgreSQL Database',
        status: postgresStatus,
        lastSeen: 'now',
        latency: '< 1 ms',
        protocol: 'PostgreSQL 16',
      },
      {
        id: 'dataset_mgr',
        name: 'Dataset Manager',
        status: dmStatus,
        lastSeen: 'now',
        latency: '< 4 ms',
        protocol: 'HTTP Service',
      },
    ];
  }, [healthData, isRuntimeStale]);

  const clusterNodes = useMemo(() => {
    if (liveWorkers.length > 0) {
      return liveWorkers.map(w => ({
        id: `node-${w.worker_id}`,
        nodeLabel: w.node_label || `Compute Node 0${w.worker_id + 1}`,
        workerLabel: `Worker ${w.worker_id}`,
        state: w.state === 'READY' ? 'Active · Synchronized' : w.state,
        lastHeartbeat: w.last_heartbeat_at ? new Date(w.last_heartbeat_at).toLocaleTimeString() : 'connected',
        internalIp: `10.240.0.1${w.worker_id + 1}`,
        protocol: 'dtp/v1.0',
        workerData: {
          workerId: w.worker_id,
          sessionId: w.session_id,
          nodeLabel: w.node_label || `Node ${w.worker_id}`,
          protocolVersion: 'dtp/v1.0',
          connectedAt: w.connected_at || 'now',
          state: (w.state as any) || 'READY',
          shardId: w.shard_id,
          localModelVersion: w.local_model_version ? String(w.local_model_version) : undefined,
        } as WorkerSession,
      }));
    }

    return [
      {
        id: 'node-01',
        nodeLabel: 'Compute Node 01',
        workerLabel: 'Worker 0',
        state: isHealthy ? 'Standby · Operational' : 'Offline',
        lastHeartbeat: isHealthy ? 'heartbeat ok' : 'unreachable',
        internalIp: '10.240.0.11',
        protocol: 'dtp/v1.0',
        workerData: null,
      },
      {
        id: 'node-02',
        nodeLabel: 'Compute Node 02',
        workerLabel: 'Worker 1',
        state: isHealthy ? 'Standby · Operational' : 'Offline',
        lastHeartbeat: isHealthy ? 'heartbeat ok' : 'unreachable',
        internalIp: '10.240.0.12',
        protocol: 'dtp/v1.0',
        workerData: null,
      },
      {
        id: 'node-03',
        nodeLabel: 'Compute Node 03',
        workerLabel: 'Worker 2',
        state: isHealthy ? 'Standby · Operational' : 'Offline',
        lastHeartbeat: isHealthy ? 'heartbeat ok' : 'unreachable',
        internalIp: '10.240.0.13',
        protocol: 'dtp/v1.0',
        workerData: null,
      },
    ];
  }, [liveWorkers, isHealthy]);

  // Convert AuditEventResponse to DiagnosticEvent format for UI
  const displayEvents: DiagnosticEvent[] = useMemo(() => {
    if (apiEvents.length > 0) {
      return apiEvents.map(evt => ({
        id: evt.event_id,
        time: evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : 'now',
        scope: (evt.scope_type || 'SYSTEM').toLowerCase() as any,
        event: evt.event_type,
        severity: (evt.severity?.toUpperCase() || 'INFO') as any,
        actor: evt.scope_id || 'system',
        payloadSummary: evt.payload ? JSON.stringify(evt.payload) : undefined,
        humanText: evt.event_type.replace(/_/g, ' '),
      }));
    }
    return [];
  }, [apiEvents]);

  const filteredEvents = useMemo(() => {
    return displayEvents.filter(evt => {
      const formatted = formatDiagnosticEvent(evt);
      const matchesSearch =
        evt.event.toLowerCase().includes(searchQuery.toLowerCase()) ||
        evt.scope.toLowerCase().includes(searchQuery.toLowerCase()) ||
        formatted.humanText.toLowerCase().includes(searchQuery.toLowerCase());

      const matchesSeverity =
        severityFilter === 'ALL' || evt.severity === severityFilter;

      return matchesSearch && matchesSeverity;
    });
  }, [displayEvents, searchQuery, severityFilter]);

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
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              System
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Fetching API...
              </span>
            )}
            {error && (
              <span className="text-[11px] text-rose-400 font-mono">
                ({error})
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Platform services, coordinator health, and worker connectivity
          </p>
        </div>

        {/* Tab switch & Refresh */}
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={fetchSystemData}
            className="p-1.5 rounded bg-[#121214] border border-white/[0.07] text-[#73737c] hover:text-[#f3f3f4] transition-colors"
            title="Refresh system state"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <div className="flex items-center gap-1 bg-[#121214] p-0.5 rounded border border-white/[0.07] text-xs">
            <button
              type="button"
              onClick={() => setSearchParams({})}
              className={`px-3 py-1 rounded transition-colors ${
                activeTab === 'overview'
                  ? 'bg-[#171719] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#f3f3f4]'
              }`}
            >
              Overview
            </button>
            <button
              type="button"
              onClick={() => setSearchParams({ tab: 'diagnostics' })}
              className={`px-3 py-1 rounded transition-colors ${
                activeTab === 'diagnostics'
                  ? 'bg-[#171719] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#f3f3f4]'
              }`}
            >
              Diagnostics
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'overview' ? (
        <div className="space-y-6">
          {/* Core Services Table */}
          <div className="space-y-2">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Core Services
            </h2>

            <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                    <th className="py-2.5 px-3.5 font-medium">Service</th>
                    <th className="py-2.5 px-3 font-medium">Status</th>
                    <th className="py-2.5 px-3.5 font-medium text-right">Last seen</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {coreServices.map(svc => (
                    <tr key={svc.id} className="hover:bg-[#171719] transition-colors">
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4]">
                        {svc.name}
                      </td>
                      <td className="py-2.5 px-3">
                        <SubsystemHealthBadge status={svc.status} />
                      </td>
                      <td className="py-2.5 px-3.5 text-right text-[#a1a1a8]">
                        {svc.lastSeen}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Worker Connectivity Table */}
          <div className="space-y-2">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Worker Connectivity
            </h2>

            <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                    <th className="py-2.5 px-3.5 font-medium">Worker</th>
                    <th className="py-2.5 px-3 font-medium">Node</th>
                    <th className="py-2.5 px-3 font-medium">Status</th>
                    <th className="py-2.5 px-3.5 font-medium text-right">Heartbeat</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {clusterNodes.map(node => (
                    <tr
                      key={node.id}
                      onClick={() => node.workerData && setSelectedWorker(node.workerData)}
                      className={`hover:bg-[#171719] transition-colors group ${
                        node.workerData ? 'cursor-pointer' : ''
                      }`}
                    >
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                        <div className="flex items-center gap-2">
                          <span className={`w-1.5 h-1.5 rounded-full ${node.state.includes('Active') || node.state.includes('Operational') ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
                          <span>{node.workerLabel}</span>
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {node.nodeLabel}
                      </td>
                      <td className="py-2.5 px-3 text-[#f3f3f4]">
                        {node.state}
                      </td>
                      <td className="py-2.5 px-3.5 text-right text-[#73737c]">
                        {node.lastHeartbeat}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Collapsed Technical details */}
          <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
            <button
              type="button"
              onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
              className="w-full p-3 flex items-center justify-between text-left hover:bg-white/[0.02] transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2 text-xs">
                <ChevronDown
                  className={`w-3.5 h-3.5 text-[#73737c] transition-transform ${
                    showTechnicalDetails ? 'rotate-180' : ''
                  }`}
                />
                <span className="font-semibold text-[#f3f3f4]">Technical details</span>
              </div>
              <span className="text-xs text-[#73737c]">
                {showTechnicalDetails ? 'Hide' : 'Expand'}
              </span>
            </button>

            {showTechnicalDetails && (
              <div className="p-3 pt-0 space-y-3 text-xs border-t border-white/[0.04]">
                <div className="pt-3 overflow-x-auto">
                  <table className="w-full text-left text-xs font-mono">
                    <thead>
                      <tr className="border-b border-white/[0.07] text-[#73737c] text-[11px]">
                        <th className="py-2 px-3 font-medium">Service / Node</th>
                        <th className="py-2 px-3 font-medium">Internal IP</th>
                        <th className="py-2 px-3 font-medium">Protocol</th>
                        <th className="py-2 px-3 font-medium text-right">Latency</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04] text-[#a1a1a8]">
                      {coreServices.map(svc => (
                        <tr key={svc.id}>
                          <td className="py-2 px-3 text-[#f3f3f4]">{svc.name}</td>
                          <td className="py-2 px-3">10.240.0.1</td>
                          <td className="py-2 px-3">{svc.protocol}</td>
                          <td className="py-2 px-3 text-right">{svc.latency}</td>
                        </tr>
                      ))}
                      {clusterNodes.map(node => (
                        <tr key={node.id}>
                          <td className="py-2 px-3 text-[#f3f3f4]">{node.workerLabel} ({node.id})</td>
                          <td className="py-2 px-3">{node.internalIp}</td>
                          <td className="py-2 px-3">{node.protocol}</td>
                          <td className="py-2 px-3 text-right">&lt; 1 ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="p-2.5 rounded bg-[#171719] border border-white/[0.04] text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[#73737c]">Supported Strategies</span>
                    <span className="font-mono text-[#a1a1a8]">
                      {capabilitiesData?.supported_training_strategies?.join(', ') || 'strict_bsp'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#73737c]">Barrier Algorithm</span>
                    <span className="text-[#a1a1a8]">Deterministic Strict BSP v1.0</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#73737c]">Transport Socket</span>
                    <span className="font-mono text-[#a1a1a8]">
                      {config.wsBaseUrl ? `${config.wsBaseUrl}/ws/v1/attempts` : '/ws/v1/attempts'}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Diagnostics Tab: Event Stream */
        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
            <div className="relative flex-1">
              <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
              <input
                type="text"
                placeholder="Search diagnostic events..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
              />
            </div>

            <div className="flex items-center gap-1.5">
              {['ALL', 'INFO', 'WARN', 'ERROR'].map(sev => (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setSeverityFilter(sev)}
                  className={`px-2.5 py-1 text-xs rounded transition-colors ${
                    severityFilter === sev
                      ? 'bg-blue-600 text-white font-medium'
                      : 'bg-[#121214] border border-white/[0.07] text-[#73737c] hover:text-[#f3f3f4]'
                  }`}
                >
                  {sev}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
            <div className="divide-y divide-white/[0.05]">
              {filteredEvents.length === 0 ? (
                <div className="p-8 text-center text-xs text-[#73737c]">
                  No matching diagnostic events.
                </div>
              ) : (
                filteredEvents.map((evt, idx) => {
                  const formatted = formatDiagnosticEvent(evt);
                  const displayTime =
                    evt.time && evt.time.length > 8 ? evt.time.slice(0, 8) : evt.time;

                  return (
                    <div
                      key={`${evt.id}-${evt.runtimeSeq ?? idx}`}
                      onClick={() => setInspectEvent(evt)}
                      className="p-3 flex items-center justify-between text-xs hover:bg-white/[0.02] cursor-pointer transition-colors"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        {renderStatusIcon(formatted.iconType)}
                        <span className="text-[#f3f3f4] truncate">
                          {formatted.humanText}
                        </span>
                      </div>

                      <div className="flex items-center gap-3 shrink-0 text-[#73737c]">
                        <SeverityBadge severity={evt.severity} />
                        <span>{displayTime}</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Event Details Drawer */}
      <EventDetailDrawer
        event={inspectEvent}
        onClose={() => setInspectEvent(null)}
      />
    </div>
  );
};
