import React, { useState } from 'react';
import { Drawer } from '../common/Drawer';
import {
  Attempt,
  TrainingStep,
  WorkerSession,
  DiagnosticEvent,
} from '../../types';
import { Copy, Check, Terminal, Server, Hash, ShieldCheck, Code, Layers } from 'lucide-react';
import { CopyableId } from '../common/CopyableId';
import { StepStateBadge } from '../common/Badge';

interface TechnicalDetailsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  attempt: Attempt;
  activeStep?: TrainingStep;
  workers: WorkerSession[];
  latestEvent?: DiagnosticEvent;
}

export const TechnicalDetailsDrawer: React.FC<TechnicalDetailsDrawerProps> = ({
  isOpen,
  onClose,
  attempt,
  activeStep,
  workers,
  latestEvent,
}) => {
  const [copiedSection, setCopiedSection] = useState<string | null>(null);

  const copyToClipboard = (text: string, section: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSection(section);
    setTimeout(() => setCopiedSection(null), 2000);
  };

  const rawStateJson = JSON.stringify(
    {
      attempt: {
        id: attempt.id,
        jobId: attempt.jobId,
        state: attempt.state,
        runtimeEventSeq: attempt.runtimeEventSeq,
        modelVersion: attempt.modelVersion,
        barrierWaitMs: attempt.barrierWaitMs,
      },
      currentStep: activeStep,
      workers: workers.map(w => ({
        workerId: w.workerId,
        sessionId: w.sessionId,
        state: w.state,
        protocolVersion: w.protocolVersion,
        shardId: w.shardId,
      })),
    },
    null,
    2
  );

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-blue-400" />
          <span>Execution Technical Details</span>
        </span>
      }
      subtitle={`Technical diagnostics & internal protocol state for Attempt`}
      widthClass="max-w-2xl"
      footer={
        <div className="flex items-center justify-between w-full text-xs">
          <span className="text-[#73737c] font-mono">
            Seq #{attempt.runtimeEventSeq} · DTP v1.3
          </span>
          <button
            type="button"
            onClick={() => copyToClipboard(rawStateJson, 'all')}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors"
          >
            {copiedSection === 'all' ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                <span>Copied Technical Snapshot</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy Technical Snapshot</span>
              </>
            )}
          </button>
        </div>
      }
    >
      <div className="space-y-6 font-sans">
        {/* Section 1: Internal Identifiers */}
        <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3 font-mono">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4] font-sans">
            <Hash className="w-3.5 h-3.5 text-blue-400" />
            <span>Internal Cluster Identifiers</span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
            <div className="text-[#73737c] font-sans">Attempt ID</div>
            <div className="text-[#f3f3f4]">
              <CopyableId value={attempt.id} truncateLength={24} />
            </div>

            <div className="text-[#73737c] font-sans">Job Specification ID</div>
            <div className="text-[#f3f3f4]">
              <CopyableId value={attempt.jobId} truncateLength={24} />
            </div>

            <div className="text-[#73737c] font-sans">Runtime Event Seq</div>
            <div className="text-[#f3f3f4]">#{attempt.runtimeEventSeq}</div>

            <div className="text-[#73737c] font-sans">Latest Checkpoint ID</div>
            <div className="text-[#f3f3f4]">
              <CopyableId value={attempt.latestCheckpointId || 'chk_none'} truncateLength={24} />
            </div>

            <div className="text-[#73737c] font-sans">Execution Mode</div>
            <div className="text-[#f3f3f4]">{attempt.executionMode}</div>

            <div className="text-[#73737c] font-sans">Model Output Version</div>
            <div className="text-blue-400 font-semibold">{attempt.modelVersion}</div>
          </div>
        </div>

        {/* Section 2: Worker DTP Sessions */}
        <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3 font-mono">
          <div className="flex items-center justify-between font-sans">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
              <Server className="w-3.5 h-3.5 text-emerald-400" />
              <span>Worker Session Details ({(workers || []).length})</span>
            </div>
            <span className="text-[10px] text-[#73737c]">DTP Protocol</span>
          </div>

          <div className="divide-y divide-white/[0.04]">
            {(workers || []).map(w => (
              <div key={w.workerId} className="py-2 flex items-center justify-between text-xs">
                <div>
                  <div className="text-[#f3f3f4] font-sans font-medium">Worker {w.workerId} ({w.nodeLabel})</div>
                  <div className="text-[11px] text-[#73737c]">
                    Session: <CopyableId value={w.sessionId} truncateLength={16} />
                  </div>
                </div>
                <div className="text-right text-[11px]">
                  <div className="text-[#a1a1a8]">{w.protocolVersion}</div>
                  <div className="text-emerald-400 font-sans">{w.state}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Section 3: Strict BSP Timing & Barrier */}
        {activeStep && (
          <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3 font-mono">
            <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4] font-sans">
              <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
              <span>Step State Machine &amp; Timings</span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
              <div className="text-[#73737c] font-sans">Canonical State</div>
              <div>
                <StepStateBadge state={activeStep.state} />
              </div>

              <div className="text-[#73737c] font-sans">Operation ID</div>
              <div className="text-[#f3f3f4]">#{activeStep.operationId}</div>

              <div className="text-[#73737c] font-sans">Barrier Wait Duration</div>
              <div className="text-[#f3f3f4]">{attempt.barrierWaitMs} ms</div>

              <div className="text-[#73737c] font-sans">Total Step Duration</div>
              <div className="text-[#f3f3f4]">{activeStep.timings.totalDurationMs || 420} ms</div>
            </div>
          </div>
        )}

        {/* Section 4: Raw Step JSON State */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs font-semibold text-[#f3f3f4]">
            <div className="flex items-center gap-1.5">
              <Code className="w-3.5 h-3.5 text-blue-400" />
              <span>Raw Internal State JSON</span>
            </div>
            <button
              type="button"
              onClick={() => copyToClipboard(rawStateJson, 'json')}
              className="text-blue-400 hover:text-blue-300 font-sans text-xs transition-colors"
            >
              {copiedSection === 'json' ? 'Copied' : 'Copy'}
            </button>
          </div>
          <div className="bg-[#101012] p-3.5 rounded-lg border border-white/[0.04] font-mono text-xs text-[#a1a1a8] max-h-56 overflow-y-auto">
            <pre className="text-[11px] leading-relaxed">{rawStateJson}</pre>
          </div>
        </div>
      </div>
    </Drawer>
  );
};
