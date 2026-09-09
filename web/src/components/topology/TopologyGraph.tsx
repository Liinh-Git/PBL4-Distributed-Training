import type { WorkerSessionItem } from '../../domain/types'

interface TopologyGraphProps {
  workers: WorkerSessionItem[]
  attemptState?: string
}

function nodeColor(state: string) {
  if (state === 'CONNECTED' || state === 'running') return 'var(--success)'
  if (state === 'FAILED' || state === 'error') return 'var(--error)'
  if (state === 'DISCONNECTED') return 'var(--text-muted)'
  return 'var(--accent)'
}

function WorkerNode({ x, y, label, state, isCoord }: {
  x: number; y: number; label: string; state: string; isCoord?: boolean
}) {
  const color = nodeColor(state)
  const r = isCoord ? 44 : 36
  return (
    <g>
      <circle cx={x} cy={y} r={r} fill="var(--bg-elevated)" stroke={isCoord ? 'var(--accent)' : color} strokeWidth={isCoord ? 2 : 1.5} />
      {isCoord && <circle cx={x} cy={y} r={r + 6} fill="none" stroke="var(--accent)" strokeWidth={0.5} strokeDasharray="4 3" opacity={0.5} />}
      <circle cx={x + r - 6} cy={y - r + 6} r={5} fill={color}>
        {(state === 'CONNECTED' || state === 'running') && (
          <animate attributeName="opacity" values="1;0.4;1" dur="2s" repeatCount="indefinite" />
        )}
      </circle>
      <text x={x} y={y - 6} textAnchor="middle" fill="var(--text-primary)" fontSize={isCoord ? 11 : 10} fontFamily="Inter, sans-serif" fontWeight="600">
        {isCoord ? 'Coordinator' : label}
      </text>
      <text x={x} y={y + 10} textAnchor="middle" fill="var(--text-muted)" fontSize={9} fontFamily="JetBrains Mono, monospace">
        {state}
      </text>
    </g>
  )
}

export default function TopologyGraph({ workers, attemptState }: TopologyGraphProps) {
  const W = 520, H = 320
  const cx = W / 2, cy = H / 2

  if (workers.length === 0) {
    return (
      <div className="topology-container" style={{ height: 200 }}>
        <div className="empty-state">
          <div className="empty-state-icon">◎</div>
          <div className="empty-state-title">
            {attemptState === 'WAITING_WORKERS' ? 'Waiting for workers to connect…' : 'No workers connected'}
          </div>
        </div>
      </div>
    )
  }

  // Layout: coordinator at center, workers in a ring
  const radius = Math.min(120, 40 + workers.length * 20)
  const workerPositions = workers.map((_, i) => {
    const angle = (2 * Math.PI * i) / workers.length - Math.PI / 2
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) }
  })

  return (
    <div className="topology-container">
      <svg className="topology-svg" viewBox={`0 0 ${W} ${H}`} aria-label="Distributed topology">
        {/* Radial glow */}
        <radialGradient id="topo-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="rgba(34,211,238,0.06)" />
          <stop offset="100%" stopColor="transparent" />
        </radialGradient>
        <rect x={0} y={0} width={W} height={H} fill="url(#topo-glow)" />

        {/* Edges from coordinator to workers */}
        {workerPositions.map((pos, i) => (
          <line
            key={workers[i].session_id}
            x1={cx} y1={cy} x2={pos.x} y2={pos.y}
            stroke="var(--border-strong)" strokeWidth={1}
            strokeDasharray={workers[i].state === 'CONNECTED' ? 'none' : '4 3'}
          />
        ))}

        {/* Workers */}
        {workers.map((w, i) => (
          <WorkerNode
            key={w.session_id}
            x={workerPositions[i].x}
            y={workerPositions[i].y}
            label={w.node_label || `Worker ${w.worker_id}`}
            state={w.state}
          />
        ))}

        {/* Coordinator at center */}
        <WorkerNode x={cx} y={cy} label="Coordinator" state={attemptState ?? 'idle'} isCoord />
      </svg>
    </div>
  )
}
