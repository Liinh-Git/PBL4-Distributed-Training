import React, { useState } from 'react';
import { Drawer } from '../common/Drawer';
import { Job } from '../../types';
import { Copy, Check, FileCode, ChevronDown, ChevronRight, Sliders, Database, Cpu, Activity, ShieldCheck, Save, Server } from 'lucide-react';

interface RawContractDrawerProps {
  job: Job | null;
  onClose: () => void;
}

export const RawContractDrawer: React.FC<RawContractDrawerProps> = ({
  job,
  onClose,
}) => {
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'summary' | 'raw'>('summary');
  const [isTechnicalExpanded, setIsTechnicalExpanded] = useState(false);

  if (!job) return null;

  const resolved = job.resolvedContract;
  const jsonString = JSON.stringify(resolved, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Drawer
      isOpen={!!job}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <Sliders className="w-4 h-4 text-blue-400" />
          <span>Job Configuration Specification</span>
        </span>
      }
      subtitle={job.name}
      widthClass="max-w-2xl"
      footer={
        <div className="flex items-center justify-between w-full text-xs">
          <button
            type="button"
            onClick={() => setActiveTab(activeTab === 'summary' ? 'raw' : 'summary')}
            className="text-blue-400 hover:text-blue-300 font-medium transition-colors"
          >
            {activeTab === 'summary' ? 'View raw configuration JSON' : 'View configuration summary'}
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[#171719] hover:bg-[#202024] text-[#f3f3f4] border border-white/[0.07] transition-colors"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-400" />
                <span>Copied JSON</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>Copy JSON</span>
              </>
            )}
          </button>
        </div>
      }
    >
      <div className="space-y-6 font-sans">
        {/* Toggle Switch */}
        <div className="flex items-center gap-1 p-1 bg-[#171719] rounded-lg border border-white/[0.04] text-xs">
          <button
            type="button"
            onClick={() => setActiveTab('summary')}
            className={`flex-1 py-1.5 px-3 rounded-md transition-all font-medium ${
              activeTab === 'summary'
                ? 'bg-white/[0.1] text-[#f3f3f4] shadow-xs'
                : 'text-[#73737c] hover:text-[#a1a1a8]'
            }`}
          >
            Configuration Summary
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('raw')}
            className={`flex-1 py-1.5 px-3 rounded-md transition-all font-medium ${
              activeTab === 'raw'
                ? 'bg-white/[0.1] text-[#f3f3f4] shadow-xs'
                : 'text-[#73737c] hover:text-[#a1a1a8]'
            }`}
          >
            Raw Configuration JSON
          </button>
        </div>

        {/* VIEW 1: READABLE CONFIGURATION SUMMARY */}
        {activeTab === 'summary' && (
          <div className="space-y-5">
            {/* Section 1: Dataset */}
            <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
                <Database className="w-3.5 h-3.5 text-blue-400" />
                <span>Dataset</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="text-[#73737c]">Dataset Name</div>
                <div className="text-[#f3f3f4] font-medium">{job.datasetName}</div>

                <div className="text-[#73737c]">Input Shape</div>
                <div className="text-[#f3f3f4] font-mono">{resolved?.dataset?.inputShape || '32 × 32 × 3'}</div>

                <div className="text-[#73737c]">Data Type</div>
                <div className="text-[#f3f3f4] font-medium">{resolved?.dataset?.dtype || 'FP32'}</div>

                <div className="text-[#73737c]">Classes</div>
                <div className="text-[#f3f3f4]">{resolved?.dataset?.numClasses || 10}</div>

                <div className="text-[#73737c]">Batch Size</div>
                <div className="text-[#f3f3f4]">{resolved?.dataset?.batchSize || 64} per worker</div>

                <div className="text-[#73737c]">Shards</div>
                <div className="text-[#f3f3f4]">{resolved?.dataset?.shardCount || 3} deterministic partitions</div>
              </div>
            </div>

            {/* Section 2: Model */}
            <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
                <Cpu className="w-3.5 h-3.5 text-blue-400" />
                <span>Model Architecture</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="text-[#73737c]">Model Architecture</div>
                <div className="text-[#f3f3f4] font-medium">{resolved?.model?.modelId || 'ResNet-18'}</div>

                <div className="text-[#73737c]">Profile</div>
                <div className="text-[#a1a1a8] leading-snug">{resolved?.model?.modelProfile || 'Standard ResNet Vision Architecture'}</div>
              </div>
            </div>

            {/* Section 3: Training Hyperparameters */}
            <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
                <Activity className="w-3.5 h-3.5 text-emerald-400" />
                <span>Training Parameters</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="text-[#73737c]">Epochs</div>
                <div className="text-[#f3f3f4] font-semibold">{resolved?.training?.epochs || 20}</div>

                <div className="text-[#73737c]">Learning Rate</div>
                <div className="text-[#f3f3f4] font-mono">{resolved?.training?.learningRate || 0.01}</div>

                <div className="text-[#73737c]">Random Seed</div>
                <div className="text-[#f3f3f4] font-mono">{resolved?.training?.seed || 42}</div>
              </div>
            </div>

            {/* Section 4: Distributed Training */}
            <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
                <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
                <span>Distributed Training</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="text-[#73737c]">Synchronization Strategy</div>
                <div className="text-[#f3f3f4] font-medium">Strict BSP</div>

                <div className="text-[#73737c]">Expected Workers</div>
                <div className="text-[#f3f3f4]">{resolved?.synchronization?.expectedWorkers || 3} worker nodes</div>
              </div>
            </div>

            {/* Section 5: Checkpoint Durability */}
            <div className="bg-[#171719] border border-white/[0.04] rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#f3f3f4]">
                <Save className="w-3.5 h-3.5 text-amber-400" />
                <span>Checkpoint Policy</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div className="text-[#73737c]">Save Trigger</div>
                <div className="text-[#f3f3f4] font-medium">{resolved?.durability?.checkpointPolicy || 'On epoch end & periodic steps'}</div>

                <div className="text-[#73737c]">Retention Count</div>
                <div className="text-[#f3f3f4]">{resolved?.durability?.retentionCount || 10} snapshots</div>
              </div>
            </div>

            {/* Section 6: Technical Details (Default Collapsed) */}
            <div className="bg-[#141417] border border-white/[0.04] rounded-lg overflow-hidden">
              <button
                type="button"
                onClick={() => setIsTechnicalExpanded(!isTechnicalExpanded)}
                className="w-full px-4 py-3 flex items-center justify-between text-xs font-medium text-[#a1a1a8] hover:text-[#f3f3f4] transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Server className="w-3.5 h-3.5 text-[#73737c]" />
                  <span>Technical &amp; Protocol Specifications</span>
                </div>
                {isTechnicalExpanded ? (
                  <ChevronDown className="w-3.5 h-3.5 text-[#73737c]" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-[#73737c]" />
                )}
              </button>

              {isTechnicalExpanded && (
                <div className="px-4 pb-4 pt-1 border-t border-white/[0.04] grid grid-cols-2 gap-x-4 gap-y-2 text-xs font-mono">
                  <div className="text-[#73737c]">DTP Version</div>
                  <div className="text-[#a1a1a8]">{resolved?.protocol?.dtpVersion || 'dtp/v1.3'}</div>

                  <div className="text-[#73737c]">MCP Version</div>
                  <div className="text-[#a1a1a8]">{resolved?.protocol?.mcpVersion || 'mcp/v1.8'}</div>

                  <div className="text-[#73737c]">Contract Hash</div>
                  <div className="text-[#a1a1a8] truncate" title={resolved?.contractHash}>
                    {resolved?.contractHash || '0x77c2aa00ff8126749102837bcda81923'}
                  </div>

                  <div className="text-[#73737c]">Dataset Build ID</div>
                  <div className="text-[#a1a1a8]">{job.datasetBuildId}</div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* VIEW 2: RAW JSON (Available on request) */}
        {activeTab === 'raw' && (
          <div className="bg-[#171719] p-4 rounded-lg border border-white/[0.04] font-mono text-xs text-[#a1a1a8] overflow-x-auto leading-relaxed">
            <pre className="text-[11px]">{jsonString}</pre>
          </div>
        )}
      </div>
    </Drawer>
  );
};
