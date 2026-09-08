import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSystemStatus } from '../hooks/useSystemStatus'
import { datasetsApi } from '../api/datasets'
import { jobsApi } from '../api/jobs'
import { useJobList } from '../hooks/useJobs'
import StatusBadge from '../components/jobs/StatusBadge'
import TopologyGraph from '../components/topology/TopologyGraph'
import type { DatasetBuildListItem } from '../domain/types'

// ─── System Health Strip ────────────────────────────────────────────────────
function HealthStrip() {
  const { health, snapshot } = useSystemStatus(10000)
  if (!health) return (
    <div className="card flex gap-12 items-center" style={{ padding: '10px 16px' }}>
      <div className="skeleton" style={{ width: 200, height: 14 }} />
    </div>
  )
  return (
    <div className="card" style={{ padding: '10px 16px', display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center' }}>
      <StatusItem label="Backend" status={health.backend} good="healthy" />
      <StatusItem label="PostgreSQL" status={health.postgres} good="healthy" />
      <StatusItem label="Runtime" status={health.runtime_mcp} good="connected" />
      <StatusItem label="Dataset Manager" status={health.dataset_manager} good="healthy" />
      {snapshot?.stale && (
        <span className="text-muted" style={{ fontSize: 11 }}>⚠ Runtime snapshot is stale</span>
      )}
    </div>
  )
}

function StatusItem({ label, status, good }: { label: string; status: string; good: string }) {
  const ok = status === good
  const color = ok ? 'var(--success)' : status === 'degraded' || status === 'disconnected' ? 'var(--warning)' : 'var(--text-muted)'
  const icon = ok ? '●' : status === 'degraded' ? '◐' : '○'
  return (
    <span style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ color }}>{icon}</span>
      <span className="text-secondary">{label}:</span>
      <span style={{ color, fontWeight: 500 }}>{status}</span>
    </span>
  )
}

// ─── Job Create Form ────────────────────────────────────────────────────────
interface JobFormValues {
  display_name: string
  description: string
  dataset_build_id: string
  model_id: string
  epochs: number
  learning_rate: number
  training_seed: number
  training_strategy: string
}

const DEFAULT_FORM: JobFormValues = {
  display_name: '',
  description: '',
  dataset_build_id: '',
  model_id: 'model_v1',
  epochs: 5,
  learning_rate: 0.01,
  training_seed: 42,
  training_strategy: 'strict_bsp',
}

