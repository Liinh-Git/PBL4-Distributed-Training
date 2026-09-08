import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useJobList, useJobDetail } from '../hooks/useJobs'
import { attemptsApi } from '../api/attempts'
import { jobsApi } from '../api/jobs'
import StatusBadge from '../components/jobs/StatusBadge'
import JobLog from '../components/logs/JobLog'
import type { JobDetail, AttemptListItem, EventListItem } from '../domain/types'

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// ─── Confirm Modal ──────────────────────────────────────────────────────────
function ConfirmModal({ title, body, onConfirm, onCancel, danger }: {
  title: string; body: string; onConfirm: () => void; onCancel: () => void; danger?: boolean
}) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal">
        <div className="modal-title" id="modal-title">{title}</div>
        <div className="modal-body">{body}</div>
        <div className="modal-actions">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} autoFocus>Confirm</button>
        </div>
      </div>
    </div>
  )
}

// ─── Job Actions ────────────────────────────────────────────────────────────
function JobActions({ job, onRefresh }: { job: JobDetail; onRefresh: () => void }) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<null | { action: string; label: string; danger?: boolean }>(null)

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await action(); onRefresh() }
    catch (e) { setError(errMsg(e)) }
    finally { setBusy(false); setConfirm(null) }
  }

  const latestAttempt = job.attempt_summary.latest_attempt_id
  const latestState = job.attempt_summary.latest_attempt_state
  const isRunning = latestState === 'RUNNING' || latestState === 'INITIALIZING'
    || latestState === 'PROVISIONING' || latestState === 'WAITING_WORKERS'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {error && <div className="text-error" style={{ fontSize: 12 }}>{error}</div>}
      <div className="flex gap-8" style={{ flexWrap: 'wrap' }}>
        {job.state === 'DRAFT' && (
          <button className="btn btn-secondary btn-sm" disabled={busy}
            onClick={() => run(() => jobsApi.freeze(job.job_id))}>
            Freeze to Ready
          </button>
        )}
        {job.state === 'READY' && !isRunning && (
          <>
            <button className="btn btn-primary btn-sm" disabled={busy}
              onClick={() => run(async () => { await jobsApi.start(job.job_id); navigate('/current-job') })}>
              ▶ Start
            </button>
            {(latestState === 'FAILED' || latestState === 'ABORTED') && (
              <button className="btn btn-secondary btn-sm" disabled={busy}
                onClick={() => run(() => jobsApi.retry(job.job_id))}>
                ↺ Retry
              </button>
            )}
          </>
        )}
        {isRunning && latestAttempt && (
          <button className="btn btn-danger btn-sm" disabled={busy}
            onClick={() => setConfirm({ action: 'abort', label: 'Abort attempt', danger: true })}>
            ■ Abort
          </button>
        )}
        <button className="btn btn-secondary btn-sm" disabled={busy}
          onClick={() => run(() => jobsApi.clone(job.job_id))}>
          ⎘ Clone
        </button>
        {job.state !== 'ARCHIVED' && (
          <button className="btn btn-ghost btn-sm" disabled={busy}
            onClick={() => setConfirm({ action: 'archive', label: 'Archive this job?' })}>
            Archive
          </button>
        )}
      </div>
      {confirm && (
        <ConfirmModal
          title={confirm.label}
          body="This action cannot be undone. Are you sure?"
          danger={confirm.danger}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            if (confirm.action === 'archive') run(() => jobsApi.archive(job.job_id))
            if (confirm.action === 'abort' && latestAttempt) {
              run(() => attemptsApi.abort(latestAttempt, 'Operator abort'))
            }
          }}
        />
      )}
    </div>
  )
}

