import React from 'react';
import { Drawer } from '../common/Drawer';
import { DiagnosticEvent } from '../../types';
import { SeverityBadge } from '../common/Badge';
import { CopyableId } from '../common/CopyableId';
import { Activity, Code, Clock, Layers } from 'lucide-react';

interface EventDetailDrawerProps {
  event: DiagnosticEvent | null;
  onClose: () => void;
}

export const EventDetailDrawer: React.FC<EventDetailDrawerProps> = ({
  event,
  onClose,
}) => {
  if (!event) return null;

  return (
    <Drawer
      isOpen={!!event}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <span>Diagnostic Event Detail</span>
        </span>
      }
      subtitle={`Seq #${event.runtimeSeq} • ${event.event}`}
      widthClass="max-w-xl"
    >
      <div className="space-y-6 font-sans">
        {/* Severity & Sequence Card */}
        <div className="p-4 bg-[#171719] rounded-lg border border-white/[0.04] flex items-center justify-between text-xs">
          <div>
            <div className="text-[#73737c]">Severity Level</div>
            <div className="mt-1.5">
              <SeverityBadge severity={event.severity} />
            </div>
          </div>
          <div className="text-right">
            <div className="text-[#73737c]">Runtime Sequence</div>
            <div className="font-semibold text-[#f3f3f4] font-mono text-sm mt-1">
              #{event.runtimeSeq}
            </div>
          </div>
        </div>

        {/* Source & Correlation Details */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4]">
            Source &amp; Correlation Metadata
          </h3>
          <div className="divide-y divide-white/[0.04] text-xs bg-[#171719] rounded-lg border border-white/[0.04] p-3">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Event Name</span>
              <span className="text-[#f3f3f4] font-medium">{event.event}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Scope</span>
              <span className="text-blue-400 font-mono">{event.scope}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Source Daemon</span>
              <span className="text-[#a1a1a8]">{event.source}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Timestamp</span>
              <span className="text-[#a1a1a8]">{event.time}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Attempt ID</span>
              <CopyableId value={event.attemptId} truncateLength={18} />
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#73737c]">Technical Correlation ID</span>
              <CopyableId value={event.technicalCorrelationId} truncateLength={22} />
            </div>
          </div>
        </div>

        {/* Structured Semantic Payload */}
        <div className="space-y-3">
          <h3 className="text-xs font-semibold text-[#f3f3f4] flex items-center gap-2">
            <Code className="w-3.5 h-3.5 text-[#a1a1a8]" />
            <span>Structured Payload</span>
          </h3>
          <div className="p-3.5 bg-[#171719] rounded-lg border border-white/[0.04] font-mono text-xs text-[#a1a1a8] overflow-x-auto">
            <pre className="text-[11px] leading-relaxed">{JSON.stringify(event.payload, null, 2)}</pre>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
