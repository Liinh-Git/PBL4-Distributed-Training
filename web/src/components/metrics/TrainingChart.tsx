import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

interface DataPoint { [key: string]: number | string }

interface TrainingChartProps {
  title: string
  data: DataPoint[]
  xKey: string
  yKey: string
  unit?: string
  color?: string
}

const DARK_TOOLTIP = {
  contentStyle: {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border-strong)',
    borderRadius: 6,
    fontSize: 12,
    color: 'var(--text-primary)',
  },
  labelStyle: { color: 'var(--text-muted)' },
}

export function TrainingChart({ title, data, xKey, yKey, unit, color = 'var(--accent)' }: TrainingChartProps) {
  return (
    <div className="card" aria-label={title}>
      <div className="card-header">
        <span className="card-title">{title}</span>
        {unit && <span className="text-muted" style={{ fontSize: 11 }}>{unit}</span>}
      </div>
      {data.length === 0 ? (
        <div className="empty-state" style={{ padding: '24px 0' }}>
          <span className="empty-state-desc">No data yet</span>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
            <Tooltip {...DARK_TOOLTIP} />
            <Line type="monotone" dataKey={yKey} stroke={color} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

interface WorkerBarProps {
  title: string
  data: { name: string; value: number }[]
  unit?: string
}

export function WorkerComparisonChart({ title, data, unit }: WorkerBarProps) {
  return (
    <div className="card" aria-label={title}>
      <div className="card-header">
        <span className="card-title">{title}</span>
        {unit && <span className="text-muted" style={{ fontSize: 11 }}>{unit}</span>}
      </div>
      {data.length === 0 ? (
        <div className="empty-state" style={{ padding: '24px 0' }}>
          <span className="empty-state-desc">No worker data</span>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
            <Tooltip {...DARK_TOOLTIP} />
            <Bar dataKey="value" fill="var(--accent-2)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
