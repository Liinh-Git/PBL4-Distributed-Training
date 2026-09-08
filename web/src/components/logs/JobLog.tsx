import { useState, useMemo } from 'react'
import type { EventListItem, EventSeverity } from '../../domain/types'

interface JobLogProps {
  events: EventListItem[]
  loading?: boolean
}

const SEVERITY_COLORS: Record<EventSeverity, { bg: string; text: string; dot: string }> = {
  INFO: { bg: 'rgba(56, 189, 248, 0.12)', text: '#38BDF8', dot: '#38BDF8' },
  WARNING: { bg: 'rgba(245, 158, 11, 0.12)', text: '#F59E0B', dot: '#F59E0B' },
  ERROR: { bg: 'rgba(239, 68, 68, 0.15)', text: '#EF4444', dot: '#EF4444' },
  CRITICAL: { bg: 'rgba(217, 70, 239, 0.18)', text: '#D946EF', dot: '#D946EF' },
}

export default function JobLog({ events, loading = false }: JobLogProps) {
  const [filterSeverity, setFilterSeverity] = useState<string>('ALL')
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  const filteredEvents = useMemo(() => {
    return events.filter((ev) => {
      if (filterSeverity !== 'ALL' && ev.severity !== filterSeverity) {
        return false
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase()
        const matchType = ev.event_type.toLowerCase().includes(q)
        const matchSource = ev.source_component?.toLowerCase().includes(q) ?? false
        const matchPayload = ev.payload ? JSON.stringify(ev.payload).toLowerCase().includes(q) : false
        return matchType || matchSource || matchPayload
      }
      return true
    })
  }, [events, filterSeverity, searchQuery])

  const toggleExpand = (idx: number) => {
    setExpandedIndex((prev) => (prev === idx ? null : idx))
  }

  return (
    <div className="card" style={{ padding: '1.25rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem',
          marginBottom: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            Attempt Event Logs
          </h3>
          <span
            style={{
              fontSize: '0.75rem',
              color: 'var(--text-muted)',
              background: 'var(--bg-elevated)',
              padding: '0.2rem 0.5rem',
              borderRadius: 'var(--radius-sm)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {filteredEvents.length} {filteredEvents.length === 1 ? 'event' : 'events'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <input
            type="text"
            placeholder="Filter events..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: '0.35rem 0.75rem',
              fontSize: '0.8rem',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              minWidth: '180px',
            }}
          />

          <div style={{ display: 'flex', gap: '0.25rem' }}>
            {['ALL', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((sev) => {
              const active = filterSeverity === sev
              return (
                <button
                  key={sev}
                  type="button"
                  onClick={() => setFilterSeverity(sev)}
                  style={{
                    padding: '0.25rem 0.5rem',
                    fontSize: '0.75rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid',
                    borderColor: active ? 'var(--accent)' : 'var(--border)',
                    background: active ? 'var(--accent-dim)' : 'transparent',
                    color: active ? 'var(--accent)' : 'var(--text-secondary)',
                    fontWeight: active ? 600 : 400,
                  }}
                >
                  {sev}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <div
        style={{
          maxHeight: '400px',
          overflowY: 'auto',
          background: 'var(--bg-app)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8rem',
        }}
      >
        {loading && events.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            Loading events...
          </div>
        ) : filteredEvents.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            {events.length === 0 ? 'No events recorded yet.' : 'No events match your filter.'}
          </div>
        ) : (
          filteredEvents.map((ev, idx) => {
            const colors = SEVERITY_COLORS[ev.severity] ?? SEVERITY_COLORS.INFO
            const isExpanded = expandedIndex === idx
            const hasPayload = ev.payload && Object.keys(ev.payload).length > 0

            return (
              <div
                key={ev.event_id || `${ev.runtime_event_seq ?? idx}-${ev.occurred_at}`}
                style={{
                  borderBottom: '1px solid var(--border)',
                  padding: '0.5rem 0.75rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.25rem',
                  background: idx % 2 === 0 ? 'transparent' : 'rgba(255, 255, 255, 0.01)',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    flexWrap: 'wrap',
                    cursor: hasPayload ? 'pointer' : 'default',
                  }}
                  onClick={() => hasPayload && toggleExpand(idx)}
                >
                  <span style={{ color: 'var(--text-muted)', minWidth: '70px', fontSize: '0.75rem' }}>
                    {ev.occurred_at ? new Date(ev.occurred_at).toLocaleTimeString() : '--:--:--'}
                  </span>

                  {ev.runtime_event_seq !== undefined && (
                    <span
                      style={{
                        color: 'var(--accent-2)',
                        fontWeight: 600,
                        fontSize: '0.75rem',
                        minWidth: '40px',
                      }}
                    >
                      #{ev.runtime_event_seq}
                    </span>
                  )}

                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.35rem',
                      padding: '0.1rem 0.4rem',
                      borderRadius: 'var(--radius-sm)',
                      background: colors.bg,
                      color: colors.text,
                      fontSize: '0.7rem',
                      fontWeight: 600,
                    }}
                  >
                    <span
                      style={{
                        width: '5px',
                        height: '5px',
                        borderRadius: '50%',
                        backgroundColor: colors.dot,
                      }}
                    />
                    {ev.severity}
                  </span>

                  {ev.source_component && (
                    <span
                      style={{
                        color: 'var(--text-muted)',
                        fontSize: '0.75rem',
                        background: 'var(--bg-elevated)',
                        padding: '0.1rem 0.35rem',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      {ev.source_component}
                    </span>
                  )}

                  <span style={{ color: 'var(--text-primary)', fontWeight: 500, flex: 1 }}>
                    {ev.event_type}
                  </span>

                  {hasPayload && (
                    <span
                      style={{
                        color: 'var(--accent)',
                        fontSize: '0.7rem',
                        cursor: 'pointer',
                        userSelect: 'none',
                      }}
                    >
                      {isExpanded ? '▲ Hide details' : '▼ Details'}
                    </span>
                  )}
                </div>

                {isExpanded && hasPayload && (
                  <pre
                    style={{
                      margin: '0.35rem 0 0 0',
                      padding: '0.5rem',
                      background: 'var(--bg-surface)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border)',
                      color: 'var(--text-secondary)',
                      fontSize: '0.75rem',
                      overflowX: 'auto',
                    }}
                  >
                    {JSON.stringify(ev.payload, null, 2)}
                  </pre>
                )}
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
