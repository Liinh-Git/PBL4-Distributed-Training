import React from 'react';
import { Drawer } from '../common/Drawer';
import { WorkerSession } from '../../types';
import { CopyableId } from '../common/CopyableId';
import { WorkerStateBadge, Badge } from '../common/Badge';
import { Cpu, Server, Clock, AlertCircle, CheckCircle2 } from 'lucide-react';

interface WorkerDetailDrawerProps {
  worker: WorkerSession | null;
  onClose: () => void;
}

export const WorkerDetailDrawer: React.FC<WorkerDetailDrawerProps> = ({
  worker,
  onClose,
}) => {
  if (!worker) return null;

  return (
    <Drawer
      isOpen={!!worker}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-blue-400" />
          <span>Worker {worker.workerId} Inspector</span>
        </span>
      }
      subtitle={`Session: ${worker.sessionId}`}
      widthClass="max-w-xl"
    >
      <div className="space-y-6 font-sans">
        {/* Session State Banner */}
        <div className="p-4 bg-[#171719] rounded-lg border border-white/[0.04] flex items-center justify-between text-xs">
          <div>
            <div className="text-[#73737c]">Current Session State</div>
            <div className="mt-1.5">
              <WorkerStateBadge state={worker.state} />
            </div>
          </div>
          <div className="text-right">
            <div className="text-[#73737c]">Assigned Compute Node</div>
            <div className="text-xs font-semibold text-[#f3f3f4] mt-1.5">
              {worker.nodeLabel}
            </div>
          </div>
        </div>

        {/* Primary Identity & Protocol */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Identity &amp; Protocol
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Worker ID</span>
              <span className="text-[#f3f3f4] font-semibold">{worker.workerId}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Session ID</span>
              <CopyableId value={worker.sessionId} truncateLength={22} />
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Protocol Version</span>
              <span className="text-blue-400 font-mono">{worker.protocolVersion}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Connected Timestamp</span>
              <span className="text-[#a1a1a8]">{worker.connectedAt}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Last Heartbeat</span>
              <span className="text-emerald-400 font-mono">
                {worker.lastHeartbeatMs !== undefined
                  ? `${(worker.lastHeartbeatMs / 1000).toFixed(1)}s ago (${worker.lastHeartbeatMs} ms)`
                  : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Shard & Model Alignment */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Partition &amp; Model Version Alignment
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Assigned Shard Partition</span>
              <span className="text-blue-400 font-mono font-medium">
                {worker.shardId || worker.assignedShard || 'Unassigned'}
              </span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Local Parameter Version</span>
              <span className="text-[#f3f3f4] font-mono font-medium">
                {worker.localModelVersion || worker.currentModelVersion ? `v${worker.localModelVersion || worker.currentModelVersion}` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Health & Failure Code */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Session Health &amp; Diagnostics
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Historical Sessions</span>
              <span className="text-[#a1a1a8]">
                {(worker.previousSessions || worker.historicalSessions || []).length > 0
                  ? (worker.previousSessions || worker.historicalSessions)!.join(', ')
                  : 'None (Initial active session)'}
              </span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Status Condition</span>
              <span>
                {worker.failureCode ? (
                  <span className="text-rose-400 font-mono font-semibold">{worker.failureCode}</span>
                ) : (
                  <span className="text-emerald-400 font-medium">HEALTHY (Zero Disconnects)</span>
                )}
              </span>
            </div>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
