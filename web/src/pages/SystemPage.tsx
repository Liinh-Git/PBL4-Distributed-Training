import React, { useState, useMemo, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
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
import { HealthData, CapabilitiesData, EventListItemData, WorkerSessionItemData, NodeItemData } from '../types/api';
import { deriveHealthState, mapSubsystemStatus } from '../utils/health';
import { formatDateTime } from '../utils/date';

export const SystemPage: React.FC = () => {
  const { isRuntimeStale, setSelectedWorker } = useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') === 'diagnostics' ? 'diagnostics' : 'overview';

  const [inspectEvent, setInspectEvent] = useState<DiagnosticEvent | null>(null);

  // System API states
  const [healthData, setHealthData] = useState<HealthData | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [capabilitiesData, setCapabilitiesData] = useState<CapabilitiesData | null>(null);
  const [apiEvents, setApiEvents] = useState<EventListItemData[]>([]);
  const [liveWorkers, setLiveWorkers] = useState<WorkerSessionItemData[]>([]);
  const [nodes, setNodes] = useState<NodeItemData[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Diagnostics filters
  const [searchQuery, setSearchQuery] = useState('');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');

  const fetchSystemData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [healthRes, capRes, evRes, attemptRes, nodesRes] = await Promise.allSettled([
        systemService.getHealth(),
        systemService.getCapabilities(),
        eventsService.listEvents({ limit: 50 }),
        attemptsService.listAttempts({ state: 'RUNNING', limit: 1 }),
        systemService.getNodes(),
      ]);
      if (nodesRes.status === 'fulfilled') setNodes(nodesRes.value.data || []);

      if (healthRes.status === 'fulfilled') {
        setHealthData(healthRes.value.data);
        setHealthError(false);
      } else {
        setHealthError(true);
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

  const isHealthy = !healthError && deriveHealthState(healthData, { isRuntimeStale }) === 'healthy';

  // Map dependencies from real Health API fields
  const coreServices = useMemo(() => {
    const lastSeen = healthData?.timestamp ? formatDateTime(healthData.timestamp) : '—';
    const backendStatus = mapSubsystemStatus(healthData?.backend);
    const postgresStatus = mapSubsystemStatus(healthData?.postgres);
    const runtimeStatus = isRuntimeStale ? 'DEGRADED' : mapSubsystemStatus(healthData?.runtime_mcp);
    const dmStatus = mapSubsystemStatus(healthData?.dataset_manager);

    return [
      {
        id: 'backend',
        name: 'Backend API',
        status: backendStatus,
        lastSeen,
        latency: 'Chưa có dữ liệu',
        protocol: 'HTTP REST',
      },
      {
        id: 'runtime',
        name: 'Coordinator Runtime',
        status: runtimeStatus,
        lastSeen,
        latency: 'Chưa có dữ liệu',
        protocol: 'MCP/1',
      },
      {
        id: 'database',
        name: 'Cơ sở dữ liệu PostgreSQL',
        status: postgresStatus,
        lastSeen,
        latency: 'Chưa có dữ liệu',
        protocol: 'PostgreSQL',
      },
      {
        id: 'dataset_mgr',
        name: 'Quản lý tập dữ liệu (Dataset Manager)',
        status: dmStatus,
        lastSeen,
        latency: 'Chưa có dữ liệu',
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
        state: w.state === 'READY' ? 'Hoạt động · Đã đồng bộ' : w.state,
        lastHeartbeat: w.last_heartbeat_at ? formatDateTime(w.last_heartbeat_at) : 'Chưa có dữ liệu',
        internalIp: 'Chưa có dữ liệu',
        protocol: 'dtp/v1.0',
        workerData: {
          workerId: w.worker_id,
          sessionId: w.session_id,
          nodeLabel: w.node_label || `Node ${w.worker_id}`,
          protocolVersion: 'dtp/v1.0',
          connectedAt: w.connected_at || 'Vừa xong',
          state: (w.state as any) || 'READY',
          shardId: w.shard_id,
          localModelVersion: w.local_model_version ? String(w.local_model_version) : undefined,
        } as WorkerSession,
      }));
    }

    return [];
  }, [liveWorkers]);

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
              Hệ thống
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Đang tải dữ liệu...
              </span>
            )}
            {error && (
              <span className="text-[11px] text-rose-400 font-mono">
                ({error})
              </span>
            )}
            {healthError && (
              <span role="alert" className="text-[11px] text-amber-400">
                Không lấy được trạng thái dịch vụ. Nhấn làm mới để thử lại.
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Dịch vụ nền tảng, tình trạng điều phối và kết nối worker
          </p>
        </div>

        {/* Tab switch & Refresh */}
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            onClick={fetchSystemData}
            className="p-1.5 rounded bg-[#121214] border border-white/[0.07] text-[#73737c] hover:text-[#f3f3f4] transition-colors"
            title="Làm mới trạng thái"
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
              Tổng quan
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
              Chẩn đoán
            </button>
          </div>
        </div>
      </div>

      {activeTab === 'overview' ? (
        <div className="space-y-6">
          {/* Node Agents Table */}
          <div className="space-y-2">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Danh sách Node Agent ({nodes.length})
            </h2>

            <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                    <th className="py-2.5 px-3.5 font-medium">Node</th>
                    <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                    <th className="py-2.5 px-3.5 font-medium text-right">Ghi nhận gần nhất</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {nodes.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="py-4 px-3.5 text-center text-[#73737c]">
                        Chưa có Node Agent nào được ghi nhận
                      </td>
                    </tr>
                  ) : (
                    nodes.map(node => {
                      const isOnline = node.state === 'ONLINE';
                      return (
                        <tr key={node.node_id} className="hover:bg-[#171719] transition-colors">
                          <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4]">
                            <div>{node.display_name}</div>
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="inline-flex items-center gap-1.5 text-xs">
                              <span
                                className={`w-1.5 h-1.5 rounded-full ${
                                  isOnline ? 'bg-emerald-400' : 'bg-zinc-500'
                                }`}
                              />
                              <span className={isOnline ? 'text-emerald-400 font-medium' : 'text-[#73737c]'}>
                                {isOnline ? 'Online' : 'Offline'}
                              </span>
                            </span>
                          </td>
                          <td className="py-2.5 px-3.5 text-right text-[#73737c]">
                            {formatDateTime(node.last_seen_at)}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Core Services Table */}
          <div className="space-y-2">
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Dịch vụ Cốt lõi
            </h2>

            <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                    <th className="py-2.5 px-3.5 font-medium">Dịch vụ</th>
                    <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                    <th className="py-2.5 px-3.5 font-medium text-right">Ghi nhận gần nhất</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {coreServices.map(svc => (
                    <tr key={svc.id} className="hover:bg-[#171719] transition-colors">
                      <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4]">
                        {svc.name}
                      </td>
                      <td className="py-2.5 px-3">
                        <SubsystemHealthBadge status={!healthData || healthError ? null : svc.status} />
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
              Kết nối Worker
            </h2>

            <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                    <th className="py-2.5 px-3.5 font-medium">Worker</th>
                    <th className="py-2.5 px-3 font-medium">Node</th>
                    <th className="py-2.5 px-3 font-medium">Trạng thái</th>
                    <th className="py-2.5 px-3.5 font-medium text-right">Thời gian phản hồi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {clusterNodes.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="py-4 px-3.5 text-center text-[#73737c]">
                        Chưa có Worker nào kết nối
                      </td>
                    </tr>
                  ) : (
                    clusterNodes.map(node => (
                      <tr
                        key={node.id}
                        onClick={() => node.workerData && setSelectedWorker(node.workerData)}
                        className={`hover:bg-[#171719] transition-colors group ${
                          node.workerData ? 'cursor-pointer' : ''
                        }`}
                      >
                        <td className="py-2.5 px-3.5 font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                          <div className="flex items-center gap-2">
                            <span
                              className={`w-1.5 h-1.5 rounded-full ${
                                node.state.includes('Hoạt động') ||
                                node.state.includes('Active') ||
                                node.state.includes('READY')
                                  ? 'bg-emerald-400'
                                  : 'bg-zinc-500'
                              }`}
                            />
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
                    ))
                  )}
                </tbody>
              </table>
            </div>
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
                placeholder="Tìm kiếm sự kiện chẩn đoán..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
              />
            </div>

            <div className="flex items-center gap-1.5">
              {[
                { key: 'ALL', label: 'Tất cả' },
                { key: 'INFO', label: 'Thông tin' },
                { key: 'WARN', label: 'Cảnh báo' },
                { key: 'ERROR', label: 'Lỗi' },
              ].map(sev => (
                <button
                  key={sev.key}
                  type="button"
                  onClick={() => setSeverityFilter(sev.key)}
                  className={`px-2.5 py-1 text-xs rounded transition-colors ${
                    severityFilter === sev.key
                      ? 'bg-blue-600 text-white font-medium'
                      : 'bg-[#121214] border border-white/[0.07] text-[#73737c] hover:text-[#f3f3f4]'
                  }`}
                >
                  {sev.label}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
            <div className="divide-y divide-white/[0.05]">
              {filteredEvents.length === 0 ? (
                <div className="p-8 text-center text-xs text-[#73737c]">
                  Không tìm thấy sự kiện chẩn đoán phù hợp.
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
