import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  Play,
  Layers,
  Server,
  Database,
  ShieldCheck,
  Check,
  X,
  Save,
  Briefcase,
  ChevronRight,
  Plus,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { AttemptStateBadge, Badge } from '../components/common/Badge';
import { formatDiagnosticEvent, EventIconType } from '../utils/eventFormatter';
import { EventDetailDrawer } from '../components/drawers/EventDetailDrawer';
import { DiagnosticEvent } from '../types';
import { jobsService } from '../api';

export const OverviewPage: React.FC = () => {
  const {
    currentAttempt,
    workers,
    events,
    jobs,
    datasets,
    datasetBuilds,
    checkpoints,
    isRuntimeStale,
  } = useApp();

  const [realJobCount, setRealJobCount] = useState<number | null>(null);

  React.useEffect(() => {
    jobsService.listJobs({ limit: 100 })
      .then(res => setRealJobCount(res.data?.length ?? 0))
      .catch(() => {});
  }, []);

  const [inspectEvent, setInspectEvent] = useState<DiagnosticEvent | null>(null);


  const progressPercent = Math.min(
    100,
    Math.round(
      ((currentAttempt.epoch - 1) * currentAttempt.totalBatches +
        currentAttempt.currentBatch) /
        (currentAttempt.totalEpochs * currentAttempt.totalBatches) *
        100
    )
  );

  const isHealthy = !isRuntimeStale && currentAttempt.activeWorkers === currentAttempt.expectedWorkers;
  const isTrainingActive = currentAttempt.state === 'RUNNING';

  const renderStatusIcon = (type: EventIconType) => {
    switch (type) {
      case 'success':
        return <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />;
      case 'warning':
        return <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />;
      case 'error':
        return <span className="w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0" />;
      case 'normal':
      default:
        return <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 shrink-0" />;
    }
  };

  return (
    <div className="w-full space-y-8 pb-12 font-sans select-none">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[#f3f3f4]">
            Overview
          </h1>
          <p className="text-xs text-[#73737c] mt-0.5">
            Distributed cluster state and active training execution
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isTrainingActive && (
            <Link
              to="/live"
              className="px-3 py-1.5 rounded text-xs font-normal text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              Live training
            </Link>
          )}
          <Link
            to="/training/new"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New training</span>
          </Link>
        </div>
      </div>

      {/* Cluster Health Summary Row */}
      <div className="flex items-center justify-between py-2.5 px-3 bg-[#121214] rounded border border-white/[0.07] text-xs">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isHealthy ? 'bg-emerald-400' : 'bg-amber-400'}`} />
          <span className="text-[#f3f3f4] font-medium">
            {isHealthy ? 'Cluster operational' : 'Cluster attention needed'}
          </span>
          <span className="text-[#73737c]">·</span>
          <span className="text-[#a1a1a8]">
            {isHealthy
              ? 'All workers connected and synchronized under Strict BSP'
              : 'One or more workers delayed or waiting'}
          </span>
        </div>
        <Link to="/system" className="text-[#73737c] hover:text-[#f3f3f4] transition-colors text-xs">
          System details →
        </Link>
      </div>

      {/* Active Training Run Section OR Getting Started Guide */}
      {!isTrainingActive ? (
        <div className="p-6 bg-[#121214] border border-white/[0.07] rounded space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Start a training run
            </h2>
            <p className="text-xs text-[#73737c] mt-0.5">
              Follow three simple steps to launch deterministic distributed training across your worker cluster.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-1">
            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">1</span>
                <span>Choose a dataset</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Select verified training data and a partitioned dataset build.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">2</span>
                <span>Configure model & training</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Select a neural network architecture and set hyperparameters.
              </p>
            </div>

            <div className="p-3.5 bg-[#171719] rounded border border-white/[0.05] space-y-1">
              <div className="text-xs font-medium text-[#f3f3f4] flex items-center gap-2">
                <span className="w-4 h-4 rounded-full bg-white/[0.08] flex items-center justify-center text-[10px] text-[#f3f3f4]">3</span>
                <span>Start distributed training</span>
              </div>
              <p className="text-xs text-[#73737c] pl-6">
                Launch synchronized execution and monitor live progress.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 pt-1">
            <Link
              to="/training/new"
              className="px-3.5 py-1.5 rounded text-xs font-normal text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5 text-[#73737c]" />
              <span>Start configuration wizard</span>
            </Link>
            <Link
              to="/datasets"
              className="px-3.5 py-1.5 rounded text-xs text-[#a1a1a8] hover:text-[#f3f3f4] bg-[#171719] hover:bg-[#202024] border border-white/[0.07] transition-colors"
            >
              View datasets
            </Link>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.07] pb-2">
            <div className="flex items-center gap-3">
              <h2 className="text-sm font-semibold text-[#f3f3f4]">
                {currentAttempt.jobName || 'ResNet18 CIFAR-10'}
              </h2>
              <AttemptStateBadge state={currentAttempt.state} />
              <span className="text-xs text-[#73737c]">
                v{currentAttempt.modelVersion.replace('v', '') || '3264'}
              </span>
            </div>

            <Link
              to="/live"
              className="text-xs text-blue-400 hover:text-blue-300 font-normal inline-flex items-center gap-1 transition-colors"
            >
              <span>Open live view</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {/* Progress Bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[#73737c]">
                Epoch {currentAttempt.epoch} of {currentAttempt.totalEpochs} · Batch {currentAttempt.currentBatch} of {currentAttempt.totalBatches}
              </span>
              <span className="text-[#f3f3f4] font-medium">{progressPercent}%</span>
            </div>
            <div className="w-full bg-[#171719] rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-blue-600 h-full rounded-full transition-all duration-300"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Metrics Row (Flat, clean, no inner cards) */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 pt-2">
            <div>
              <div className="text-xs text-[#73737c]">Current Epoch</div>
              <div className="text-base font-semibold text-[#f3f3f4] mt-0.5">
                {currentAttempt.epoch} <span className="text-xs text-[#73737c] font-normal">/ {currentAttempt.totalEpochs}</span>
              </div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                Batch {currentAttempt.currentBatch} of {currentAttempt.totalBatches}
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Workers</div>
              <div className="text-base font-semibold text-[#f3f3f4] mt-0.5">
                {currentAttempt.activeWorkers} of {currentAttempt.expectedWorkers} Active
              </div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                Synchronized
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Synchronization</div>
              <div className="text-base font-semibold text-[#f3f3f4] mt-0.5">
                Strict BSP
              </div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                Barrier deterministic
              </div>
            </div>

            <div>
              <div className="text-xs text-[#73737c]">Elapsed Time</div>
              <div className="text-base font-semibold text-[#f3f3f4] mt-0.5">
                {currentAttempt.elapsedFormatted}
              </div>
              <div className="text-xs text-[#a1a1a8] mt-0.5">
                Checkpointing active
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Cluster Resources Quick Strip */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-[#f3f3f4]">
          Resources
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Link
            to="/jobs"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Training Jobs</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">{realJobCount !== null ? `${realJobCount} registered` : `${(jobs || []).length} registered`}</div>
            </div>

            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/datasets"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Datasets</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">{(datasets || []).length} datasets · {(datasetBuilds || []).length} builds</div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/checkpoints"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Checkpoints</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">{(checkpoints || []).length} saved snapshots</div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>

          <Link
            to="/system"
            className="p-3.5 rounded bg-[#121214] hover:bg-[#171719] border border-white/[0.07] transition-colors flex items-center justify-between group"
          >
            <div>
              <div className="text-xs text-[#73737c]">Cluster Nodes</div>
              <div className="text-sm font-semibold text-[#f3f3f4] mt-0.5">{(workers || []).length} worker nodes</div>
            </div>
            <ChevronRight className="w-4 h-4 text-[#73737c] group-hover:text-[#f3f3f4] transition-colors" />
          </Link>
        </div>
      </div>

      {/* Recent Activity Section (Flat List) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between border-b border-white/[0.07] pb-2">
          <div>
            <h2 className="text-sm font-semibold text-[#f3f3f4]">
              Recent Activity
            </h2>
          </div>
          <Link
            to="/live"
            className="text-xs text-blue-400 hover:text-blue-300 font-normal inline-flex items-center gap-1 transition-colors"
          >
            <span>Live stream</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="divide-y divide-white/[0.05]">
          {(events || []).slice(0, 5).map((evt, idx) => {
            const formatted = formatDiagnosticEvent(evt);
            const displayTime = evt.time && evt.time.length > 8 ? evt.time.slice(0, 8) : evt.time;

            return (
              <div
                key={`${evt.id}-${evt.runtimeSeq ?? idx}`}
                onClick={() => setInspectEvent(evt)}
                className="py-2 flex items-center justify-between text-xs hover:bg-white/[0.02] cursor-pointer transition-colors px-1"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {renderStatusIcon(formatted.iconType)}
                  <span className="text-[#f3f3f4] font-normal truncate">
                    {formatted.humanText}
                  </span>
                </div>

                <div className="text-[#73737c] text-xs shrink-0 pl-3">
                  {displayTime}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Event Inspect Drawer */}
      <EventDetailDrawer
        event={inspectEvent}
        onClose={() => setInspectEvent(null)}
      />
    </div>
  );
};
