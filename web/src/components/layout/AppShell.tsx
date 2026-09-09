import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useSystemStatus } from '../../hooks/useSystemStatus'

function BrandIcon() {
  return (
    <svg className="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      <path d="M4.93 4.93l2.12 2.12M16.95 16.95l2.12 2.12M4.93 19.07l2.12-2.12M16.95 7.05l2.12-2.12" />
    </svg>
  )
}

function HomeIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 12L12 3l9 9"/><path d="M9 21V12h6v9"/></svg>
}
function ActivityIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><polyline points="22,12 18,12 15,21 9,3 6,12 2,12"/></svg>
}
function LayersIcon() {
  return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><polygon points="12,2 22,8.5 12,15 2,8.5"/><path d="M2 15.5l10 6.5 10-6.5"/><path d="M2 12l10 6.5 10-6.5"/></svg>
}

function HealthDot({ status }: { status: string }) {
  const cls = status === 'healthy' || status === 'connected' ? 'health-healthy'
    : status === 'degraded' ? 'health-degraded'
    : 'health-disconnected'
  return (
    <span className={`ws-status ${cls}`} title={status}>
      <span className="ws-status-dot" />
    </span>
  )
}

interface AppShellProps { children: ReactNode }

export default function AppShell({ children }: AppShellProps) {
  const { health } = useSystemStatus(15000)

  return (
    <div className="app-shell">
      <header className="app-header" role="banner">
        <div className="header-inner">
          <div className="header-brand">
            <BrandIcon />
            <span>PBL4</span>
            <span className="brand-name">Distributed Training</span>
          </div>

          <nav className="header-nav" aria-label="Main navigation">
            <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <HomeIcon /> Home
            </NavLink>
            <NavLink to="/datasets" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              Datasets
            </NavLink>
            <NavLink to="/jobs" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <LayersIcon /> Jobs
            </NavLink>
            <NavLink to="/current-job" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              <ActivityIcon /> Current Job
            </NavLink>
            <NavLink to="/checkpoints" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              Checkpoints
            </NavLink>
            <NavLink to="/events" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              Events
            </NavLink>
            <NavLink to="/system" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
              System
            </NavLink>
          </nav>

          <div className="header-status" aria-label="System status">
            {health && (
              <span className="text-muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
                <HealthDot status={health.backend} />
                <span>BE:{health.backend}</span>
                <span>|</span>
                <HealthDot status={health.runtime_mcp} />
                <span>RT:{health.runtime_mcp}</span>
                <span>|</span>
                <HealthDot status={health.postgres} />
                <span>DB:{health.postgres}</span>
                <span>|</span>
                <HealthDot status={health.dataset_manager} />
                <span>DM:{health.dataset_manager}</span>
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="page-content" role="main">
        {children}
      </main>
    </div>
  )
}