function JobCreateForm() {
  const navigate = useNavigate()
  const [form, setForm] = useState<JobFormValues>(DEFAULT_FORM)
  const [builds, setBuilds] = useState<DatasetBuildListItem[]>([])
  const [loadingBuilds, setLoadingBuilds] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState<string | null>(null)

  useEffect(() => {
    datasetsApi.builds({ state: 'READY', limit: 100 })
      .then(r => setBuilds(r.data))
      .catch(() => setBuilds([]))
      .finally(() => setLoadingBuilds(false))
  }, [])

  function validate(): boolean {
    const e: Record<string, string> = {}
    if (!form.display_name.trim()) e.display_name = 'Job name is required'
    if (!form.dataset_build_id) e.dataset_build_id = 'Select a dataset build'
    if (!form.model_id.trim()) e.model_id = 'Model ID is required'
    if (form.epochs < 1) e.epochs = 'Must be ≥ 1'
    if (form.learning_rate <= 0) e.learning_rate = 'Must be > 0'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  function errMsg(e: unknown): string {
    return e instanceof Error ? e.message : String(e)
  }

  async function handleSaveDraft() {
    if (!validate()) return
    setSubmitting(true); setServerError(null)
    try {
      await jobsApi.create({
        display_name: form.display_name,
        description: form.description,
        requested_contract: {
          dataset_build_id: form.dataset_build_id,
          model_id: form.model_id,
          epochs: form.epochs,
          learning_rate: form.learning_rate,
          training_seed: form.training_seed,
          training_strategy: form.training_strategy,
        },
      })
      navigate('/jobs')
    } catch (e) {
      setServerError(errMsg(e))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleStartJob() {
    if (!validate()) return
    setSubmitting(true); setServerError(null)
    try {
      const job = await jobsApi.create({
        display_name: form.display_name,
        description: form.description,
        requested_contract: {
          dataset_build_id: form.dataset_build_id,
          model_id: form.model_id,
          epochs: form.epochs,
          learning_rate: form.learning_rate,
          training_seed: form.training_seed,
          training_strategy: form.training_strategy,
        },
      })
      const frozen = await jobsApi.freeze(job.job_id)
      await jobsApi.start(frozen.job_id)
      navigate('/current-job')
    } catch (e) {
      setServerError(errMsg(e))
    } finally {
      setSubmitting(false)
    }
  }

  const set = (k: keyof JobFormValues) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const val = e.target.type === 'number' ? Number(e.target.value) : e.target.value
    setForm(f => ({ ...f, [k]: val }))
    setErrors(er => { const n = { ...er }; delete n[k]; return n })
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="card-header">
        <span className="section-title">Create Job</span>
      </div>

      {serverError && (
        <div style={{ background: 'var(--error-dim)', border: '1px solid var(--error)', borderRadius: 6, padding: '10px 14px', color: 'var(--error)', fontSize: 13 }}>
          {serverError}
        </div>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor="job-name">Job Name <span className="required">*</span></label>
        <input id="job-name" className="form-input" value={form.display_name} onChange={set('display_name')} placeholder="e.g. CIFAR-10 Training Run" disabled={submitting} />
        {errors.display_name && <span className="form-error">{errors.display_name}</span>}
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="job-desc">Description</label>
        <input id="job-desc" className="form-input" value={form.description} onChange={set('description')} placeholder="Optional description" disabled={submitting} />
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="dataset-build">Dataset Build <span className="required">*</span></label>
        <select id="dataset-build" className="form-select" value={form.dataset_build_id} onChange={set('dataset_build_id')} disabled={submitting || loadingBuilds}>
          <option value="">{loadingBuilds ? 'Loading…' : builds.length === 0 ? 'No READY builds available' : '— Select build —'}</option>
          {builds.map(b => (
            <option key={b.dataset_build_id} value={b.dataset_build_id}>
              {b.dataset_build_id} ({b.profile}, {b.sample_count ?? '?'} samples)
            </option>
          ))}
        </select>
        {errors.dataset_build_id && <span className="form-error">{errors.dataset_build_id}</span>}
        {!loadingBuilds && builds.length === 0 && (
          <span className="form-hint">Create a dataset build via the API to use it here.</span>
        )}
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="model-id">Model ID <span className="required">*</span></label>
        <input id="model-id" className="form-input" value={form.model_id} onChange={set('model_id')} placeholder="e.g. model_v1" disabled={submitting} />
        {errors.model_id && <span className="form-error">{errors.model_id}</span>}
      </div>

      <div className="form-group">
        <label className="form-label" htmlFor="strategy">Training Strategy</label>
        <select id="strategy" className="form-select" value={form.training_strategy} onChange={set('training_strategy')} disabled={submitting}>
          <option value="strict_bsp">Strict BSP (Synchronous)</option>
        </select>
        <span className="form-hint">V1 supports Strict BSP only</span>
      </div>

      <div className="grid-3">
        <div className="form-group">
          <label className="form-label" htmlFor="epochs">Epochs <span className="required">*</span></label>
          <input id="epochs" type="number" className="form-input" value={form.epochs} onChange={set('epochs')} min={1} disabled={submitting} />
          {errors.epochs && <span className="form-error">{errors.epochs}</span>}
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="lr">Learning Rate</label>
          <input id="lr" type="number" className="form-input" value={form.learning_rate} onChange={set('learning_rate')} step={0.001} min={0.0001} disabled={submitting} />
          {errors.learning_rate && <span className="form-error">{errors.learning_rate}</span>}
        </div>
        <div className="form-group">
          <label className="form-label" htmlFor="seed">Training Seed</label>
          <input id="seed" type="number" className="form-input" value={form.training_seed} onChange={set('training_seed')} disabled={submitting} />
        </div>
      </div>

      <div className="flex gap-8" style={{ marginTop: 4 }}>
        <button className="btn btn-primary" onClick={handleStartJob} disabled={submitting} aria-label="Create and start job">
          {submitting ? '⟳ Starting…' : '▶ Start Job'}
        </button>
        <button className="btn btn-secondary" onClick={handleSaveDraft} disabled={submitting} aria-label="Save as draft">
          {submitting ? '⟳ Saving…' : 'Save Draft'}
        </button>
      </div>
    </div>
  )
}

// ─── Recent Jobs Panel ───────────────────────────────────────────────────────
function RecentJobs() {
  const { jobs, loading, error } = useJobList()
  const navigate = useNavigate()
  const recent = jobs.slice(0, 5)

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="card-header">
        <span className="section-title">Recent Jobs</span>
        <button className="btn btn-ghost btn-sm" onClick={() => navigate('/jobs')}>View all</button>
      </div>
      {loading && <div className="skeleton" style={{ height: 60 }} />}
      {error && <div className="text-warning" style={{ fontSize: 12 }}>⚠ {error}</div>}
      {!loading && !error && recent.length === 0 && (
        <div className="empty-state" style={{ padding: '16px 0' }}>
          <div className="empty-state-title">No jobs yet</div>
          <div className="empty-state-desc">Create your first job using the form.</div>
        </div>
      )}
      {recent.map(job => (
        <div key={job.job_id}
          style={{ padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
          onClick={() => navigate('/jobs')}
          role="button" tabIndex={0}
          onKeyDown={e => e.key === 'Enter' && navigate('/jobs')}
          aria-label={`Open job ${job.display_name}`}
        >
          <div>
            <div style={{ fontSize: 13, fontWeight: 500 }}>{job.display_name}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{job.job_id}</div>
          </div>
          <StatusBadge state={job.latest_attempt?.state ?? job.state} size="sm" />
        </div>
      ))}
    </div>
  )
}

// ─── Topology Preview ───────────────────────────────────────────────────────
function TopologyPreview() {
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="card-header">
        <span className="section-title">System Topology</span>
        <span className="text-muted" style={{ fontSize: 11 }}>No active attempt</span>
      </div>
      <TopologyGraph workers={[]} attemptState="idle" />
    </div>
  )
}

// ─── Home Page ───────────────────────────────────────────────────────────────
export default function HomePage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 className="page-title">Home</h1>
      </div>
      <HealthStrip />
      <div className="grid-2">
        <JobCreateForm />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <RecentJobs />
          <TopologyPreview />
        </div>
      </div>
    </div>
  )
}
