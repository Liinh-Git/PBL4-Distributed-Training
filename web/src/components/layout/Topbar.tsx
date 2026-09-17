import React, { useEffect, useState } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { ChevronRight, RefreshCw } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { systemService } from '../../api';
import { HealthData } from '../../types/api';

export const Topbar: React.FC = () => {
  const location = useLocation();
  const { isRuntimeStale } = useApp();
  const [health, setHealth] = useState<HealthData | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);
  const [healthError, setHealthError] = useState<boolean>(false);

  const fetchHealth = async () => {
    try {
      setHealthLoading(true);
      const res = await systemService.getHealth();
      setHealth(res.data);
      setHealthError(false);
    } catch {
      setHealthError(true);
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, 30000);
    return () => clearInterval(timer);
  }, []);

  // Contract: 'ok' | 'degraded' | 'down'. Also handle backend discrepancy 'healthy'.
  const isHealthy = !healthError && !isRuntimeStale && (
    health?.status === 'ok' || (health?.status as unknown as string) === 'healthy'
  );
  const isDegraded = !healthError && (health?.status === 'degraded' || isRuntimeStale);

  // Generate breadcrumb items
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const breadcrumbs = [
    { label: 'Console', path: '/' },
    ...pathSegments.map((segment, index) => {
      const url = `/${pathSegments.slice(0, index + 1).join('/')}`;
      const formatted = segment
        .replace(/-/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
      return { label: formatted, path: url };
    }),
  ];

  return (
    <header className="h-12 bg-[#0b0b0c] border-b border-white/[0.07] px-6 flex items-center justify-between sticky top-0 z-30 select-none font-sans">
      {/* Breadcrumb Navigation */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-xs">
        {breadcrumbs.map((crumb, idx) => {
          const isLast = idx === breadcrumbs.length - 1;
          return (
            <React.Fragment key={crumb.path}>
              {idx > 0 && <ChevronRight className="w-3.5 h-3.5 text-[#73737c]" />}
              {isLast ? (
                <span className="font-normal text-[#f3f3f4]">{crumb.label}</span>
              ) : (
                <Link
                  to={crumb.path}
                  className="text-[#73737c] hover:text-[#f3f3f4] transition-colors"
                >
                  {crumb.label}
                </Link>
              )}
            </React.Fragment>
          );
        })}
      </nav>

      {/* Topbar Utility Actions & Indicators */}
      <div className="flex items-center gap-3">
        {/* System Health Status */}
        <div className="flex items-center gap-1.5 text-xs text-[#a1a1a8]">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              healthLoading && !health
                ? 'bg-zinc-500 animate-pulse'
                : isHealthy
                ? 'bg-emerald-400'
                : isDegraded
                ? 'bg-amber-400'
                : 'bg-rose-400'
            }`}
          />
          <span className="text-xs">
            {healthLoading && !health
              ? 'Checking status...'
              : isHealthy
              ? 'System healthy'
              : isDegraded
              ? 'Degraded'
              : 'Connection warning'}
          </span>
        </div>

        {/* Refresh Button */}
        <button
          type="button"
          onClick={() => {
            fetchHealth();
            window.location.reload();
          }}
          className="p-1 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.04] transition-colors"
          title="Refresh console state"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>
    </header>
  );
};
