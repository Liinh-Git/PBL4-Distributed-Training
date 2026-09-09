interface MetricCardProps {
  label: string
  value: string | number
  sub?: string
  accent?: boolean
}

export default function MetricCard({ label, value, sub, accent }: MetricCardProps) {
  return (
    <div className={`metric-card${accent ? ' card-accent' : ''}`}>
      <div className="metric-card-label">{label}</div>
      <div className="metric-card-value">{value}</div>
      {sub && <div className="metric-card-sub">{sub}</div>}
    </div>
  )
}
