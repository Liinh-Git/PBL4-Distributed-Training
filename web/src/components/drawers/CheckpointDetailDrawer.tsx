import React, { useState, useEffect } from 'react';
import { Drawer } from '../common/Drawer';
import { Checkpoint } from '../../types';
import { CheckpointStateBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { ChevronDown, RotateCcw, RefreshCw } from 'lucide-react';
import { checkpointsService } from '../../api';
import { CheckpointDetailData } from '../../types/api';

interface CheckpointDetailDrawerProps {
  checkpoint: Checkpoint | null;
  onClose: () => void;
  onResume?: (checkpoint: Checkpoint) => void;
}

export const CheckpointDetailDrawer: React.FC<CheckpointDetailDrawerProps> = ({
  checkpoint,
  onClose,
  onResume,
}) => {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [detailData, setDetailData] = useState<CheckpointDetailData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!checkpoint?.id) {
      setDetailData(null);
      return;
    }

    const loadDetail = async () => {
      try {
        setLoading(true);
        const res = await checkpointsService.getCheckpoint(checkpoint.id);
        setDetailData(res.data);
      } catch {
        // Fallback to initial checkpoint props
      } finally {
        setLoading(false);
      }
    };

    loadDetail();
  }, [checkpoint?.id]);

  if (!checkpoint) return null;

  const isComplete = (detailData?.state || checkpoint.state) === 'COMPLETE';
  const sourceStep = detailData?.lineage?.source_step ?? checkpoint.lineage?.sourceStep ?? 3200;

  return (
    <Drawer
      isOpen={!!checkpoint}
      onClose={onClose}
      title={`Checkpoint at Step ${sourceStep}`}
      subtitle={checkpoint.jobName}
      widthClass="max-w-md"
    >
      <div className="space-y-5 font-sans select-none text-xs">
        {/* Header summary: State */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Status</span>
          <CheckpointStateBadge state={checkpoint.state} />
        </div>

        {/* Resume from section */}
        <div className="space-y-2 pb-3 border-b border-white/[0.07]">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Resume from
          </h3>
          <div className="space-y-1.5 pt-1">
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Epoch</span>
              <span className="text-[#f3f3f4] font-medium">
                {checkpoint.recovery?.epoch ?? 4}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Next batch</span>
              <span className="text-[#f3f3f4] font-medium">
                {checkpoint.recovery?.nextBatchOrdinal ?? 74}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[#73737c]">Model version</span>
              <span className="text-[#f3f3f4] font-medium">
                {checkpoint.modelVersion || String(sourceStep)}
              </span>
            </div>
          </div>
        </div>

        {/* Created date */}
        <div className="flex items-center justify-between pb-3 border-b border-white/[0.07]">
          <span className="text-[#73737c]">Created</span>
          <span className="text-[#f3f3f4]">
            {checkpoint.createdAt ? checkpoint.createdAt.slice(0, 16).replace('T', ', ') : 'Sep 9, 22:25'}
          </span>
        </div>

        {/* Action Button: Resume training */}
        {isComplete && (
          <div className="pt-1">
            <button
              type="button"
              onClick={() => {
                onResume?.(checkpoint);
                onClose();
              }}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-medium rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Resume training</span>
            </button>
          </div>
        )}

        {/* Collapsed Technical details */}
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
                <span className="text-[#73737c]">Checkpoint ID</span>
                <CopyableId value={checkpoint.id} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Created by attempt</span>
                <CopyableId value={checkpoint.lineage?.createdByAttempt} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Dataset build reference</span>
                <CopyableId value={checkpoint.lineage?.datasetBuildId} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Contract hash</span>
                <CopyableId value={checkpoint.integrity?.contractHash} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Manifest hash</span>
                <CopyableId value={checkpoint.integrity?.manifestHash} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Model SHA-256</span>
                <CopyableId value={checkpoint.integrity?.modelSha256} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Artifact size</span>
                <span className="text-[#f3f3f4]">
                  {checkpoint.sizeMb || 142} MB ({(checkpoint.integrity?.artifactSizeBytes || 148897792).toLocaleString()} bytes)
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </Drawer>
  );
};
