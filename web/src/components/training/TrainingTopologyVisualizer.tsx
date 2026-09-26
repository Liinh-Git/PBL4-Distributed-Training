import React, { useMemo, useState, useEffect } from 'react';
import {
  Server as ServerIcon,
  ShieldCheck,
  CheckCircle2,
  HardDrive,
  Activity,
  Radio,
  Wifi,
} from 'lucide-react';
import { TrainingStep, WorkerSession, Attempt } from '../../types';
import { StrategyStateStrictBSPData } from '../../types/api';

export interface TrainingTopologyVisualizerProps {
  currentStep?: TrainingStep | null;
  workers: WorkerSession[];
  expectedWorkers: number;
  attempt?: Attempt | null;
  strategyState?: StrategyStateStrictBSPData | null;
  isStale?: boolean;
  isSimulating?: boolean;
  onToggleSimulating?: () => void;
  onSelectWorker?: (worker: WorkerSession) => void;
  onOpenServerDetails?: () => void;
}

interface NodeCoord {
  x: number;
  y: number;
  cardWidth: number;
  cardHeight: number;
}

interface TopologyLayout {
  serverCoord: { x: number; y: number; width: number; height: number };
  workerCoords: NodeCoord[];
}

/**
 * Dynamically computes balanced 2D coordinates for Parameter Server and N Workers.
 * Ensures zero vertical or horizontal collisions on 1000 x 580 canvas.
 */
