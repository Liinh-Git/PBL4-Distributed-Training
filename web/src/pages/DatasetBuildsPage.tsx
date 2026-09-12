import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Layers,
  Search,
  Filter,
  ChevronRight,
  Database,
  Calendar,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { DatasetBuildStateBadge } from '../components/common/Badge';
import { datasetBuildsService } from '../api';
import { DatasetBuildListItemData, DatasetBuildState } from '../types/api';

export const DatasetBuildsPage: React.FC = () => {
  const [builds, setBuilds] = useState<DatasetBuildListItemData[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<string>('ALL');

  const fetchBuilds = async (cursor?: string | null, append = false) => {
    try {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      const params = {
        state: stateFilter === 'ALL' ? undefined : (stateFilter as DatasetBuildState),
        cursor,
        limit: 50,
      };

      const res = await datasetBuildsService.listBuilds(params);
      const data = res.data || [];
      setBuilds(prev => (append ? [...prev, ...data] : data));
      setNextCursor(res.page?.next_cursor || null);
    } catch (err: any) {
      setError(err?.message || 'Failed to load dataset builds');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    fetchBuilds();
  }, [stateFilter]);

  const filteredBuilds = builds.filter(b => {
    const matchesSearch =
      b.dataset_build_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (b.dataset_name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (b.profile || '').toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  return (
    <div className="space-y-4 w-full pb-10 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-semibold text-[#f3f3f4]">
              Dataset Builds
            </h1>
            {loading && (
              <span className="text-[11px] text-blue-400 font-mono animate-pulse">
                Loading API...
              </span>
            )}
          </div>
          <p className="text-xs text-[#73737c] mt-0.5">
            Materialized and sharded partitions prepared for training workers
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fetchBuilds()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#121214] hover:bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] text-xs font-medium transition-colors border border-white/[0.07]"
            title="Refresh builds"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <Link
            to="/datasets"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-[#f3f3f4] text-xs font-medium transition-colors border border-white/[0.07] w-fit"
          >
            <span>Datasets Catalog</span>
          </Link>
        </div>
      </div>

      {/* Error state */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => fetchBuilds()}
            className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-xs transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Search & Filter Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-2">
        <div className="relative flex-1 w-full">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-[#73737c]" />
          <input
            type="text"
            placeholder="Search builds or dataset names..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-[#121214] border border-white/[0.07] rounded text-xs text-[#f3f3f4] placeholder-[#73737c] focus:outline-hidden focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="flex items-center gap-0.5 bg-[#121214] border border-white/[0.07] rounded p-0.5 self-start sm:self-auto">
          {['ALL', 'READY', 'DEPRECATED', 'FAILED'].map(st => (
            <button
              key={st}
              type="button"
              onClick={() => setStateFilter(st)}
              className={`px-2.5 py-1 rounded text-xs transition-colors ${
                stateFilter === st
                  ? 'bg-white/[0.08] text-[#f3f3f4] font-medium'
                  : 'text-[#73737c] hover:text-[#a1a1a8]'
              }`}
            >
              {st}
            </button>
          ))}
        </div>
      </div>

      {/* Builds Table: Public Backend Fields Only */}
      <div className="bg-[#121214] border border-white/[0.07] rounded overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                <th className="py-2.5 px-3.5 font-medium">Dataset / Profile</th>
                <th className="py-2.5 px-3 font-medium">State</th>
                <th className="py-2.5 px-3 font-medium">Batch Size</th>
                <th className="py-2.5 px-3 font-medium text-center">Shards</th>
                <th className="py-2.5 px-3 font-medium text-right">Samples</th>
                <th className="py-2.5 px-3 font-medium">Created</th>
                <th className="py-2.5 px-3.5 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {loading && builds.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-[#73737c]">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
                      <span>Loading materialized dataset builds...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredBuilds.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-[#73737c]">
                    No dataset builds found matching query.
                  </td>
                </tr>
              ) : (
                filteredBuilds.map(b => (
                  <tr key={b.dataset_build_id} className="hover:bg-[#171719] transition-colors group">
                    <td className="py-2.5 px-3.5">
                      <div className="font-medium text-[#f3f3f4] group-hover:text-blue-400 transition-colors">
                        {b.dataset_name || 'Dataset'}
                      </div>
                      <div className="text-[11px] text-[#73737c] mt-0.5 max-w-md truncate font-mono">
                        {b.profile || b.dataset_build_id}
                      </div>
                    </td>

                    <td className="py-2.5 px-3">
                      <DatasetBuildStateBadge state={b.state as any} />
                    </td>

                    <td className="py-2.5 px-3 text-[#a1a1a8]">
                      {b.batch_size || 64}
                    </td>

                    <td className="py-2.5 px-3 text-center text-[#f3f3f4]">
                      {b.shard_count || 3}
                    </td>

                    <td className="py-2.5 px-3 text-right text-[#f3f3f4]">
                      {(b.sample_count || 50000).toLocaleString()}
                    </td>

                    <td className="py-2.5 px-3 text-[11px] text-[#73737c]">
                      {b.created_at ? b.created_at.slice(0, 10) : '2026-09-09'}
                    </td>

                    <td className="py-2.5 px-3.5 text-right">
                      <Link
                        to={`/dataset-builds/${b.dataset_build_id}`}
                        className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        <span>Details</span>
                        <ChevronRight className="w-3 h-3" />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Cursor Pagination Load More */}
        {nextCursor && (
          <div className="p-3 border-t border-white/[0.07] flex justify-center">
            <button
              type="button"
              onClick={() => fetchBuilds(nextCursor, true)}
              disabled={loadingMore}
              className="px-4 py-1.5 rounded bg-[#171719] hover:bg-[#1f1f23] text-xs text-[#f3f3f4] border border-white/[0.07] transition-colors flex items-center gap-2"
            >
              {loadingMore && <RefreshCw className="w-3 h-3 animate-spin" />}
              <span>Load more builds</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
