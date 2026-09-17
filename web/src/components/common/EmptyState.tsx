import React from 'react';
import { Layers } from 'lucide-react';

interface EmptyStateProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title,
  description,
  icon,
  action,
}) => {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center border border-dashed border-white/[0.08] rounded bg-[#121214]/60 font-sans select-none">
      <div className="p-3 bg-[#171719] border border-white/[0.06] rounded-full text-[#73737c] mb-3">
        {icon || <Layers className="w-5 h-5 text-[#a1a1a8]" />}
      </div>
      <h3 className="text-sm font-semibold text-[#f3f3f4]">{title}</h3>
      <p className="text-xs text-[#73737c] max-w-sm mt-1 mb-4 leading-relaxed">
        {description}
      </p>
      {action && <div>{action}</div>}
    </div>
  );
};
