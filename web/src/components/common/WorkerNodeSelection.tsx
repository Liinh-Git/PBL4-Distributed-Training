import { useCallback, useEffect, useId, useState } from 'react';
import { systemService } from '../../api';
import type { NodeItemData } from '../../types/api';

export interface WorkerSelection {
  mode: 'auto' | 'manual';
  nodeIds: string[];
}

export function selectionError(selection: WorkerSelection, frozenCount?: number): string | null {
  if (selection.mode === 'auto') {
    return frozenCount && frozenCount > 3 ? `Select exactly ${frozenCount} Nodes manually for this frozen Job.` : null;
  }
  const count = selection.nodeIds.length;
  if (count < 1 || count > 5 || new Set(selection.nodeIds).size !== count) return 'Select 1 to 5 distinct Nodes.';
  return frozenCount && count !== frozenCount ? `Select exactly ${frozenCount} Nodes for this frozen Job.` : null;
}

export function useWorkerNodes() {
  const [nodes, setNodes] = useState<NodeItemData[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const response = await systemService.getNodes({ signal });
      if (!signal?.aborted) { setNodes(response.data); setError(null); }
    } catch (err) {
      if (!signal?.aborted) setError(err instanceof Error ? err.message : 'Unable to load Nodes.');
    } finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);
  return { nodes, error, loading, refresh };
}

export function WorkerNodeSelection({ value, onChange, frozenCount, disabled = false }: {
  value: WorkerSelection;
  onChange: (value: WorkerSelection) => void;
  frozenCount?: number;
  disabled?: boolean;
}) {
  const groupId = useId();
  const { nodes, error, loading, refresh } = useWorkerNodes();
  const idle = nodes.filter(node => node.state === 'ONLINE' && !node.has_active_allocation);
  const problem = selectionError(value, frozenCount);
  return <fieldset disabled={disabled} className="space-y-3 rounded border border-white/[0.08] p-3 text-xs">
    <legend className="px-1 font-medium">Worker Nodes{frozenCount ? ` · ${frozenCount} Workers fixed for this Job` : ''}</legend>
    <p className="text-[#a1a1a8]">One Worker per Node. Dataset shards are independent of Worker count.</p>
    <div className="flex flex-wrap gap-4">
      <label className="flex items-center gap-2"><input type="radio" name={groupId} className="focus-visible:outline-2 focus-visible:outline-blue-500" checked={value.mode === 'auto'}
        disabled={Boolean(frozenCount && frozenCount > 3)}
        onChange={() => onChange({ mode: 'auto', nodeIds: [] })} />Automatic · up to 3</label>
      <label className="flex items-center gap-2"><input type="radio" name={groupId} className="focus-visible:outline-2 focus-visible:outline-blue-500" checked={value.mode === 'manual'}
        onChange={() => onChange({ ...value, mode: 'manual' })} />Manual · 1–5</label>
      <button type="button" disabled={loading} onClick={() => void refresh()} className="underline focus-visible:outline-2">Refresh Nodes</button>
    </div>
    {error && <p role="alert" className="text-rose-300">{error}</p>}
    {loading && <p role="status">Loading Nodes…</p>}
    {!loading && <p className="text-[#a1a1a8]">{idle.length} ONLINE and idle. Capacity is checked again when starting.</p>}
    {value.mode === 'manual' && <div className="max-h-48 space-y-2 overflow-y-auto">
      {nodes.map(node => {
        const checked = value.nodeIds.includes(node.node_id);
        const unavailable = node.state !== 'ONLINE' || node.has_active_allocation;
        return <label key={node.node_id} className="flex items-center gap-2">
          <input type="checkbox" name={`${groupId}-nodes`} className="focus-visible:outline-2 focus-visible:outline-blue-500" checked={checked}
            disabled={!checked && (Boolean(unavailable) || value.nodeIds.length >= (frozenCount ?? 5))}
            onChange={event => onChange({ mode: 'manual', nodeIds: event.target.checked
              ? [...value.nodeIds, node.node_id] : value.nodeIds.filter(id => id !== node.node_id) })} />
          <span>{node.display_name} · {node.state}{node.has_active_allocation ? ' · Busy' : ''}</span>
        </label>;
      })}
      {!loading && nodes.length === 0 && <p>No Nodes registered.</p>}
      <p>{value.nodeIds.length} selected{frozenCount ? ` / ${frozenCount} required` : ' / 5 maximum'}</p>
    </div>}
    {problem && <p role="status" className="text-amber-300">{problem}</p>}
    {frozenCount && <p className="text-[#a1a1a8]">Clone this Job to change its Worker count.</p>}
  </fieldset>;
}
