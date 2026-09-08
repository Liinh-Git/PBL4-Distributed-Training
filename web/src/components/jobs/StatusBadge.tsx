import type { AttemptState, JobState } from '../../domain/types'

type AnyState = JobState | AttemptState | string

interface StatusBadgeProps {
  state: AnyState
  size?: 'sm' | 'md'
}

const LABELS: Record<string, string> = {
  DRAFT: 'Draft', READY: 'Ready', ARCHIVED: 'Archived',
  CREATED: 'Created', WAITING_WORKERS: 'Waiting', PROVISIONING: 'Provisioning',
  INITIALIZING: 'Initializing', RUNNING: 'Running', COMPLETING: 'Completing',
  COMPLETED: 'Completed', FAILED: 'Failed', ABORTED: 'Aborted',
  CONNECTED: 'Connected', DISCONNECTED: 'Disconnected',
  PENDING: 'Pending', BUILDING: 'Building', DEPRECATED: 'Deprecated',
}

export default function StatusBadge({ state, size }: StatusBadgeProps) {
  const label = LABELS[state] ?? state
  return (
    <span className={`status-badge status-${state}${size === 'sm' ? ' btn-sm' : ''}`} aria-label={`Status: ${label}`}>
      <span className="status-dot" aria-hidden="true" />
      {label}
    </span>
  )
}
