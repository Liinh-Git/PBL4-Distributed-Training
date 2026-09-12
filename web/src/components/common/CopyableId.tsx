import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface CopyableIdProps {
  value?: string | null;
  truncateLength?: number;
  prefix?: string;
  className?: string;
  title?: string;
}

export const CopyableId: React.FC<CopyableIdProps> = ({
  value,
  truncateLength = 16,
  prefix,
  className = '',
  title,
}) => {
  const [copied, setCopied] = useState(false);
  const safeVal = value != null ? String(value) : '';

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!safeVal) return;
    navigator.clipboard.writeText(safeVal);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const displayText =
    truncateLength && safeVal.length > truncateLength
      ? `${safeVal.slice(0, Math.floor(truncateLength / 2))}...${safeVal.slice(-Math.floor(truncateLength / 2))}`
      : safeVal || '—';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-xs text-slate-300 group hover:text-slate-100 ${className}`}
      title={title || safeVal}
    >
      {prefix && <span className="text-slate-500 select-none">{prefix}</span>}
      <span className="tracking-tight select-all">{displayText}</span>
      {safeVal && (
        <button
          type="button"
          onClick={handleCopy}
          className="p-1 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors focus:outline-hidden"
          title={copied ? 'Copied to clipboard!' : `Copy full value: ${safeVal}`}
          aria-label="Copy identifier"
        >
          {copied ? (
            <Check className="w-3 h-3 text-emerald-400 animate-in fade-in" />
          ) : (
            <Copy className="w-3 h-3 opacity-60 group-hover:opacity-100 transition-opacity" />
          )}
        </button>
      )}
    </span>
  );
};
