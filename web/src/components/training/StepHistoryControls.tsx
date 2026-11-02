import React from 'react';

interface Props {
  error: string | null;
  onRetry: () => void;
}

export function StepHistoryControls({ error, onRetry }: Props) {
  if (!error) return null;
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-xs text-rose-400">
      <span>{error}</span>
      <button type="button" onClick={onRetry}
        className="underline focus-visible:outline-2 focus-visible:outline-blue-400">Thử lại</button>
    </div>
  );
}
