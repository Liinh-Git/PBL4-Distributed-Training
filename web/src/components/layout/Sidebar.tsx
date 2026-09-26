import React, { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Activity,
  Briefcase,
  Database,
  Save,
  Server,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { attemptsService } from '../../api';

export const Sidebar: React.FC = () => {
  const [hasRunningAttempt, setHasRunningAttempt] = useState<boolean>(false);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('pbl4_sidebar_collapsed') === 'true';
    }
    return false;
  });

  const toggleCollapsed = () => {
    setIsCollapsed(prev => {
      const next = !prev;
      try {
        localStorage.setItem('pbl4_sidebar_collapsed', String(next));
      } catch {
        // Ignore localStorage error
      }
      return next;
    });
  };

  useEffect(() => {
    let isMounted = true;
    attemptsService.listAttempts({ state: 'RUNNING', limit: 1 })
      .then(res => {
        if (isMounted && res.data && res.data.length > 0) {
          setHasRunningAttempt(true);
        }
      })
      .catch(() => {
        // Degraded or network failure: leave as false
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const navGroups = [
    {
      label: null,
      items: [
        {
          name: 'Overview',
          path: '/',
          icon: LayoutDashboard,
        },
      ],
    },
    {
      label: 'Training',
      items: [
        {
          name: 'Live Training',
          path: '/live',
          icon: Activity,
          activeIndicator: hasRunningAttempt,
        },
        {
          name: 'Jobs',
          path: '/jobs',
          icon: Briefcase,
        },
      ],
    },
    {
      label: 'Data',
      items: [
        {
          name: 'Datasets',
          path: '/datasets',
          icon: Database,
        },
      ],
    },
    {
      label: 'Recovery',
      items: [
        {
          name: 'Checkpoints',
          path: '/checkpoints',
          icon: Save,
        },
      ],
    },
    {
      label: 'System',
      items: [
        {
          name: 'System',
          path: '/system',
          icon: Server,
        },
      ],
    },
  ];

  return (
    <aside
      className={`${
        isCollapsed ? 'w-16' : 'w-56'
      } shrink-0 bg-[#0d0d0f] border-r border-white/[0.14] flex flex-col h-screen select-none font-sans transition-all duration-200 ease-in-out`}
    >
      {/* Brand Header & Toggle Button */}
      <div className="h-12 px-3 border-b border-white/[0.14] flex items-center justify-between">
        {!isCollapsed ? (
          <>
            <div className="flex items-center gap-2 overflow-hidden pl-1">
              <span className="text-xs font-semibold text-[#f3f3f4] tracking-tight truncate">
                Training Console
              </span>
            </div>
            <button
              type="button"
              onClick={toggleCollapsed}
              className="p-1.5 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.06] transition-colors"
              title="Thu gọn sidebar (Collapse)"
              aria-label="Thu gọn sidebar"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          </>
        ) : (
          <div className="w-full flex items-center justify-center">
            <button
              type="button"
              onClick={toggleCollapsed}
              className="p-1.5 rounded text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.06] transition-colors"
              title="Mở rộng sidebar (Expand)"
              aria-label="Mở rộng sidebar"
            >
              <ChevronRight className="w-4 h-4 text-blue-400" />
            </button>
          </div>
        )}
      </div>

      {/* Navigation Groups */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {navGroups.map((group, idx) => (
          <div key={group.label || `group_${idx}`} className="space-y-1">
            {!isCollapsed && group.label && (
              <div className="px-2 pb-0.5 text-[11px] text-[#73737c]">
                {group.label}
              </div>
            )}
            {isCollapsed && group.label && (
              <div className="my-1.5 border-t border-white/[0.06]" />
            )}
            <div className="space-y-0.5">
              {group.items.map(item => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.path === '/'}
                    title={isCollapsed ? item.name : undefined}
                    className={({ isActive }) =>
                      isCollapsed
                        ? `relative flex items-center justify-center py-2.5 rounded text-xs font-normal transition-colors ${
                            isActive
                              ? 'bg-[#171719] text-[#f3f3f4] border-l-2 border-blue-500 rounded-l-none'
                              : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.03]'
                          }`
                        : `flex items-center justify-between px-2.5 py-1.5 rounded text-xs font-normal transition-colors ${
                            isActive
                              ? 'bg-[#171719] text-[#f3f3f4] font-medium border-l-2 border-blue-500 pl-2 rounded-l-none'
                              : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.03]'
                          }`
                    }
                  >
                    {!isCollapsed ? (
                      <>
                        <div className="flex items-center gap-2 truncate">
                          <Icon className="w-3.5 h-3.5 shrink-0 opacity-80" />
                          <span className="truncate">{item.name}</span>
                        </div>
                        {item.activeIndicator && (
                          <span className="flex items-center gap-1 text-[10px] text-emerald-400 shrink-0">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                            Live
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        <Icon className="w-4 h-4 shrink-0 opacity-80" />
                        {item.activeIndicator && (
                          <span
                            className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-emerald-400"
                            title="Live attempt running"
                          />
                        )}
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer: Subtle Backend Connection Status */}
      <div className="px-3.5 py-2.5 border-t border-white/[0.14] bg-[#0d0d0f] text-xs text-[#73737c] flex items-center justify-between">
        {!isCollapsed ? (
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="text-[#a1a1a8] text-xs">Connected</span>
          </div>
        ) : (
          <div className="w-full flex items-center justify-center" title="Backend: Connected">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
          </div>
        )}
      </div>
    </aside>
  );
};