// ─── Job Detail Panel ───────────────────────────────────────────────────────
function JobDetailPanel({ jobId }: { jobId: string }) {
  const { job, loading, error, refresh } = useJobDetail(jobId)
  const [events, setEvents] = useState<EventListItem[]>([])
  const [attempts, setAttempts] = useState<AttemptListItem[]>([])
  const [loadingExtra, setLoadingExtra] = useState(false)
  const navigate = useNavigate()

  const loadExtra = useCallback(async (aid: string) => {
    setLoadingExtra(true)
    try {
      const [ev, at] = await Promise.allSettled([
        attemptsApi.events(aid, { limit: 100 }),
        attemptsApi.list({ job_id: jobId, limit: 20 }),
      ])
      if (ev.status === 'fulfilled') setEvents(ev.value.data)
      if (at.status === 'fulfilled') setAttempts(at.value.data)
    } finally { setLoadingExtra(false) }
  }, [jobId])

  // Load extras when job detail arrives
  const latestAid = job?.attempt_summary.latest_attempt_id
  useState(() => { if (latestAid) loadExtra(latestAid) })

  if (loading) return <div className="card"><div className="skeleton" style={{ height: 120 }} /></div>
  if (error) return (
    <div className="card error-state">
      <div>Failed to load</div>
      <div style={{ fontSize: 12 }}>{error}</div>
      <button className="btn btn-secondary btn-sm" onClick={refresh}>Retry</button>
    </div>
  )
  if (!job) return null

  const rc = job.requested_contract

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="card">
        <div className="card-header">
          <div>
            <div className="section-title">{job.display_name}</div>
            <div className="text-muted" style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>{job.job_id}</div>
          </div>
          <StatusBadge state={job.attempt_summary.latest_attempt_state ?? job.state} />
        </div>
        {job.description && <div className="text-secondary" style={{ fontSize: 13, marginBottom: 12 }}>{job.description}</div>}
        <div className="grid-4" style={{ gap: 12 }}>
          <Info label="State" value={job.state} />
          <Info label="Attempts" value={job.attempt_summary.total} />
          <Info label="Strategy" value={rc?.training_strategy ?? '—'} />
          <Info label="Epochs" value={rc?.epochs ?? '—'} />
          <Info label="Build ID" value={rc?.dataset_build_id ?? '—'} mono />
          <Info label="Model" value={rc?.model_id ?? '—'} mono />
          <Info label="LR" value={rc?.learning_rate ?? '—'} />
          <Info label="Created" value={new Date(job.created_at).toLocaleDateString()} />
        </div>
      </div>

      <div className="card">
        <div className="card-title" style={{ marginBottom: 12 }}>Actions</div>
        <JobActions job={job} onRefresh={refresh} />
      </div>

      {attempts.length > 0 && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 12 }}>Attempts ({attempts.length})</div>
          <div className="table-container">
            <table className="table">
              <thead><tr><th>Attempt ID</th><th>Mode</th><th>State</th><th>Started</th><th>Ended</th></tr></thead>
              <tbody>
                {attempts.map(a => (
                  <tr key={a.attempt_id}
                    onClick={() => navigate('/current-job', { state: { attemptId: a.attempt_id } })}
                    style={{ cursor: 'pointer' }}
                    aria-label={`View attempt ${a.attempt_id}`}
                  >
                    <td><span className="text-mono" style={{ fontSize: 11 }}>{a.attempt_id.slice(0, 20)}…</span></td>
                    <td><span className="tag">{a.execution_mode}</span></td>
                    <td><StatusBadge state={a.state} size="sm" /></td>
                    <td className="text-muted" style={{ fontSize: 11 }}>{a.started_at ? new Date(a.started_at).toLocaleString() : '—'}</td>
                    <td className="text-muted" style={{ fontSize: 11 }}>{a.ended_at ? new Date(a.ended_at).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <JobLog events={events} loading={loadingExtra} />
      </div>
    </div>
  )
}

function Info({ label, value, mono }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 13, fontFamily: mono ? 'var(--font-mono)' : undefined }}>{value}</div>
    </div>
  )
}

// ─── Job Table ───────────────────────────────────────────────────────────────
function JobTable({ onSelect, selected }: { onSelect: (id: string) => void; selected: string | null }) {
  const { jobs, loading, error, refresh, nextCursor, loadMore } = useJobList()

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="card-header">
        <span className="section-title">All Jobs</span>
        <button className="btn btn-ghost btn-sm" onClick={refresh} aria-label="Refresh job list">↻ Refresh</button>
      </div>
      {loading && <div className="skeleton" style={{ height: 120 }} />}
      {error && (
        <div className="error-state" style={{ padding: 16 }}>
          <div>Failed to load jobs</div>
          <div style={{ fontSize: 12 }}>{error}</div>
          <button className="btn btn-secondary btn-sm" onClick={refresh}>Retry</button>
        </div>
      )}
      {!loading && !error && jobs.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">◫</div>
          <div className="empty-state-title">No jobs found</div>
          <div className="empty-state-desc">Create a job from the Home page to get started.</div>
        </div>
      )}
      {jobs.length > 0 && (
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th><th>State</th><th>Attempts</th><th>Latest</th><th>Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.job_id}
                  className={selected === job.job_id ? 'selected' : ''}
                  onClick={() => onSelect(job.job_id)}
                  role="button" tabIndex={0}
                  onKeyDown={e => e.key === 'Enter' && onSelect(job.job_id)}
                  aria-selected={selected === job.job_id}
                  aria-label={`Select job ${job.display_name}`}
                >
                  <td>
                    <div style={{ fontWeight: 500 }}>{job.display_name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{job.job_id.slice(0, 24)}…</div>
                  </td>
                  <td><StatusBadge state={job.state} size="sm" /></td>
                  <td className="text-secondary">{job.attempt_count}</td>
                  <td>{job.latest_attempt ? <StatusBadge state={job.latest_attempt.state ?? 'CREATED'} size="sm" /> : <span className="text-muted">—</span>}</td>
                  <td className="text-muted" style={{ fontSize: 11 }}>{new Date(job.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {nextCursor && (
        <button className="btn btn-secondary btn-sm" onClick={loadMore} style={{ alignSelf: 'flex-start' }}>
          Load more
        </button>
      )}
    </div>
  )
}

// ─── Job Management Page ─────────────────────────────────────────────────────
export default function JobManagementPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <h1 className="page-title">Job Management</h1>
      <div style={{ display: 'grid', gridTemplateColumns: selectedId ? '1fr 1.4fr' : '1fr', gap: 20 }}>
        <JobTable onSelect={id => setSelectedId(id === selectedId ? null : id)} selected={selectedId} />
        {selectedId && (
          <div>
            <button className="btn btn-ghost btn-sm" onClick={() => setSelectedId(null)} style={{ marginBottom: 12 }}>
              ✕ Close
            </button>
            <JobDetailPanel jobId={selectedId} />
          </div>
        )}
      </div>
    </div>
  )
}
