import React, { useRef } from 'react';
import { AlertTriangle, RefreshCw, X } from 'lucide-react';

interface ConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  isLoading?: boolean;
  closeOnConfirm?: boolean;
}

export const ConfirmationModal: React.FC<ConfirmationModalProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = true,
  isLoading = false,
  closeOnConfirm = true,
}) => {
  const confirmingRef = useRef(false);
  if (!isOpen) return null;
  const close = () => { if (!isLoading) onClose(); };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 font-sans select-none">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-[#09090b]/80 backdrop-blur-xs transition-opacity"
        onClick={close}
      />

      {/* Modal Dialog */}
      <div className="relative bg-[#121214] border border-white/[0.08] rounded shadow-2xl max-w-md w-full p-5 z-10 animate-in zoom-in-95 duration-150">
        <div className="flex items-start gap-3.5">
          <div
            className={`p-2 rounded shrink-0 ${
              isDestructive
                ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
            }`}
          >
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-[#f3f3f4]">{title}</h3>
            <div className="text-xs text-[#a1a1a8] mt-1.5 leading-relaxed">
              {message}
            </div>
          </div>
          <button
            onClick={close}
            disabled={isLoading}
            aria-label="Close confirmation"
            className="text-[#73737c] hover:text-[#f3f3f4] p-1 rounded hover:bg-[#171719] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2.5 pt-3.5 border-t border-white/[0.07]">
          <button
            type="button"
            onClick={close}
            disabled={isLoading}
            className="px-3 py-1.5 text-xs font-normal rounded text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] transition-colors border border-white/[0.07]"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            disabled={isLoading}
            aria-busy={isLoading}
            onClick={async () => {
              if (isLoading || confirmingRef.current) return;
              confirmingRef.current = true;
              try {
                const result = onConfirm();
                if (closeOnConfirm) onClose();
                await result;
              } finally {
                confirmingRef.current = false;
              }
            }}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded transition-colors disabled:opacity-50 ${
              isDestructive
                ? 'bg-rose-600 hover:bg-rose-500 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            }`}
          >
            {isLoading && <RefreshCw aria-hidden="true" className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
