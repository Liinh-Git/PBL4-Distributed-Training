import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Drawer } from '../common/Drawer';
import { DatasetBuild, Dataset } from '../../types';
import { DatasetBuildStateBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { ChevronDown, Play } from 'lucide-react';

export function getConfigurationDisplayName(build: DatasetBuild): string {
  if (build.state === 'DEPRECATED') return 'Deprecated configuration';
  if (build.batchSize >= 128) return 'Large batch';
  if (build.batchSize === 64) return 'Standard';
  return `Batch ${build.batchSize}`;
}

export function getConfigurationDescription(build: DatasetBuild): string {
  if (build.state === 'DEPRECATED') return 'Superseded legacy partition split. Retained for reproducible benchmark historical runs.';
  if (build.batchSize >= 128) return 'Optimized for high-throughput distributed training with larger per-worker batch allocation.';
  if (build.batchSize === 64) return 'Balanced standard configuration recommended for typical convergence stability.';
  return `Custom partition split with batch size ${build.batchSize}.`;
}

interface TrainingConfigurationDrawerProps {
  build: DatasetBuild | null;
  dataset: Dataset;
  isOpen: boolean;
  onClose: () => void;
}

export const TrainingConfigurationDrawer: React.FC<TrainingConfigurationDrawerProps> = ({
  build,
  dataset,
  isOpen,
  onClose,
}) => {
  const navigate = useNavigate();
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  if (!build) return null;

  const configName = getConfigurationDisplayName(build);
  const isReady = build.state === 'READY';
  const partitionCount = build.shardCount || build.shards?.length || 3;
  const totalSamples = build.totalSamples || build.sampleCount || 50000;

  const handleUseForTraining = () => {
    navigate(`/training/new?datasetId=${dataset.id}&buildId=${build.id}`);
    onClose();
  };

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={configName}
      subtitle={`${dataset.name} configuration`}
      widthClass="max-w-md"
    >
      <div className="space-y-5 font-sans select-none text-xs">
        {/* Status header */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Status</span>
          <DatasetBuildStateBadge state={build.state} />
        </div>

        {/* Primary Operational Information */}
        <div className="space-y-3 pb-3 border-b border-white/[0.07]">
          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Configuration</span>
            <span className="text-[#f3f3f4] font-medium">{configName}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Batch size</span>
            <span className="text-[#f3f3f4] font-medium">{build.batchSize} samples</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Data partitions</span>
            <span className="text-[#f3f3f4] font-medium">{partitionCount} partitions</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Total samples</span>
            <span className="text-[#f3f3f4] font-medium">{totalSamples.toLocaleString()}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[#73737c]">Created</span>
            <span className="text-[#f3f3f4]">
              {build.createdAt ? build.createdAt.slice(0, 10) : '2026-09-08'}
            </span>
          </div>
        </div>

        {/* Brief Human-readable description */}
        <div className="pb-3 border-b border-white/[0.07]">
          <p className="text-[#73737c] leading-relaxed">
            {getConfigurationDescription(build)}
          </p>
        </div>

        {/* Primary Action */}
        {isReady && (
          <div className="pt-1">
            <button
              type="button"
              onClick={handleUseForTraining}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>Use for training</span>
            </button>
          </div>
        )}

        {/* Collapsed Technical Details */}
        <div className="pt-2">
          <button
            type="button"
            onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            className="w-full flex items-center justify-between text-left text-xs text-[#73737c] hover:text-[#f3f3f4] transition-colors py-1"
          >
            <span>Technical details</span>
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${
                showTechnicalDetails ? 'rotate-180' : ''
              }`}
            />
          </button>

          {showTechnicalDetails && (
            <div className="mt-2.5 p-3 bg-[#171719] rounded border border-white/[0.04] space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">dataset_build_id</span>
                <CopyableId value={build.id} />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">profile</span>
                <span className="font-mono text-[11px] text-[#a1a1a8]">
                  {build.profile || 'standard-sharded-fp32'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">shard_count</span>
                <span className="font-mono text-[11px] text-[#a1a1a8]">{partitionCount}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">partition_seed</span>
                <span className="font-mono text-[11px] text-[#a1a1a8]">
                  {build.partitionSeed || 42}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">manifest URI</span>
                <span className="font-mono text-[11px] text-[#a1a1a8] truncate max-w-[200px]">
                  {`/shards/${build.id}/manifest.json`}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">manifest hash</span>
                <CopyableId
                  value={
                    build.manifestHash ||
                    build.datasetManifestHash ||
                    '0x3344bb1190aaeff871238990172c'
                  }
                />
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">input shape</span>
                <span className="font-mono text-[11px] text-[#a1a1a8]">
                  {build.manifest?.inputShape || '[3, 32, 32]'}
                </span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">data type</span>
                <span className="font-mono text-[11px] text-[#a1a1a8]">
                  {build.manifest?.dtype || 'FLOAT32'}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </Drawer>
  );
};
