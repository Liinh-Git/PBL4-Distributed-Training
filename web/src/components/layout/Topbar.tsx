import React from 'react';
import { useLocation, Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

export const Topbar: React.FC = () => {
  const location = useLocation();

  // Helper to format human-friendly breadcrumb labels without exposing raw technical IDs
  const getFriendlyLabel = (segment: string, pathSegments: string[], index: number): string => {
    if (segment === 'runs') return 'Lịch sử Huấn luyện';
    if (segment === 'live') {
      return location.search.includes('tab=metrics') ? 'Kết quả Huấn luyện' : 'Huấn luyện Trực tiếp';
    }
    if (segment === 'jobs' || segment === 'training') return 'Nhiệm vụ';
    if (segment === 'datasets') return 'Tập dữ liệu';
    if (segment === 'dataset-builds') return 'Bản dựng dữ liệu';
    if (segment === 'checkpoints') return 'Checkpoints';
    if (segment === 'system') return 'Hệ thống';
    if (segment === 'events') return 'Sự kiện';
    if (segment === 'new') return 'Tạo mới';
    if (segment === 'edit') return 'Chỉnh sửa';

    const lower = segment.toLowerCase();

    // If segment is a Job ID
    if (lower.startsWith('job_') || pathSegments[index - 1] === 'jobs') {
      try {
        const cached = sessionStorage.getItem(`pbl4_job_title_${segment}`) || sessionStorage.getItem(`pbl4_job_title_${lower}`);
        if (cached) return cached;
      } catch {}
      return 'Chi tiết Nhiệm vụ';
    }

    // If segment is an Attempt ID
    if (lower.startsWith('atm_') || pathSegments[index - 1] === 'attempts') {
      return 'Lần chạy';
    }

    // If segment is a Dataset ID
    if (lower.startsWith('ds_') || pathSegments[index - 1] === 'datasets') {
      try {
        const cached = sessionStorage.getItem(`pbl4_ds_title_${segment}`) || sessionStorage.getItem(`pbl4_ds_title_${lower}`);
        if (cached) return cached;
      } catch {}
      return 'Chi tiết Tập dữ liệu';
    }

    // If segment is a Checkpoint ID
    if (lower.startsWith('chk_') || pathSegments[index - 1] === 'checkpoints') {
      return 'Mốc Lưu Checkpoint';
    }

    // If segment is a Build ID or hex hash
    if (lower.startsWith('build_') || /^[0-9a-f]{8,}$/i.test(segment) || /^[0-9a-f-]{20,}$/i.test(segment)) {
      return 'Bản dựng';
    }

    return segment
      .replace(/-/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  };

  // Generate breadcrumb items
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const breadcrumbs = [
    { label: 'Console', path: '/' },
    ...pathSegments.map((segment, index) => {
      let url = `/${pathSegments.slice(0, index + 1).join('/')}`;
      if (url === '/training') url = '/jobs';
      const formatted = getFriendlyLabel(segment, pathSegments, index);
      return { label: formatted, path: url };
    }),
  ];

  if ((location.search.includes('attempt_id=') || location.search.includes('attemptId=')) && location.pathname !== '/live') {
    breadcrumbs.push({
      label: 'Chi tiết Lần chạy',
      path: location.pathname + location.search,
    });
  }

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
