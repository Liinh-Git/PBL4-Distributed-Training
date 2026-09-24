import React, { useEffect } from 'react';
import { X } from 'lucide-react';

interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClass?: string;
}

export const Drawer: React.FC<DrawerProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  widthClass = 'max-w-xl',
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = 'auto';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-[#09090b]/80 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over panel */}
      <div
        className={`relative w-full ${widthClass} bg-[#101012] border-l border-white/[0.06] flex flex-col h-full z-10 animate-in slide-in-from-right duration-200`}
        role="dialog"
        aria-modal="true"
      >
        {/* Drawer Header */}
        <div className="px-5 py-4 border-b border-white/[0.06] flex items-start justify-between bg-[#101012] sticky top-0 z-10">
          <div className="pr-4">
            <h2 className="text-base font-semibold text-[#f4f4f5] flex items-center gap-2">
              {title}
            </h2>
            {subtitle && (
              <div className="text-xs text-[#71717a] mt-1 font-mono">{subtitle}</div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-xs text-[#71717a] hover:text-[#f4f4f5] hover:bg-[#18181b] transition-colors"
            aria-label="Close panel"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drawer Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6 text-sm text-[#d4d4d8]">
          {children}
        </div>

        {/* Optional Footer */}
        {footer && (
          <div className="px-5 py-3 border-t border-white/[0.06] bg-[#101012] flex items-center justify-end gap-3 sticky bottom-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
