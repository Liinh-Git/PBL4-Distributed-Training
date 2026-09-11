import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Activity,
  Briefcase,
  Database,
  Save,
  Server,
} from 'lucide-react';
import { StatusDot } from '../common/Badge';
import { useApp } from '../../context/AppContext';

export const Sidebar: React.FC = () => {
  const { currentAttempt } = useApp();

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
          activeIndicator: currentAttempt.state === 'RUNNING',
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
    <aside className="w-56 shrink-0 bg-[#0d0d0f] border-r border-white/[0.07] flex flex-col h-screen select-none font-sans">
      {/* Brand Header */}
      <div className="h-12 px-4 border-b border-white/[0.07] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[#f3f3f4] tracking-tight">
            Training Console
          </span>
        </div>
      </div>

      {/* Navigation Groups */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {navGroups.map((group, idx) => (
          <div key={group.label || `group_${idx}`} className="space-y-1">
            {group.label && (
              <div className="px-2 pb-0.5 text-[11px] text-[#73737c]">
                {group.label}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map(item => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.path === '/'}
                    className={({ isActive }) =>
                      `flex items-center justify-between px-2.5 py-1.5 rounded text-xs font-normal transition-colors ${
                        isActive
                          ? 'bg-[#171719] text-[#f3f3f4] font-medium border-l-2 border-blue-500 pl-2 rounded-l-none'
                          : 'text-[#73737c] hover:text-[#f3f3f4] hover:bg-white/[0.03]'
                      }`
                    }
                  >
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 shrink-0 opacity-80" />
                      <span>{item.name}</span>
                    </div>
                    {item.activeIndicator && (
                      <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        Live
                      </span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer: Subtle Backend Connection Status */}
      <div className="px-3.5 py-2.5 border-t border-white/[0.07] bg-[#0d0d0f] text-xs text-[#73737c] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span className="text-[#a1a1a8] text-xs">Connected</span>
        </div>
      </div>
    </aside>
  );
};
