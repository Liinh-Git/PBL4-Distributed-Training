import React from 'react';
import { Drawer } from '../common/Drawer';
import { WorkerSession } from '../../types';
import { WorkerStateBadge } from '../common/Badge';
import { Cpu } from 'lucide-react';

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
          <span>Thông tin Worker {worker.workerId}</span>
        </span>
      }
      subtitle={`Node: ${worker.nodeLabel}`}
      widthClass="max-w-xl"
    >
      <div className="space-y-6 font-sans">
        {/* Session State Banner */}
        <div className="p-4 bg-[#171719] rounded border border-white/[0.04] flex items-center justify-between text-xs">
          <div>
            <div className="text-[#73737c]">Trạng thái phiên</div>
            <div className="mt-1.5">
              <WorkerStateBadge state={worker.state} />
            </div>
          </div>
          <div className="text-right">
            <div className="text-[#73737c]">Node tính toán</div>
            <div className="text-xs font-semibold text-[#f3f3f4] mt-1.5">
              {worker.nodeLabel}
            </div>
          </div>
        </div>

        {/* Primary Identity & Protocol */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Thông tin kết nối &amp; Giao thức
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Worker ID</span>
              <span className="text-[#f3f3f4] font-semibold">{worker.workerId}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Phiên bản giao thức</span>
              <span className="text-blue-400 font-mono">{worker.protocolVersion}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Thời điểm kết nối</span>
              <span className="text-[#a1a1a8]">{worker.connectedAt}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Heartbeat gần nhất</span>
              <span className="text-emerald-400 font-mono">
                {worker.lastHeartbeatMs !== undefined
                  ? `${(worker.lastHeartbeatMs / 1000).toFixed(1)}s trước (${worker.lastHeartbeatMs} ms)`
                  : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Shard & Model Alignment */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Phân vùng dữ liệu &amp; Phiên bản mô hình
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Phân vùng Shard</span>
              <span className="text-blue-400 font-mono font-medium">
                {worker.shardId || worker.assignedShard || 'Chưa phân vùng'}
              </span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Phiên bản tham số cục bộ</span>
              <span className="text-[#f3f3f4] font-mono font-medium">
                {worker.localModelVersion || worker.currentModelVersion ? `v${worker.localModelVersion || worker.currentModelVersion}` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Health & Failure Code */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Tình trạng phiên &amp; Chẩn đoán
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Các phiên trước đó</span>
              <span className="text-[#a1a1a8]">
                {(worker.previousSessions || worker.historicalSessions || []).length > 0
                  ? (worker.previousSessions || worker.historicalSessions)!.join(', ')
                  : 'Không có (Phiên đầu tiên)'}
              </span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Tình trạng hoạt động</span>
              <span>
                {worker.failureCode ? (
                  <span className="text-rose-400 font-mono font-semibold">{worker.failureCode}</span>
                ) : (
                  <span className="text-emerald-400 font-medium">BÌNH THƯỜNG (0 lần ngắt kết nối)</span>
                )}
              </span>
            </div>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
