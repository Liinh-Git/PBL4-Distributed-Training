import { useState, useEffect, useCallback } from 'react';
import { systemApi } from '../api/system';
import type { HealthResponse, CapabilitiesResponse, RuntimeSnapshot } from '../domain/types';

export default function SystemPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [hRes, cRes, sRes] = await Promise.allSettled([
        systemApi.health(),
        systemApi.capabilities(),
        systemApi.runtimeSnapshot(),
      ]);
      if (hRes.status === 'fulfilled') setHealth(hRes.value);
      if (cRes.status === 'fulfilled') setCapabilities(cRes.value);
      if (sRes.status === 'fulfilled') setSnapshot(sRes.value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const statusColor = (status?: string) => {
    if (status === 'healthy' || status === 'connected' || status === 'true') return 'var(--success)';
    if (status === 'degraded') return 'var(--warning)';
    return 'var(--text-muted)';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>System Infrastructure & Status</h1>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 4 }}>
            Subsystem connectivity, protocol capabilities, and authoritative Parameter Server telemetry.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={fetchAll} disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="card" style={{ background: 'var(--error-dim)', borderColor: 'var(--error)', padding: 12 }}>
          <span style={{ color: 'var(--error)', fontWeight: 500 }}>{error}</span>
        </div>
      )}

      {/* Subsystem Health Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">PostgreSQL Database</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: statusColor(health?.postgres),
              }}
            />
            <span style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize' }}>
              {health?.postgres || 'Unknown'}
            </span>
          </div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
            Durable repository for attempts, jobs, commands, and audit events.
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Runtime MCP/1 Gateway</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: statusColor(health?.runtime_mcp),
              }}
            />
            <span style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize' }}>
              {health?.runtime_mcp || 'Disconnected'}
            </span>
          </div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
            Instance: {snapshot?.runtime_instance_id || 'Not connected'}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Dataset Manager</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: statusColor(health?.dataset_manager),
              }}
            />
            <span style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize' }}>
              {health?.dataset_manager || 'Unknown'}
            </span>
          </div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
            Dataset ingestion and partition shard distribution service.
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Management API</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: statusColor(health?.backend),
              }}
            />
            <span style={{ fontSize: 16, fontWeight: 600, textTransform: 'capitalize' }}>
              {health?.backend ?? 'unknown'}
            </span>
          </div>
          <div className="text-muted" style={{ fontSize: 12, marginTop: 8 }}>
            API Version: {capabilities?.api_version || 'v1'}
          </div>
        </div>
      </div>

      {/* Protocol Capabilities Section */}
      {capabilities && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Protocol & System Capabilities</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
            <div>
              <span className="text-muted" style={{ fontSize: 12 }}>Supported DTP Versions:</span>
              <div style={{ fontWeight: 600, marginTop: 4 }}>
                {capabilities.dtp_versions?.join(', ') || '1'}
              </div>
            </div>
            <div>
              <span className="text-muted" style={{ fontSize: 12 }}>Supported MCP Versions:</span>
              <div style={{ fontWeight: 600, marginTop: 4 }}>
                {capabilities.mcp_versions?.join(', ') || '1'}
              </div>
            </div>
            <div>
              <span className="text-muted" style={{ fontSize: 12 }}>Supported Strategies:</span>
              <div style={{ fontWeight: 600, marginTop: 4 }}>
                {capabilities.supported_training_strategies?.length
                  ? capabilities.supported_training_strategies.join(', ')
                  : 'unknown'}
              </div>
            </div>
            <div>
              <span className="text-muted" style={{ fontSize: 12 }}>WebSocket Streaming:</span>
              <div style={{ fontWeight: 600, marginTop: 4, color: 'var(--success)' }}>
                {capabilities.feature_flags?.attempt_websocket_stream ? 'Enabled' : 'Disabled'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Live Runtime Snapshot Section */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Live Parameter Server Snapshot</span>
          {snapshot?.stale && (
            <span className="status-badge status-ABORTED">
              <span className="status-dot" />
              Stale (Offline / Reconnecting)
            </span>
          )}
        </div>
        {!snapshot || !snapshot.runtime_instance_id ? (
          <div className="text-muted" style={{ padding: 20, textAlign: 'center' }}>
            No live Runtime instance currently connected.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14 }}>
              <div>
                <span className="text-muted" style={{ fontSize: 12 }}>Active Attempt:</span>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, marginTop: 4 }}>
                  {snapshot.active_attempt_id || 'None'}
                </div>
              </div>
              <div>
                <span className="text-muted" style={{ fontSize: 12 }}>Attempt State:</span>
                <div style={{ fontWeight: 600, marginTop: 4 }}>
                  {snapshot.attempt_state || 'IDLE'}
                </div>
              </div>
              <div>
                <span className="text-muted" style={{ fontSize: 12 }}>Strategy:</span>
                <div style={{ fontWeight: 600, marginTop: 4 }}>
                  {snapshot.training_strategy || '—'}
                </div>
              </div>
              <div>
                <span className="text-muted" style={{ fontSize: 12 }}>Model Version:</span>
                <div style={{ fontWeight: 600, marginTop: 4 }}>
                  v{snapshot.model_version ?? 0}
                </div>
              </div>
              <div>
                <span className="text-muted" style={{ fontSize: 12 }}>Sequence Cursor:</span>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, marginTop: 4 }}>
                  @{snapshot.runtime_event_seq ?? '—'}
                </div>
              </div>
            </div>

            {snapshot.workers && snapshot.workers.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Connected Workers ({snapshot.workers.length}):</div>
                <table className="table" style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 12 }}>
                      <th style={{ padding: '6px 10px' }}>Worker ID</th>
                      <th style={{ padding: '6px 10px' }}>Session ID</th>
                      <th style={{ padding: '6px 10px' }}>Node Label</th>
                      <th style={{ padding: '6px 10px' }}>State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.workers.map((w) => (
                      <tr key={w.worker_id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '8px 10px', fontWeight: 600 }}>Worker #{w.worker_id}</td>
                        <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                          {w.session_id}
                        </td>
                        <td style={{ padding: '8px 10px' }}>{w.node_label || '—'}</td>
                        <td style={{ padding: '8px 10px' }}>
                          <span className={`status-badge status-${w.state}`}>
                            <span className="status-dot" />
                            {w.state}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
