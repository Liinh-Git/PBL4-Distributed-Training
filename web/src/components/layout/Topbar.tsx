import React from 'react';
import { useLocation, Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

export const Topbar: React.FC = () => {
  const location = useLocation();

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
    <header className="h-12 bg-[#0b0b0c] border-b border-white/[0.14] px-6 flex items-center justify-between sticky top-0 z-30 select-none font-sans">
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
    </header>
  );
};
