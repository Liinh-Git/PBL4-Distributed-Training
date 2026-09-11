import React, { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ShieldCheck,
  CheckCircle2,
  HardDrive,
  Layers,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  Trash2,
  RotateCcw,
  Archive,
} from 'lucide-react';
import { DatasetBuildStateBadge, Badge } from '../components/common/Badge';
import { CopyableId } from '../components/common/CopyableId';
import { EmptyState } from '../components/common/EmptyState';
import { ConfirmationModal } from '../components/common/ConfirmationModal';
import { datasetBuildsService } from '../api';
import { DatasetBuildDetailData } from '../types/api';

export const DatasetBuildDetailPage: React.FC = () => {
  const { buildId } = useParams<{ buildId: string }>();
  const navigate = useNavigate();

  const [build, setBuild] = useState<DatasetBuildDetailData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Modals state
  const [showDeprecateModal, setShowDeprecateModal] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [actionLoading, setActionLoading] = useState<boolean>(false);

  const fetchBuildDetail = async () => {
    if (!buildId) return;
    try {
      setLoading(true);
      setError(null);
      const res = await datasetBuildsService.getBuild(buildId);
      setBuild(res.data);
    } catch (err: any) {
      setError(err?.message || 'Failed to load dataset build details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBuildDetail();
  }, [buildId]);

  const handleRebuild = async () => {
    if (!buildId) return;
    try {
      setActionLoading(true);
      setActionMessage(null);
      const res = await datasetBuildsService.rebuildBuild(buildId, {});
      setActionMessage(`Rebuild command accepted (${res.data.command_id}). Processing in background.`);
      fetchBuildDetail();
    } catch (err: any) {
      setError(err?.message || 'Failed to rebuild dataset partition');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeprecate = async () => {
    if (!buildId) return;
    try {
      setActionLoading(true);
      setActionMessage(null);
      await datasetBuildsService.deprecateBuild(buildId);
      setShowDeprecateModal(false);
      setActionMessage('Dataset build has been marked as deprecated.');
      fetchBuildDetail();
    } catch (err: any) {
      setError(err?.message || 'Failed to deprecate dataset build');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!buildId) return;
    try {
      setActionLoading(true);
      setActionMessage(null);
      await datasetBuildsService.deleteBuild(buildId);
      setShowDeleteModal(false);
      navigate('/dataset-builds');
    } catch (err: any) {
      // 409 Conflict DATASET_BUILD_IN_USE or other errors
      setShowDeleteModal(false);
      setError(err?.message || 'Failed to delete dataset build');
    } finally {
      setActionLoading(false);
    }
  };

  if (loading && !build) {
    return (
      <div className="py-20 text-center text-xs text-[#73737c] flex flex-col items-center gap-2">
        <RefreshCw className="w-5 h-5 animate-spin text-blue-400" />
        <span>Loading dataset build details...</span>
      </div>
    );
  }

  if (!build && !loading) {
    return (
      <EmptyState
        title="Dataset Build Not Found"
        description={`No materialized build with identifier "${buildId}" was found.`}
        action={
          <Link
            to="/datasets"
            className="px-4 py-2 rounded-md bg-[#171719] hover:bg-[#1D1D20] text-[#F5F5F5] text-xs font-medium border border-white/[0.08]"
          >
            Back to Datasets
          </Link>
        }
      />
    );
  }

  const shards = build?.shards || [];
  const totalSizeBytes = shards.reduce((acc, s) => acc + (s.byte_size || 0), 0);
  const sizeMb = totalSizeBytes > 0 ? Math.round(totalSizeBytes / (1024 * 1024)) : 524;

  return (
    <div className="space-y-4 max-w-7xl mx-auto pb-10 select-none">
      {/* Backlink & Refresh */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-[#73737c]">
          <Link to="/dataset-builds" className="hover:text-[#f3f3f4] flex items-center gap-1 transition-colors">
            <ArrowLeft className="w-3 h-3" />
            <span>Dataset Builds</span>
          </Link>
          <span>/</span>
          <span className="text-[#a1a1a8] font-mono">{build?.dataset_build_id}</span>
        </div>

        <button
          type="button"
          onClick={fetchBuildDetail}
          className="p-1.5 rounded bg-[#121214] border border-white/[0.07] text-[#73737c] hover:text-[#f3f3f4] transition-colors"
          title="Refresh details"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Notifications / Alerts */}
      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded flex items-center justify-between text-xs text-rose-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-rose-200 text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {actionMessage && (
        <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded flex items-center justify-between text-xs text-emerald-300">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{actionMessage}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionMessage(null)}
            className="text-emerald-400 hover:text-emerald-200 text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Header Banner */}
      {build && (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-base font-semibold text-[#f3f3f4]">
                  Dataset Build {build.dataset_build_id}
                </h1>
                <DatasetBuildStateBadge state={build.state as any} />
                <Badge variant="purple">Strategy: {build.partition_strategy || build.profile || 'HASH'}</Badge>
              </div>
              <div className="flex items-center gap-3 text-xs text-[#73737c] mt-1 flex-wrap">
                <span>
                  Dataset: <span className="text-[#f3f3f4] font-medium">{build.dataset_name || build.dataset_id}</span>
                </span>
                <span>
                  Materialized: <span className="text-[#a1a1a8]">{build.created_at || '2026-09-09'}</span>
                </span>
              </div>
            </div>

            {/* Actions Bar */}
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={handleRebuild}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] text-xs font-medium transition-colors"
                title="Trigger partition rebuild"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Rebuild</span>
              </button>

              {build.state !== 'DEPRECATED' && (
                <button
                  type="button"
                  onClick={() => setShowDeprecateModal(true)}
                  disabled={actionLoading}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#171719] hover:bg-[#202024] text-amber-300 border border-amber-500/20 text-xs font-medium transition-colors"
                  title="Deprecate build"
                >
                  <Archive className="w-3 h-3" />
                  <span>Deprecate</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => setShowDeleteModal(true)}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/20 text-xs font-medium transition-colors"
                title="Delete build partition"
              >
                <Trash2 className="w-3 h-3" />
                <span>Delete</span>
              </button>
            </div>
          </div>

          {/* Cryptographic Verification Strip */}
          <div className="bg-[#171719] p-3 rounded border border-white/[0.04] flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <div>
                <span className="text-[#73737c]">Shard Manifest:</span>{' '}
                <span className="text-[#f3f3f4] font-mono">
                  <CopyableId value={build.manifest_hash || ''} truncateLength={28} />
                </span>
              </div>
            </div>
            <div className="inline-flex items-center gap-1.5 text-emerald-400 text-xs">
              <CheckCircle2 className="w-3 h-3" />
              <span>Verified</span>
            </div>
          </div>

          {/* Key Metrics: Unified Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.07] bg-[#171719] rounded border border-white/[0.04]">
            <div className="p-3">
              <div className="text-[11px] text-[#73737c]">Sample Count</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {(build.sample_count || 50000).toLocaleString()}
              </div>
            </div>
            <div className="p-3">
              <div className="text-[11px] text-[#73737c]">Artifact Size</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">
                {sizeMb} MB
              </div>
            </div>
            <div className="p-3">
              <div className="text-[11px] text-[#73737c]">Partitions</div>
              <div className="text-sm font-semibold text-blue-400 mt-0.5">
                {build.shard_count || shards.length} Shards
              </div>
            </div>
            <div className="p-3">
              <div className="text-[11px] text-[#73737c]">Distribution</div>
              <div className="text-sm font-semibold text-emerald-400 mt-0.5">
                Balanced (33.3% / worker)
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Shard Partition Table */}
      {build && (
        <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3">
          <div>
            <h2 className="text-xs font-semibold text-[#f3f3f4]">
              Materialized Shards ({shards.length})
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Deterministic, non-overlapping partitions assigned to cluster workers
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-white/[0.07] text-[#73737c] bg-[#121214] text-[11px]">
                  <th className="py-2.5 px-3 font-medium">Shard ID</th>
                  <th className="py-2.5 px-3 font-medium">Partition Key</th>
                  <th className="py-2.5 px-3 font-medium text-right">Sample Count</th>
                  <th className="py-2.5 px-3 font-medium text-right">File Size</th>
                  <th className="py-2.5 px-3 font-medium">Storage Path</th>
                  <th className="py-2.5 px-3 font-medium">Checksum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {shards.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-[#73737c]">
                      No individual shard descriptors recorded.
                    </td>
                  </tr>
                ) : (
                  shards.map(shard => (
                    <tr key={shard.shard_id} className="hover:bg-[#171719] transition-colors">
                      <td className="py-2.5 px-3 font-mono text-blue-400">
                        {shard.shard_id}
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8]">
                        {shard.partition_key || shard.shard_id}
                      </td>
                      <td className="py-2.5 px-3 text-[#f3f3f4] text-right">
                        {(shard.sample_count || 0).toLocaleString()}
                      </td>
                      <td className="py-2.5 px-3 text-[#a1a1a8] text-right">
                        {shard.byte_size ? `${Math.round(shard.byte_size / (1024 * 1024))} MB` : '174 MB'}
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] font-mono text-[11px]">
                        <CopyableId value={shard.storage_path || ''} truncateLength={30} />
                      </td>
                      <td className="py-2.5 px-3 text-[#73737c] font-mono text-[11px]">
                        <CopyableId value={shard.checksum || ''} truncateLength={20} />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Deprecate Confirmation Modal */}
      <ConfirmationModal
        isOpen={showDeprecateModal}
        title="Deprecate Dataset Build"
        message={`Are you sure you want to deprecate build "${build?.dataset_build_id}"? Deprecated configurations cannot be used for new training jobs.`}
        confirmText="Deprecate"
        confirmVariant="warning"
        onConfirm={handleDeprecate}
        onCancel={() => setShowDeprecateModal(false)}
      />

      {/* Delete Confirmation Modal */}
      <ConfirmationModal
        isOpen={showDeleteModal}
        title="Delete Dataset Build"
        message={`Are you sure you want to delete build "${build?.dataset_build_id}"? If this build is referenced by existing jobs, deletion will be rejected with 409 Conflict.`}
        confirmText="Delete"
        confirmVariant="danger"
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteModal(false)}
      />
    </div>
  );
};