function getTopologyLayout(count: number): TopologyLayout {
  const serverWidth = 240;
  const serverHeight = 145;
  const monitorWidth = 220;
  const monitorHeight = 135;

  if (count <= 0) {
    return {
      serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
      workerCoords: [],
    };
  }

  if (count === 1) {
    // 1 Worker: Beautiful horizontal pipeline (Worker on left, Parameter Server on right)
    // Completely eliminates vertical stacking collision!
    return {
      serverCoord: { x: 670, y: 280, width: serverWidth, height: serverHeight },
      workerCoords: [
        { x: 260, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
      ],
    };
  }

  if (count === 2) {
    // 2 Workers: Symmetric horizontal pipeline (Worker 0 on Left, Server in Center, Worker 1 on Right)
    return {
      serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
      workerCoords: [
        { x: 190, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
        { x: 810, y: 280, cardWidth: monitorWidth, cardHeight: monitorHeight },
      ],
    };
  }

  if (count === 3) {
    // 3 Workers: Balanced triangular topology
    // W0: Top-Left (200, 130)
    // W1: Top-Right (800, 130)
    // Server: Center (500, 275)
    // W2: Bottom-Center (500, 480) -> Gap of 70px from server bottom (347px) to W2 top (412px)!
    return {
      serverCoord: { x: 500, y: 275, width: serverWidth, height: serverHeight },
      workerCoords: [
        { x: 200, y: 130, cardWidth: monitorWidth, cardHeight: monitorHeight },
        { x: 800, y: 130, cardWidth: monitorWidth, cardHeight: monitorHeight },
        { x: 500, y: 480, cardWidth: monitorWidth, cardHeight: monitorHeight },
      ],
    };
  }

  if (count === 4) {
    // 4 Workers: 4 corners around central server
    return {
      serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
      workerCoords: [
        { x: 200, y: 130, cardWidth: 200, cardHeight: 125 },
        { x: 800, y: 130, cardWidth: 200, cardHeight: 125 },
        { x: 200, y: 440, cardWidth: 200, cardHeight: 125 },
        { x: 800, y: 440, cardWidth: 200, cardHeight: 125 },
      ],
    };
  }

  // N >= 5: Adaptive radial distribution around central server
  const rx = 350;
  const ry = 190;
  const cardW = count <= 6 ? 180 : 150;
  const cardH = count <= 6 ? 115 : 100;

  const coords: NodeCoord[] = [];
  for (let i = 0; i < count; i++) {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / count;
    coords.push({
      x: Math.round(500 + rx * Math.cos(angle)),
      y: Math.round(280 + ry * Math.sin(angle)),
      cardWidth: cardW,
      cardHeight: cardH,
    });
  }

  return {
    serverCoord: { x: 500, y: 280, width: serverWidth, height: serverHeight },
    workerCoords: coords,
  };
}

/**
 * Computes visible link endpoints (x1, y1) and (x2, y2) between outer edges
 * of worker monitor and server rack chassis.
 */
function computeLinkEndpoints(
  wx: number,
  wy: number,
  wWidth: number,
  wHeight: number,
  sx: number,
  sy: number,
  sWidth: number,
  sHeight: number
) {
  const dx = sx - wx;
  const dy = sy - wy;
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist === 0) return { x1: wx, y1: wy, x2: sx, y2: sy };

  // Offset cleanly past the boundaries
  const wRadius = Math.min(wWidth, wHeight) / 2 + 4;
  const sRadius = Math.min(sWidth, sHeight) / 2 + 6;

  const x1 = Math.round(wx + (dx / dist) * wRadius);
  const y1 = Math.round(wy + (dy / dist) * wRadius);
  const x2 = Math.round(sx - (dx / dist) * sRadius);
  const y2 = Math.round(sy - (dy / dist) * sRadius);

  return { x1, y1, x2, y2 };
}

export const TrainingTopologyVisualizer: React.FC<TrainingTopologyVisualizerProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  attempt,
  strategyState,
  isStale = false,
  onSelectWorker,
  onOpenServerDetails,
}) => {
  const [showMetricsHud, setShowMetricsHud] = useState<boolean>(true);

  // Accessibility: detect prefers-reduced-motion
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mediaQuery.matches);
    const handler = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const observedWorkersCount = workers.length;
  const isPartialProjection = expectedWorkers > 0 && observedWorkersCount < expectedWorkers;

  // Real step state derived strictly from currentStep
  const stepState = currentStep?.state;
  const isCollecting = stepState === 'COLLECTING_GRADIENTS';
  const isUpdating = stepState === 'AGGREGATING' || stepState === 'UPDATING';
  const isBroadcasting = stepState === 'BROADCASTING' || stepState === 'WAITING_PARAMETER_APPLIED';
  const isCommitted = stepState === 'COMMITTED';

  // Authoritative barrier sync counts from strategy_state or currentStep
  const contributions = currentStep?.workerContributions || [];
  const acceptedCount = strategyState?.accepted_contribution_count ?? (
    contributions.length > 0
      ? contributions.filter(c => c.contributionAccepted).length
      : null
  );
  const expectedCount = strategyState?.expected_contribution_count ?? (
    expectedWorkers > 0 ? expectedWorkers : null
  );
  const isSyncComplete = strategyState?.synchronization_complete ?? (isCommitted);

  // Compute non-overlapping layout
  const { serverCoord, workerCoords } = useMemo(
    () => getTopologyLayout(observedWorkersCount),
    [observedWorkersCount]
  );

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3 font-sans select-none relative overflow-hidden">
      {/* Header with Title and Status Badges */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`w-2 h-2 rounded-full ${
                isStale
                  ? 'bg-amber-400'
                  : attempt?.state === 'RUNNING' || isCommitted
                  ? 'bg-emerald-400 animate-pulse'
                  : 'bg-blue-400'
              }`}
              aria-hidden="true"
            />
            <h2 className="text-xs font-semibold text-[#f3f3f4] uppercase tracking-wider">
              Cluster Training Topology
            </h2>
            <span className="text-[11px] text-[#73737c]" aria-hidden="true">·</span>
            <span className="text-xs text-[#a1a1a8]">
              Parameter Server & Worker Cluster (DTP/1)
            </span>
          </div>
          <p className="text-xs text-[#73737c]">
            {isStale
              ? 'Telemetry snapshot is stale. Coordinator state may not reflect live workers.'
              : isCollecting
              ? `Step #${currentStep?.operationId} · Workers computing backward pass & streaming gradients to Parameter Server.`
              : isUpdating
              ? `Step #${currentStep?.operationId} · Strict BSP barrier gate locked · Computing all-reduce gradient aggregation.`
              : isBroadcasting
              ? `Step #${currentStep?.operationId} · Broadcasting updated canonical model parameters to cluster workers.`
              : isCommitted
              ? `Step #${currentStep?.operationId} · Step barrier committed · All gradients applied · Awaiting next batch.`
              : 'Workers compute gradients and exchange tensors with Parameter Server via DTP/1 persistent TCP.'}
          </p>
        </div>

        {/* Live Controls: HUD toggle & Realtime Exchange Indicator */}
        <div className="flex items-center gap-2 flex-wrap self-start sm:self-auto text-xs">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#171719] border border-white/[0.07] text-[#a1a1a8]">
            <Radio className="w-3 h-3 text-emerald-400" aria-hidden="true" />
            <span>Auto Live Synced</span>
          </div>

          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#171719] border border-white/[0.07] text-xs">
            <span
              className={`w-2 h-2 rounded-full ${
                isBroadcasting
                  ? 'bg-emerald-400 animate-pulse'
                  : isUpdating
                  ? 'bg-amber-400 animate-pulse'
                  : isCollecting || attempt?.state === 'RUNNING'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-zinc-500'
              }`}
              aria-hidden="true"
            />
            <span className="text-[#f3f3f4] font-medium">
              {isBroadcasting
                ? 'Phát tán trọng số (PS ➔ Worker)'
                : isUpdating
                ? 'Đồng bộ Barrier (All-Reduce)'
                : isCollecting || attempt?.state === 'RUNNING'
                ? 'Gửi Gradient (Worker ➔ PS)'
                : isCommitted
                ? 'Đã đồng bộ · Sẵn sàng bước tiếp'
                : 'DTP/1 Sẵn sàng'}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setShowMetricsHud(prev => !prev)}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 border border-white/[0.07] ${
              showMetricsHud
                ? 'bg-[#1a1a1e] text-[#f3f3f4]'
                : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4]'
            }`}
            title="Toggle transmission line telemetry badges"
          >
            <Wifi className="w-3 h-3 text-blue-400" aria-hidden="true" />
            <span>Metrics HUD</span>
          </button>
        </div>
      </div>

      {/* Main Canvas Area: Interactive SVG Link Layer with Computer Monitors & Server Chassis */}
      <div className="relative w-full h-[540px] sm:h-[580px] bg-[#09090b] rounded border border-white/[0.07] overflow-hidden">
        {/* Subtle grid pattern background */}
        <div
          className="absolute inset-0 opacity-[0.035] pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(#ffffff 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
          aria-hidden="true"
        />

        {/* SVG Transmission Vector Paths & Moving Packet Signals (Rendered BEHIND nodes) */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox="0 0 1000 580"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          {/* Radar orbit line when 0 workers */}
          {observedWorkersCount === 0 && (
            <ellipse
              cx="500"
              cy="280"
              rx="320"
              ry="160"
              fill="none"
              stroke="#27272a"
              strokeWidth="1.5"
              strokeDasharray="4 6"
              opacity="0.6"
            />
          )}

          {/* Dynamic SVG links between each worker monitor and server rack */}
          {workers.map((worker, idx) => {
            const coord = workerCoords[idx];
            if (!coord) return null;

            const isWorkerFailed = worker.state === 'FAILED' || worker.state === 'DISCONNECTED';
            const { x1, y1, x2, y2 } = computeLinkEndpoints(
              coord.x,
              coord.y,
              coord.cardWidth,
              coord.cardHeight,
              serverCoord.x,
              serverCoord.y,
              serverCoord.width,
              serverCoord.height
            );

            // Flow configuration based strictly on currentStep state & running status
            const isBroadcastingNow = isBroadcasting;
            const shouldAnimate =
              !prefersReducedMotion &&
              (attempt?.state === 'RUNNING' || isCollecting || isBroadcastingNow || isUpdating);

            let strokeColor = '#f59e0b';
            let strokeDash = '4 4';
            let pathD = `M ${x1} ${y1} L ${x2} ${y2}`; // worker -> server
            let particleColor = '#fbbf24';

            if (isWorkerFailed) {
              strokeColor = '#f43f5e';
              strokeDash = '3 3';
            } else if (isBroadcastingNow) {
              strokeColor = '#10b981';
              strokeDash = '4 4';
              pathD = `M ${x2} ${y2} L ${x1} ${y1}`; // server -> worker
              particleColor = '#34d399';
            } else if (isUpdating) {
              strokeColor = '#f59e0b';
              strokeDash = '2 2';
              particleColor = '#f59e0b';
            } else if (isCommitted) {
              strokeColor = '#10b981';
              strokeDash = 'none';
              particleColor = '#34d399';
            }

            return (
              <g key={`topo-link-${worker.sessionId || worker.workerId || idx}`}>
                {/* Glow underlay line */}
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeColor}
                  strokeWidth="4"
                  strokeOpacity="0.18"
                />

                {/* Main transmission line */}
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeColor}
                  strokeWidth="2.2"
                  strokeOpacity="0.85"
                  strokeDasharray={strokeDash}
                />

                {/* Realtime flowing data packet pulses along the transmission vector */}
                {shouldAnimate && !isWorkerFailed && (
                  <>
                    <circle r="4" fill={particleColor} opacity="0.95">
                      <animateMotion
                        path={pathD}
                        dur="1.5s"
                        repeatCount="indefinite"
                      />
                    </circle>
                    <circle r="2.5" fill={particleColor} opacity="0.75">
                      <animateMotion
                        path={pathD}
                        dur="1.5s"
                        begin="0.75s"
                        repeatCount="indefinite"
                      />
                    </circle>
                  </>
                )}
              </g>
            );
          })}
        </svg>

        {/* TRANSMISSION LINE TELEMETRY BADGES (Trao / Nhận) */}
        {showMetricsHud && workers.map((worker, idx) => {
          const coord = workerCoords[idx];
          if (!coord) return null;

          const midX = (coord.x + serverCoord.x) / 2;
          const midY = (coord.y + serverCoord.y) / 2;
          const contrib = contributions.find(c => c.workerId === worker.workerId);

          const isTransferringToWorker = isBroadcasting;

          return (
            <div
              key={`hud-badge-${worker.sessionId || worker.workerId || idx}`}
              style={{
                left: `${(midX / 1000) * 100}%`,
                top: `${(midY / 580) * 100}%`,
              }}
              className="absolute -translate-x-1/2 -translate-y-1/2 z-10 pointer-events-none"
            >
              <div className="bg-[#121214]/95 backdrop-blur-xs border border-white/[0.1] px-2.5 py-1.5 rounded shadow-lg text-[10px] space-y-1 min-w-[125px] text-center">
                <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] pb-0.5">
                  <span className="text-[#73737c]">DTP/1 Link:</span>
                  <span className="text-emerald-400 font-medium">TCP Connected</span>
                </div>
                <div className="flex items-center justify-between gap-1 text-[9px]">
                  <span className="text-[#73737c]">Trao/Nhận:</span>
                  <span className={isTransferringToWorker ? 'text-emerald-400 font-medium' : 'text-amber-400 font-medium'}>
                    {isTransferringToWorker
                      ? `PS ➔ W: Trọng số v${currentStep?.outputModelVersion || attempt?.modelVersion || '—'}`
                      : isUpdating
                      ? 'PS: Đồng bộ Barrier'
                      : contrib?.contributionAccepted
                      ? 'W ➔ PS: Đã nộp Gradient'
                      : 'W ➔ PS: Đang đẩy Gradient'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}

        {/* PARAMETER SERVER RACK CHASSIS */}
        <div
          onClick={onOpenServerDetails}
          style={{
            left: `${(serverCoord.x / 1000) * 100}%`,
            top: `${(serverCoord.y / 580) * 100}%`,
            width: `${serverCoord.width}px`,
          }}
          className="absolute -translate-x-1/2 -translate-y-1/2 z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.02]"
          role="button"
          tabIndex={0}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              onOpenServerDetails?.();
            }
          }}
          aria-label="Inspect Parameter Server details"
        >
          <div
            className={`w-full rounded-lg bg-[#141416] p-3 shadow-2xl border-2 transition-all duration-300 relative ${
              isStale
                ? 'border-amber-500/50 shadow-amber-500/10'
                : isUpdating
                ? 'border-amber-400 shadow-amber-400/20'
                : isCommitted || isBroadcasting
                ? 'border-emerald-500 shadow-emerald-500/20'
                : 'border-emerald-500 shadow-emerald-500/10'
            }`}
          >
            {/* Left & Right Rack Ears with screw indicators */}
            <div className="absolute left-1 top-2 bottom-2 w-1 border-r border-zinc-700/60 flex flex-col justify-between py-1" aria-hidden="true">
              <div className="w-1 h-1 rounded-full bg-zinc-600" />
              <div className="w-1 h-1 rounded-full bg-zinc-600" />
            </div>
            <div className="absolute right-1 top-2 bottom-2 w-1 border-l border-zinc-700/60 flex flex-col justify-between py-1" aria-hidden="true">
              <div className="w-1 h-1 rounded-full bg-zinc-600" />
              <div className="w-1 h-1 rounded-full bg-zinc-600" />
            </div>

            {/* Server Faceplate Header */}
            <div className="flex items-center justify-between pl-2 pr-2 pb-1.5 mb-1.5 border-b border-white/[0.08]">
              <div className="flex items-center gap-1.5">
                <ServerIcon
                  className={`w-3.5 h-3.5 ${
                    isUpdating
                      ? 'text-amber-400'
                      : isCommitted || isBroadcasting
                      ? 'text-emerald-400'
                      : 'text-emerald-400'
                  }`}
                  aria-hidden="true"
                />
                <span className="text-xs font-bold text-[#f3f3f4] tracking-wide">
                  Parameter Server
                </span>
              </div>
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" aria-hidden="true" />
                <span className="text-[10px] font-mono text-[#73737c]">DTP/1</span>
              </div>
            </div>

            {/* Server Console Status Panel */}
            <div className="mx-1 bg-[#09090b] rounded p-2 border border-white/[0.04] space-y-1 font-mono text-[10px]">
              <div className="flex items-center justify-between">
                <span className="text-[#73737c]">Barrier:</span>
                <span
                  className={`font-semibold ${
                    isCommitted
                      ? 'text-emerald-400'
                      : isUpdating
                      ? 'text-amber-400'
                      : 'text-emerald-400'
                  }`}
                >
                  {isBroadcasting
                    ? 'Broadcasting Weights'
                    : isSyncComplete
                    ? 'Barrier Synced'
                    : isUpdating
                    ? 'All-Reduce Update'
                    : acceptedCount != null && expectedCount != null
                    ? `Syncing: ${acceptedCount}/${expectedCount} Workers`
                    : 'Awaiting Gradients'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[#73737c]">
                <span>Step:</span>
                <span className="text-[#f3f3f4]">
                  {currentStep ? `#${currentStep.operationId}` : 'Pending'}
                </span>
              </div>
              <div className="flex items-center justify-between text-[#73737c]">
                <span>Model:</span>
                <span className="text-emerald-400">
                  {currentStep?.outputModelVersion
                    ? `v${currentStep.outputModelVersion}`
                    : (attempt?.modelVersion || '—')}
                </span>
              </div>
            </div>

            {/* Server LED Drive Status Bar */}
            <div className="mx-1 mt-2 pt-1.5 border-t border-white/[0.06] flex items-center justify-between text-[9px] text-[#73737c]">
              <div className="flex items-center gap-1" aria-hidden="true">
                <span className="w-1 h-1 rounded-full bg-emerald-400" />
                <span className="w-1 h-1 rounded-full bg-emerald-400" />
                <span className="w-1 h-1 rounded-full bg-amber-400" />
              </div>
              <span className="font-mono">Runtime Coordinator</span>
            </div>
          </div>
        </div>

        {/* EMPTY STATE (When 0 workers are observed) */}
        {observedWorkersCount === 0 && (
          <div className="absolute left-1/2 bottom-[12%] -translate-x-1/2 z-20 text-center max-w-sm px-4 py-2.5 bg-[#121214]/90 border border-white/[0.08] rounded-lg shadow-xl text-xs space-y-1">
            <div className="flex items-center justify-center gap-1.5 text-[#a1a1a8] font-medium">
              <Radio className="w-3.5 h-3.5 text-zinc-500" aria-hidden="true" />
              <span>0 Worker Sessions Observed</span>
            </div>
            <p className="text-[11px] text-[#73737c]">
              Workers will appear here dynamically as they connect to the Parameter Server via DTP/1.
            </p>
          </div>
        )}

        {/* DYNAMIC WORKER NODES (Stylized Computer Monitors displaying machine parameters on screen) */}
        {workers.map((worker, idx) => {
          const coord = workerCoords[idx];
          if (!coord) return null;

          const isWorkerFailed = worker.state === 'FAILED' || worker.state === 'DISCONNECTED';
          const isReady = worker.state === 'READY' || worker.state === 'RUNNING';
          const contrib = contributions.find(c => c.workerId === worker.workerId);

          const monitorBorderClass = isWorkerFailed
            ? 'border-rose-500 shadow-rose-500/10'
            : isCommitted || contrib?.contributionAccepted
            ? 'border-emerald-500 shadow-emerald-500/10'
            : 'border-amber-400 shadow-amber-400/10';

          const statusColor = isWorkerFailed
            ? 'text-rose-400'
            : isCommitted || contrib?.contributionAccepted
            ? 'text-emerald-400'
            : 'text-amber-400';

          let statusText = worker.state;
          if (isBroadcasting) {
            statusText = 'Receiving Weights';
          } else if (isCommitted || contrib?.contributionAccepted) {
            statusText = 'Gradients Pushed';
          } else if (isCollecting || attempt?.state === 'RUNNING') {
            statusText = 'Streaming Gradients';
          } else if (isReady) {
            statusText = 'Training Active';
          }

          const machineName = worker.nodeLabel || `node-${worker.workerId}`;

          return (
            <div
              key={worker.sessionId || `worker-monitor-${worker.workerId}`}
              onClick={() => onSelectWorker?.(worker)}
              style={{
                left: `${(coord.x / 1000) * 100}%`,
                top: `${(coord.y / 580) * 100}%`,
                width: `${coord.cardWidth}px`,
              }}
              className="absolute -translate-x-1/2 -translate-y-1/2 z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.03]"
              role="button"
              tabIndex={0}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  onSelectWorker?.(worker);
                }
              }}
              aria-label={`Inspect Worker ${worker.workerId} on ${machineName}`}
            >
              {/* Computer Workstation Monitor Illustration */}
              <div className="flex flex-col items-center">
                {/* Monitor Screen Frame */}
                <div
                  className={`w-full rounded-lg bg-[#141416] p-2.5 shadow-2xl border-2 transition-all duration-300 ${monitorBorderClass}`}
                >
                  {/* Top Bezel: Status dot + Worker ID + Machine Name (Tên máy) */}
                  <div className="flex items-center justify-between pb-1.5 mb-1.5 border-b border-white/[0.08]">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                          isWorkerFailed
                            ? 'bg-rose-400'
                            : isCommitted || contrib?.contributionAccepted
                            ? 'bg-emerald-400'
                            : 'bg-amber-400'
                        }`}
                        aria-hidden="true"
                      />
                      <span className="text-xs font-bold text-[#f3f3f4] group-hover:text-white truncate">
                        Worker {worker.workerId}
                      </span>
                    </div>

                    {/* Machine Name (Tên của máy hiển thị nổi bật) */}
                    <span
                      className="text-[10px] font-mono text-[#a1a1a8] truncate max-w-[105px] px-1 py-0.5 rounded bg-white/[0.04]"
                      title={machineName}
                    >
                      {machineName}
                    </span>
                  </div>

                  {/* Monitor Screen Internal Display */}
                  <div className="bg-[#09090b] rounded p-2 border border-white/[0.04] space-y-1 font-mono text-[10px]">
                    <div className="flex items-center justify-between">
                      <span className="text-[#73737c]">State:</span>
                      <span className={`font-semibold ${statusColor}`}>{statusText}</span>
                    </div>
                    <div className="flex items-center justify-between text-[#73737c]">
                      <span>Shard:</span>
                      <span className="text-[#f3f3f4] truncate max-w-[100px]">
                        {worker.assignedShard || (worker.shardId != null ? `shard-${worker.shardId}` : 'Ready')}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[#73737c]">
                      <span>Model:</span>
                      <span className="text-emerald-400">
                        {worker.currentModelVersion != null
                          ? `v${worker.currentModelVersion}`
                          : worker.localModelVersion != null
                          ? `v${worker.localModelVersion}`
                          : '—'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Monitor Stand Neck & Base */}
                <div className="w-5 h-2 bg-zinc-700 -mt-px" aria-hidden="true" />
                <div className="w-16 h-1.5 bg-zinc-600 rounded-sm shadow-md" aria-hidden="true" />
              </div>
            </div>
          );
        })}
      </div>

      {/* FOOTER METRICS SUMMARY BAR */}
      <div className="bg-[#171719] border border-white/[0.06] rounded p-3 text-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[#73737c]">Transmission Protocol:</span>
          <span className="font-mono text-[#f3f3f4] bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06]">
            DTP/1 · Persistent TCP
          </span>
          <span className="text-[#73737c]" aria-hidden="true">·</span>
          <span className="text-[#73737c]">Strict BSP Barrier:</span>
          <span className="text-emerald-400 font-medium">
            {expectedWorkers > 0
              ? `${observedWorkersCount}/${expectedWorkers} Workers Active`
              : `${observedWorkersCount} Workers Active`}
          </span>
          {isPartialProjection && (
            <span className="px-1.5 py-0.2 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 text-[10px] font-mono">
              Partial Projection
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 text-xs text-[#a1a1a8] flex-wrap">
          <div>
            <span className="text-[#73737c] mr-1.5">Step:</span>
            <span className="font-mono text-[#f3f3f4]">
              {currentStep ? `#${currentStep.operationId}` : '—'}
            </span>
          </div>
          <div>
            <span className="text-[#73737c] mr-1.5">Epoch:</span>
            <span className="font-mono text-[#f3f3f4]">
              {currentStep?.epoch ?? attempt?.epoch ?? '—'}
            </span>
          </div>
          <div>
            <span className="text-[#73737c] mr-1.5">Batch Samples:</span>
            <span className="font-mono text-[#f3f3f4]">
              {currentStep?.totalSampleCount != null
                ? `${currentStep.totalSampleCount.toLocaleString()}`
                : 'Pending'}
            </span>
          </div>
          <div>
            <span className="text-[#73737c] mr-1.5">Model Weights:</span>
            <span className="font-mono text-emerald-400">
              {currentStep?.outputModelVersion
                ? `v${currentStep.outputModelVersion}`
                : attempt?.modelVersion || 'Pending'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
