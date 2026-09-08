import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useRealtimeAttempt } from '../hooks/useRealtimeAttempt'
import { attemptsApi } from '../api/attempts'
import StatusBadge from '../components/jobs/StatusBadge'
import TopologyGraph from '../components/topology/TopologyGraph'
import MetricCard from '../components/metrics/MetricCard'
import { TrainingChart, WorkerComparisonChart } from '../components/metrics/TrainingChart'
import JobLog from '../components/logs/JobLog'
import type { StepListItem } from '../domain/types'

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// ─── WS status indicator ────────────────────────────────────────────────────
function WsStatusBadge({ status }: { status: string }) {
  return (
    <span className={`ws-status ws-${status}`} aria-label={`WebSocket: ${status}`}>
      <span className="ws-status-dot" aria-hidden="true" />
      {status === 'connected' ? 'Live' : status === 'connecting' ? 'Connecting…' : 'Disconnected'}
    </span>
  )
}

// ─── Abort confirm ──────────────────────────────────────────────────────────
function AbortModal({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="abort-title">
      <div className="modal">
        <div className="modal-title" id="abort-title">Abort Attempt?</div>
        <div className="modal-body">
          This will send an ABORT command to the runtime. The attempt will transition to ABORTED after the runtime acknowledges.
        </div>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-danger" onClick={onConfirm} autoFocus>Abort</button>
        </div>
      </div>
    </div>
  )
}

// ─── Attempt selector ───────────────────────────────────────────────────────
function AttemptSelector({ onSelect }: { onSelect: (id: string) => void }) {
  const [attemptId, setAttemptId] = useState('')
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 500 }}>
      <div className="section-title">Monitor an Attempt</div>
      <div className="text-secondary" style={{ fontSize: 13 }}>
        Enter an attempt ID to connect and monitor training in real time.
      </div>
      <div className="flex gap-8">
        <input
          className="form-input"
          value={attemptId}
          onChange={e => setAttemptId(e.target.value)}
          placeholder="attempt_..."
          aria-label="Attempt ID"
          style={{ flex: 1 }}
        />
        <button
          className="btn btn-primary"
          onClick={() => attemptId.trim() && onSelect(attemptId.trim())}
          disabled={!attemptId.trim()}
        >
          Connect
        </button>
      </div>
    </div>
  )
}

// ─── Build chart data from steps ────────────────────────────────────────────
function buildStepChartData(steps: StepListItem[]) {
  return steps.map(s => ({
    step: s.step_id,
    model_version: s.output_model_version ?? s.input_model_version,
    samples: s.total_sample_count ?? 0,
  }))
}

