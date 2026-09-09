import { useState, useEffect, useCallback } from 'react';
import { eventsApi } from '../api/events';
import type { EventListItem, EventSeverity } from '../domain/types';

export default function EventsPage() {
  const [events, setEvents] = useState<EventListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [scopeType, setScopeType] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [eventTypeFilter, setEventTypeFilter] = useState<string>('');
  const [selectedEvent, setSelectedEvent] = useState<EventListItem | null>(null);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await eventsApi.list({
        scope_type: scopeType || undefined,
        severity: severityFilter || undefined,
        event_type: eventTypeFilter || undefined,
        limit: 100,
      });
      setEvents(res.data || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [scopeType, severityFilter, eventTypeFilter]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const severityBadgeClass = (sev: EventSeverity) => {
    switch (sev) {
      case 'CRITICAL':
      case 'ERROR':
        return 'status-FAILED';
      case 'WARNING':
        return 'status-ABORTED';
      default:
        return 'status-READY';
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Management Audit Events</h1>
          <p className="text-secondary" style={{ fontSize: 13, marginTop: 4 }}>
            Authoritative audit trail of runtime lifecycle transitions, step commits, and control actions.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={fetchEvents} disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="card" style={{ background: 'var(--error-dim)', borderColor: 'var(--error)', padding: 12 }}>
          <span style={{ color: 'var(--error)', fontWeight: 500 }}>{error}</span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="card" style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Scope Type:</span>
          <select className="form-select" style={{ width: 140 }} value={scopeType} onChange={(e) => setScopeType(e.target.value)}>
            <option value="">All Scopes</option>
            <option value="ATTEMPT">ATTEMPT</option>
            <option value="SYSTEM">SYSTEM</option>
            <option value="DATASET_BUILD">DATASET_BUILD</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Severity:</span>
          <select className="form-select" style={{ width: 140 }} value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
            <option value="">All Severities</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Event Type:</span>
          <input
            className="form-input"
            style={{ width: 180 }}
            placeholder="e.g. STEP_COMMITTED"
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
          />
        </div>

        {(scopeType || severityFilter || eventTypeFilter) && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setScopeType('');
              setSeverityFilter('');
              setEventTypeFilter('');
            }}
          >
            Reset
          </button>
        )}
      </div>

      {/* Events Table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Events ({events.length})</span>
        </div>
        {events.length === 0 ? (
          <div className="text-muted" style={{ padding: 24, textAlign: 'center' }}>
            No audit events found.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="table" style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: 12 }}>
                  <th style={{ padding: '8px 12px' }}>Event ID</th>
                  <th style={{ padding: '8px 12px' }}>Severity</th>
                  <th style={{ padding: '8px 12px' }}>Event Type</th>
                  <th style={{ padding: '8px 12px' }}>Scope</th>
                  <th style={{ padding: '8px 12px' }}>Seq</th>
                  <th style={{ padding: '8px 12px' }}>Occurred At</th>
                  <th style={{ padding: '8px 12px' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.event_id || `${ev.attempt_id}-${ev.runtime_event_seq}`} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {ev.event_id || '—'}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span className={`status-badge ${severityBadgeClass(ev.severity)}`}>
                        <span className="status-dot" />
                        {ev.severity}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px', fontWeight: 600 }}>{ev.event_type}</td>
                    <td style={{ padding: '10px 12px' }}>
                      {ev.scope?.type ? `${ev.scope.type}:${ev.scope.id || ''}` : ev.attempt_id || 'SYSTEM'}
                    </td>
                    <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {ev.runtime_event_seq ?? '—'}
                    </td>
                    <td style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
                      {new Date(ev.occurred_at).toLocaleTimeString()}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => setSelectedEvent(ev)}>
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Event Details Modal */}
      {selectedEvent && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 200,
          }}
        >
          <div className="card" style={{ width: 560, padding: 24, maxHeight: '85vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ fontSize: 16, fontWeight: 700 }}>Event Payload</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelectedEvent(null)}>
                ✕
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, marginBottom: 16 }}>
              <div>
                <span className="text-muted">Event Type: </span>
                <span style={{ fontWeight: 600 }}>{selectedEvent.event_type}</span>
              </div>
              <div>
                <span className="text-muted">Occurred At: </span>
                <span>{new Date(selectedEvent.occurred_at).toISOString()}</span>
              </div>
            </div>
            <pre
              style={{
                background: 'var(--bg-elevated)',
                padding: 14,
                borderRadius: 'var(--radius)',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                overflowX: 'auto',
                color: 'var(--text-primary)',
              }}
            >
              {JSON.stringify(selectedEvent.payload || selectedEvent, null, 2)}
            </pre>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={() => setSelectedEvent(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
