import React from 'react';
import { Database, LoaderCircle } from 'lucide-react';
import { getPreparationStatus } from '../../utils/preparation';

interface Props {
  state: string;
  workers: readonly { state: string }[];
  expectedWorkers: number | null;
  isStale: boolean;
  observedAt?: string | null;
}

export function PreparationStatus({ state, workers, expectedWorkers, isStale, observedAt }: Props) {
  const status = getPreparationStatus(state, workers);
  if (!status.preparing) return null;
  const count = (value: number) => `${value}/${expectedWorkers ?? '—'}`;
  return (
    <section aria-label="Training preparation" aria-live="polite"
      className="rounded border border-blue-400/20 bg-blue-400/[0.04] p-4 space-y-3">
      <div className="flex items-start gap-3">
        {isStale
          ? <Database aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          : <LoaderCircle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-blue-400 animate-spin motion-reduce:animate-none" />}
        <div className="min-w-0 space-y-1">
          <h2 className="text-sm font-medium text-[#f3f3f4]">
            {isStale ? `Last observed: ${status.label}` : status.label}
          </h2>
          <p className="text-xs text-[#a1a1a8]">
            {isStale ? 'Telemetry is stale. Current download and readiness status are unknown.' : status.description}
          </p>
          {observedAt && <p className="text-[11px] text-[#73737c]">Last update: <time dateTime={observedAt}>{new Date(observedAt).toLocaleTimeString()}</time></p>}
        </div>
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs tabular-nums">
        <div><dt className="inline text-[#a1a1a8]">DTP connected </dt><dd className="inline text-[#f3f3f4]">{count(status.connected)}</dd></div>
        <div><dt className="inline text-[#a1a1a8]">Dataset verified </dt><dd className="inline text-[#f3f3f4]">{count(status.dataReady)}</dd></div>
        <div><dt className="inline text-[#a1a1a8]">Ready to train </dt><dd className="inline text-[#f3f3f4]">{count(status.ready)}</dd></div>
      </dl>
    </section>
  );
}