// ─── Current Job Page ────────────────────────────────────────────────────────
export default function CurrentJobPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [activeAttemptId, setActiveAttemptId] = useState<string | null>(
    (location.state as { attemptId?: string } | null)?.attemptId ?? null
  )
  const [showAbort, setShowAbort] = useState(false)
  const [abortError, setAbortError] = useState<string | null>(null)
  const [checkpointBusy, setCheckpointBusy] = useState(false)
  const [checkpointMsg, setCheckpointMsg] = useState<string | null>(null)

  const { attempt, snapshot, workers, steps, events, wsStatus, loading, error, refresh } =
    useRealtimeAttempt(activeAttemptId)

  // Auto-detect latest running attempt if none selected
  useEffect(() => {
    if (activeAttemptId) return
    let cancelled = false
    async function detect() {
      for (const state of ['RUNNING', 'INITIALIZING', 'WAITING_WORKERS', 'PROVISIONING']) {
        try {
          const r = await attemptsApi.list({ state, limit: 1 })
          if (!cancelled && r.data[0]) { setActiveAttemptId(r.data[0].attempt_id); return }
        } catch { /* ignore */ }
      }
    }
    detect()
    return () => { cancelled = true }
  }, [activeAttemptId])

  async function handleAbort() {
    if (!activeAttemptId) return
    setAbortError(null)
    try { await attemptsApi.abort(activeAttemptId, 'Operator abort'); refresh(); setShowAbort(false) }
    catch (e) { setAbortError(errMsg(e)) }
  }

  async function handleCheckpoint() {
    if (!activeAttemptId) return
    setCheckpointBusy(true); setCheckpointMsg(null)
    try {
      await attemptsApi.requestCheckpoint(activeAttemptId, 'Manual request')
      setCheckpointMsg('Checkpoint request sent')
    } catch (e) {
      setCheckpointMsg(errMsg(e))
    } finally {
      setCheckpointBusy(false)
      setTimeout(() => setCheckpointMsg(null), 4000)
    }
  }

  const isActive = attempt?.state === 'RUNNING' || attempt?.state === 'INITIALIZING'
    || attempt?.state === 'WAITING_WORKERS' || attempt?.state === 'PROVISIONING'

  const chartData = buildStepChartData(steps)
  const workerBarData = workers.map(w => ({
    name: w.node_label || `W${w.worker_id}`,
    value: 1,
  }))

  // ── No attempt selected yet ─────────────────────────────────────────────
  if (!activeAttemptId) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <h1 className="page-title">Current Job</h1>
        <AttemptSelector onSelect={setActiveAttemptId} />
        <div className="empty-state">
          <div className="empty-state-icon">◎</div>
          <div className="empty-state-title">No active training attempt</div>
          <div className="empty-state-desc">
            Start a job from{' '}
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/')}>Home</button>
            {' '}or{' '}
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/jobs')}>Job Management</button>
            , then return here to monitor training in real time.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {showAbort && <AbortModal onConfirm={handleAbort} onCancel={() => setShowAbort(false)} />}

      {/* Page header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 className="page-title">Current Job</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            {attempt && <StatusBadge state={attempt.state} />}
            <WsStatusBadge status={wsStatus} />
            <span className="text-muted" style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>
              {activeAttemptId}
            </span>
          </div>
        </div>
        <div className="flex gap-8" style={{ flexWrap: 'wrap' }}>
          {isActive && (
            <>
              <button className="btn btn-secondary btn-sm" onClick={handleCheckpoint} disabled={checkpointBusy} aria-label="Request checkpoint">
                ⊙ Checkpoint
              </button>
              <button className="btn btn-danger btn-sm" onClick={() => setShowAbort(true)} aria-label="Abort training">
                ■ Stop
              </button>
            </>
          )}
          <button className="btn btn-ghost btn-sm" onClick={() => setActiveAttemptId(null)}>
            Change Attempt
          </button>
          <button className="btn btn-ghost btn-sm" onClick={refresh} aria-label="Refresh data">↻</button>
        </div>
      </div>

      {checkpointMsg && (
        <div style={{ background: 'var(--info-dim)', border: '1px solid var(--info)', borderRadius: 6, padding: '8px 14px', fontSize: 13, color: 'var(--info)' }}>
          {checkpointMsg}
        </div>
      )}
      {abortError && <div className="text-error" style={{ fontSize: 13 }}>{abortError}</div>}

      {/* Loading skeletons */}
      {loading && (
        <div className="grid-4">
          {[1, 2, 3, 4].map(i => <div key={i} className="skeleton" style={{ height: 72 }} />)}
        </div>
      )}

      {/* Error state */}
      {error && (
        <div className="card error-state">
          <div>Failed to load attempt data</div>
          <div style={{ fontSize: 12 }}>{error}</div>
          <button className="btn btn-secondary btn-sm" onClick={refresh}>Retry</button>
        </div>
      )}

      {/* Metric Cards */}
      {attempt && (
        <div className="grid-4">
          <MetricCard
            label="Workers"
            value={`${attempt.membership.active_workers}/${attempt.membership.expected_workers}`}
            sub="active / expected"
          />
          <MetricCard
            label="Completed Steps"
            value={steps.length > 0 ? steps[steps.length - 1].step_id : '—'}
          />
          <MetricCard
            label="Current Epoch"
            value={snapshot?.epoch ?? '—'}
          />
          <MetricCard
            label="Model Version"
            value={snapshot?.model_version ?? '—'}
          />
        </div>
      )}

      {/* Main 2-col: Topology + Workers table */}
      <div className="grid-2">
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="card-header">
            <span className="section-title">Distributed Topology</span>
            {attempt && <span className="text-muted" style={{ fontSize: 11 }}>{workers.length} workers</span>}
          </div>
          <TopologyGraph workers={workers} attemptState={attempt?.state} />
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="card-title">Workers</div>
          {workers.length === 0 ? (
            <div className="empty-state" style={{ padding: '24px 0' }}>
              <div className="empty-state-title">No workers connected</div>
            </div>
          ) : (
            <div className="table-container">
              <table className="table">
                <thead><tr><th>ID</th><th>Label</th><th>State</th><th>Connected</th></tr></thead>
                <tbody>
                  {workers.map(w => (
                    <tr key={w.session_id}>
                      <td className="text-mono" style={{ fontSize: 11 }}>{w.worker_id}</td>
                      <td>{w.node_label}</td>
                      <td><StatusBadge state={w.state} size="sm" /></td>
                      <td className="text-muted" style={{ fontSize: 11 }}>
                        {new Date(w.connected_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Charts */}
      <div className="grid-2">
        <TrainingChart
          title="Model Version Progress"
          data={chartData}
          xKey="step"
          yKey="model_version"
          unit="version"
        />
        <WorkerComparisonChart
          title="Worker Distribution"
          data={workerBarData}
          unit="workers"
        />
      </div>

      {/* Steps table */}
      {steps.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="section-title">Training Steps</span>
            <span className="text-muted" style={{ fontSize: 11 }}>{steps.length} steps</span>
          </div>
          {attempt && attempt.state !== 'COMPLETED' && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                <span>Step {steps[steps.length - 1].step_id}</span>
                <span>Epoch {steps[steps.length - 1].epoch}</span>
              </div>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${Math.min(100, (steps.length / Math.max(steps.length, 10)) * 100)}%` }} />
              </div>
            </div>
          )}
          <div className="table-container">
            <table className="table">
              <thead>
                <tr><th>Step</th><th>State</th><th>Epoch</th><th>Batch</th><th>Samples</th><th>Committed</th></tr>
              </thead>
              <tbody>
                {steps.slice(-20).reverse().map(s => (
                  <tr key={s.step_id}>
                    <td className="text-accent" style={{ fontWeight: 600 }}>{s.step_id}</td>
                    <td><StatusBadge state={s.state} size="sm" /></td>
                    <td>{s.epoch}</td>
                    <td>{s.batch_ordinal}</td>
                    <td>{s.total_sample_count ?? '—'}</td>
                    <td className="text-muted" style={{ fontSize: 11 }}>
                      {s.committed_at ? new Date(s.committed_at).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Event Log */}
      <div className="card">
        <JobLog events={events} />
      </div>
    </div>
  )
}
