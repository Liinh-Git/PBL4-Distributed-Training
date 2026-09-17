import React, { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  Play,
  Pause,
  RotateCw,
  Zap,
  Wifi,
  ChevronRight,
  Info,
  Server as ServerIcon,
  Cloud as CloudIcon,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  Clock,
  HardDrive,
  Cpu,
} from 'lucide-react';
import { TrainingStep, WorkerSession, Attempt } from '../../types';

export type TopologyPhaseId = 'phase-1' | 'phase-2' | 'phase-3' | 'phase-4';

interface TrainingTopologyVisualizerProps {
  currentStep?: TrainingStep;
  workers: WorkerSession[];
  expectedWorkers: number;
  attempt?: Attempt;
  isSimulating?: boolean;
  onToggleSimulating?: () => void;
  onSelectWorker?: (worker: WorkerSession) => void;
  onOpenServerDetails?: () => void;
}

export const TrainingTopologyVisualizer: React.FC<TrainingTopologyVisualizerProps> = ({
  currentStep,
  workers,
  expectedWorkers,
  attempt,
  isSimulating,
  onToggleSimulating,
  onSelectWorker,
  onOpenServerDetails,
}) => {
  // Manual override or follow live training
  const [isLiveAutoMode, setIsLiveAutoMode] = useState<boolean>(true);
  const [selectedPhase, setSelectedPhase] = useState<TopologyPhaseId>('phase-2');
  const [showMetricsOverlay, setShowMetricsOverlay] = useState<boolean>(true);
  const [selectedNodeId, setSelectedNodeId] = useState<'cloud' | 'ps' | 'w1' | 'w2' | 'w3' | null>(null);

  // Dynamic live phase calculation based on active training step state
  const livePhase: TopologyPhaseId = useMemo(() => {
    if (!currentStep) return 'phase-2';

    // If step just created or initial epoch/batch 1 with fresh state
    if (currentStep.state === 'CREATED' || currentStep.state === 'DISPATCHED') {
      return 'phase-1';
    }
    // If waiting or collecting gradients
    if (currentStep.state === 'COLLECTING_GRADIENTS') {
      const contributions = currentStep.workerContributions || [];
      const acceptedCount = contributions.filter(c => c.contributionAccepted).length;
      if (acceptedCount >= expectedWorkers) {
        return 'phase-3'; // all arrived, ready to barrier sync
      }
      return 'phase-2'; // pushing in progress
    }
    // If aggregating or updating global weights
    if (currentStep.state === 'AGGREGATING' || currentStep.state === 'UPDATING') {
      return 'phase-3';
    }
    // If broadcasting or waiting for workers to apply new parameters
    if (
      currentStep.state === 'BROADCASTING' ||
      currentStep.state === 'WAITING_PARAMETER_APPLIED' ||
      currentStep.state === 'COMMITTED'
    ) {
      return 'phase-4';
    }

    return 'phase-2';
  }, [currentStep, expectedWorkers]);

  // Active phase being displayed
  const currentPhase = isLiveAutoMode ? livePhase : selectedPhase;

  // Real-time animation counter for oscillating transfer progress & speed simulation
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => {
      setTick(t => (t + 1) % 100);
    }, 400);
    return () => clearInterval(timer);
  }, []);

  // Compute worker dynamic attributes based on current phase
  const worker1Data = useMemo(() => {
    switch (currentPhase) {
      case 'phase-1': // Image 1: Worker 01 Download OK
        return {
          title: 'Worker 01',
          status: 'Download OK',
          subtext: 'Dataset shard 00 ready',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '1.2ms',
          bandwidth: '10 Gbps',
          packetType: 'CIFAR-10 Shard (175 MB)',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
      case 'phase-2': // Image 2: Worker 01 Pushing (69%), 5MB/s
        const p2Pct = 65 + (tick % 7);
        return {
          title: 'Worker 01',
          status: `Pushing (${p2Pct}%)`,
          subtext: 'Uploading gradient tensors',
          stateType: 'active' as const,
          speed: '5MB/s',
          progress: p2Pct,
          latency: '4.2ms',
          bandwidth: '5.0 MB/s',
          packetType: 'FP32 Gradients (18.2 MB)',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-3': // Image 3: Worker 01 Push OK
        return {
          title: 'Worker 01',
          status: 'Push OK',
          subtext: 'Gradients delivered to barrier',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '1.1ms',
          bandwidth: '10 Gbps',
          packetType: 'ACK Verified (0 pkt loss)',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-4': // Image 4: Worker 01 Pulling new Parameter (69%), 3MB/s
        const p4Pct = 68 + (tick % 5);
        return {
          title: 'Worker 01',
          status: `Pulling new Parameter (${p4Pct}%)`,
          subtext: 'Downloading updated weights',
          stateType: 'active' as const,
          speed: '3MB/s',
          progress: p4Pct,
          latency: '3.8ms',
          bandwidth: '3.0 MB/s',
          packetType: 'Model Weights v3264 (44.8 MB)',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
    }
  }, [currentPhase, tick]);

  const worker2Data = useMemo(() => {
    switch (currentPhase) {
      case 'phase-1': // Image 1: Worker 02 Downloading (69%), 2MB/s
        const p1Pct = 68 + (tick % 4);
        return {
          title: 'Worker 02',
          status: `Downloading (${p1Pct}%)`,
          subtext: 'Streaming data partition 01',
          stateType: 'active' as const,
          speed: '2MB/s',
          progress: p1Pct,
          latency: '2.1ms',
          bandwidth: '2.0 MB/s',
          packetType: 'CIFAR-10 Shard (120/175 MB)',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
      case 'phase-2': // Image 2: Worker 02 Training (80%)
        const p2Pct = 78 + (tick % 6);
        return {
          title: 'Worker 02',
          status: `Training (${p2Pct}%)`,
          subtext: 'Backward pass backprop in progress',
          stateType: 'active' as const,
          speed: '',
          progress: p2Pct,
          latency: '0.8ms',
          bandwidth: 'Standby link',
          packetType: 'Batch 3264 Tensor forward/back',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-3': // Image 3: Worker 02 Push OK
        return {
          title: 'Worker 02',
          status: 'Push OK',
          subtext: 'Gradients delivered to barrier',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '1.3ms',
          bandwidth: '10 Gbps',
          packetType: 'ACK Verified (0 pkt loss)',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-4': // Image 4: Worker 02 Pull new Parameter OK
        return {
          title: 'Worker 02',
          status: 'Pull new Parameter OK',
          subtext: 'Weights synchronized',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '1.2ms',
          bandwidth: '10 Gbps',
          packetType: 'Model v3264 active in VRAM',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
    }
  }, [currentPhase, tick]);

  const worker3Data = useMemo(() => {
    switch (currentPhase) {
      case 'phase-1': // Image 1: Worker 03 Verifying Data...
        return {
          title: 'Worker 03',
          status: 'Verifying Data...',
          subtext: 'Validating SHA-256 shard checksum',
          stateType: 'active' as const,
          speed: '',
          progress: 94,
          latency: '1.5ms',
          bandwidth: 'Local NVMe',
          packetType: 'Checksum integrity matching',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
      case 'phase-2': // Image 2: Worker 03 Push OK
        return {
          title: 'Worker 03',
          status: 'Push OK',
          subtext: 'First to reach barrier gate',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '0.9ms',
          bandwidth: '10 Gbps',
          packetType: 'FP32 Gradients buffered',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-3': // Image 3: Worker 03 Push OK
        return {
          title: 'Worker 03',
          status: 'Push OK',
          subtext: 'Gradients delivered to barrier',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '0.9ms',
          bandwidth: '10 Gbps',
          packetType: 'ACK Verified (0 pkt loss)',
          flowDirection: 'to-center' as const,
          linkActive: true,
        };
      case 'phase-4': // Image 4: Worker 03 Pull new Parameter OK
        return {
          title: 'Worker 03',
          status: 'Pull new Parameter OK',
          subtext: 'Weights synchronized',
          stateType: 'ok' as const,
          speed: '',
          progress: 100,
          latency: '1.0ms',
          bandwidth: '10 Gbps',
          packetType: 'Model v3264 active in VRAM',
          flowDirection: 'from-center' as const,
          linkActive: true,
        };
    }
  }, [currentPhase, tick]);

  // Center Server Data
  const centerServerData = useMemo(() => {
    if (currentPhase === 'phase-1') {
      return {
        isCloud: true,
        name: 'Cloud Server',
        status: 'Distributing Shards',
        substatus: 'Active Egress: 4.8 MB/s',
        stateType: 'cloud' as const,
        borderClass: 'border-sky-500/50 shadow-sky-500/10',
        textColor: 'text-sky-300',
        badgeColor: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
        details: 'Dataset repository distributing preprocessed CIFAR-10 shards to cluster workers',
      };
    }

    if (currentPhase === 'phase-2') {
      return {
        isCloud: false,
        name: 'Parameter Server',
        status: 'Syncing: 1/3 Workers',
        substatus: 'Wait: 8ms',
        stateType: 'ok' as const,
        borderClass: 'border-emerald-500 shadow-emerald-500/10',
        textColor: 'text-emerald-400',
        badgeColor: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
        details: 'Strict BSP barrier gate: 1 of 3 gradient sets arrived; holding until all workers report',
      };
    }

    if (currentPhase === 'phase-3') {
      return {
        isCloud: false,
        name: 'Parameter Server',
        status: 'Syncing...',
        substatus: 'Aggregating All-Reduce',
        stateType: 'active' as const,
        borderClass: 'border-amber-400 shadow-amber-400/10',
        textColor: 'text-amber-400',
        badgeColor: 'bg-amber-400/10 text-amber-400 border-amber-400/20',
        details: 'All 3 worker contributions locked in barrier. Calculating SGD momentum update',
      };
    }

    // Phase 4
    return {
      isCloud: false,
      name: 'Parameter Server',
      status: 'Sync OK',
      substatus: 'Broadcasting v3264',
      stateType: 'ok' as const,
      borderClass: 'border-emerald-500 shadow-emerald-500/10',
      textColor: 'text-emerald-400',
      badgeColor: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
      details: 'Global parameter tensors updated and acknowledged. Distributing weights to workers',
    };
  }, [currentPhase]);

  // Phase explanations for title bar
  const phaseMetadata = {
    'phase-1': {
      number: '1',
      title: 'Dataset Shard Ingestion & Cloud Server Distribution',
      subtitle: 'Workers download dataset partitions from Cloud Server with checksum verification (Image 1)',
    },
    'phase-2': {
      number: '2',
      title: 'Forward/Backward Execution & Gradient Push',
      subtitle: 'Workers compute gradients and push tensors to Parameter Server; PS waits for 3/3 barrier (Image 2)',
    },
    'phase-3': {
      number: '3',
      title: 'Strict BSP Barrier Gate & Gradient Aggregation',
      subtitle: 'All workers pushed OK; Parameter Server aggregates tensors & executes optimizer update (Image 3)',
    },
    'phase-4': {
      number: '4',
      title: 'Parameter Broadcast & Worker Pull',
      subtitle: 'Parameter Server sync OK; Workers pull the updated model parameters for the next batch (Image 4)',
    },
  };

  return (
    <div className="bg-[#121214] border border-white/[0.07] rounded p-4 space-y-3 font-sans select-none relative overflow-hidden">
      {/* Topology Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.07]">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <h2 className="text-xs font-semibold text-[#f3f3f4] uppercase tracking-wider">
              Cluster Training Topology
            </h2>
            <span className="text-[11px] text-[#73737c]">·</span>
            <span className="text-xs text-[#a1a1a8]">
              {centerServerData.name} & Worker Transmission Pipeline
            </span>
          </div>
          <p className="text-xs text-[#73737c]">
            {phaseMetadata[currentPhase].subtitle}
          </p>
        </div>

        {/* Phase selector & Mode Switch */}
        <div className="flex items-center gap-1.5 flex-wrap self-start sm:self-auto text-xs">
          {/* Live Auto Toggle */}
          <button
            type="button"
            onClick={() => setIsLiveAutoMode(prev => !prev)}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
              isLiveAutoMode
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.07]'
            }`}
            title="Automatically switch topology stages as the live training advances"
          >
            <Zap className={`w-3 h-3 ${isLiveAutoMode ? 'text-emerald-400' : 'text-[#73737c]'}`} />
            <span>{isLiveAutoMode ? 'Auto Live Synced' : 'Manual Stage'}</span>
          </button>

          {/* Toggle Metrics Overlay */}
          <button
            type="button"
            onClick={() => setShowMetricsOverlay(prev => !prev)}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 border border-white/[0.07] ${
              showMetricsOverlay
                ? 'bg-[#1a1a1e] text-[#f3f3f4]'
                : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4]'
            }`}
            title="Toggle transmission path metrics (speeds, progress, latency)"
          >
            <Wifi className="w-3 h-3 text-blue-400" />
            <span>Metrics HUD</span>
          </button>
        </div>
      </div>

      {/* Stage Selector Pills (Reflecting the 4 drawings) */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs scrollbar-none">
        <span className="text-[11px] text-[#73737c] shrink-0 mr-1">Topology Views:</span>
        <button
          type="button"
          onClick={() => {
            setIsLiveAutoMode(false);
            setSelectedPhase('phase-1');
          }}
          className={`px-2.5 py-1 rounded transition-colors shrink-0 flex items-center gap-1.5 ${
            currentPhase === 'phase-1'
              ? 'bg-sky-950/60 text-sky-300 border border-sky-500/40 font-medium'
              : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.06]'
          }`}
        >
          <CloudIcon className="w-3 h-3 text-sky-400" />
          <span>1. Cloud Download</span>
        </button>

        <button
          type="button"
          onClick={() => {
            setIsLiveAutoMode(false);
            setSelectedPhase('phase-2');
          }}
          className={`px-2.5 py-1 rounded transition-colors shrink-0 flex items-center gap-1.5 ${
            currentPhase === 'phase-2'
              ? 'bg-amber-950/60 text-amber-300 border border-amber-500/40 font-medium'
              : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.06]'
          }`}
        >
          <Activity className="w-3 h-3 text-amber-400" />
          <span>2. Gradient Push (1/3 Sync)</span>
        </button>

        <button
          type="button"
          onClick={() => {
            setIsLiveAutoMode(false);
            setSelectedPhase('phase-3');
          }}
          className={`px-2.5 py-1 rounded transition-colors shrink-0 flex items-center gap-1.5 ${
            currentPhase === 'phase-3'
              ? 'bg-amber-950/60 text-amber-300 border border-amber-500/40 font-medium'
              : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.06]'
          }`}
        >
          <ShieldCheck className="w-3 h-3 text-amber-400" />
          <span>3. Barrier Sync (Syncing...)</span>
        </button>

        <button
          type="button"
          onClick={() => {
            setIsLiveAutoMode(false);
            setSelectedPhase('phase-4');
          }}
          className={`px-2.5 py-1 rounded transition-colors shrink-0 flex items-center gap-1.5 ${
            currentPhase === 'phase-4'
              ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-500/40 font-medium'
              : 'bg-[#171719] text-[#73737c] hover:text-[#f3f3f4] border border-white/[0.06]'
          }`}
        >
          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
          <span>4. Parameter Pull (Sync OK)</span>
        </button>
      </div>

      {/* Main Canvas Area: Interactive SVG & HTML Node overlay */}
      <div className="relative w-full h-[540px] sm:h-[580px] bg-[#09090b] rounded border border-white/[0.07] overflow-hidden">
        {/* Subtle grid pattern background */}
        <div
          className="absolute inset-0 opacity-[0.035] pointer-events-none"
          style={{
            backgroundImage: `radial-gradient(#ffffff 1px, transparent 1px)`,
            backgroundSize: '24px 24px',
          }}
        />

        {/* SVG Transmission Vector Paths & Moving Packet Signals */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none"
          viewBox="0 0 1000 600"
          preserveAspectRatio="none"
        >
          <defs>
            {/* Arrowhead markers */}
            <marker
              id="arrow-green"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
            </marker>
            <marker
              id="arrow-amber"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#f59e0b" />
            </marker>
            <marker
              id="arrow-sky"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8" />
            </marker>
            <marker
              id="arrow-gray"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 1 L 10 5 L 0 9 z" fill="#52525b" />
            </marker>
          </defs>

          {/* Node Center Coordinates in 1000x600 viewBox:
              Center: (500, 275)
              Worker 01: (230, 140)
              Worker 02: (770, 140)
              Worker 03: (500, 480)
          */}

          {/* PATH 1: Center <--> Worker 01 */}
          {(() => {
            const isToCenter = worker1Data.flowDirection === 'to-center';
            const isFromCenter = worker1Data.flowDirection === 'from-center';
            const strokeColor =
              worker1Data.stateType === 'ok'
                ? '#10b981'
                : currentPhase === 'phase-1'
                ? '#38bdf8'
                : '#f59e0b';
            const markerId =
              worker1Data.stateType === 'ok'
                ? 'url(#arrow-green)'
                : currentPhase === 'phase-1'
                ? 'url(#arrow-sky)'
                : 'url(#arrow-amber)';

            // Line segment between node boundaries
            // W1 center (230, 140) -> Center (500, 275): dx = 270, dy = 135
            // Start at W1 edge: (285, 168), End at Center edge: (445, 248)
            const x1 = isToCenter ? 285 : 445;
            const y1 = isToCenter ? 168 : 248;
            const x2 = isToCenter ? 445 : 285;
            const y2 = isToCenter ? 248 : 168;

            return (
              <g key="link-w1">
                {/* Background path */}
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeColor}
                  strokeWidth="2.2"
                  strokeOpacity={worker1Data.linkActive ? '0.9' : '0.4'}
                  strokeDasharray={worker1Data.stateType === 'active' ? '5 4' : 'none'}
                  markerEnd={markerId}
                  className="transition-all duration-300"
                />

                {/* Animated transmission pulse particle */}
                {worker1Data.linkActive && (
                  <circle r="4.5" fill={strokeColor} opacity="0.95">
                    <animateMotion
                      path={`M ${x1} ${y1} L ${x2} ${y2}`}
                      dur="1.4s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}
              </g>
            );
          })()}

          {/* PATH 2: Center <--> Worker 02 */}
          {(() => {
            const isToCenter = worker2Data.flowDirection === 'to-center';
            const isFromCenter = worker2Data.flowDirection === 'from-center';
            const strokeColor =
              worker2Data.stateType === 'ok'
                ? '#10b981'
                : currentPhase === 'phase-1'
                ? '#38bdf8'
                : '#f59e0b';
            const markerId =
              worker2Data.stateType === 'ok'
                ? 'url(#arrow-green)'
                : currentPhase === 'phase-1'
                ? 'url(#arrow-sky)'
                : 'url(#arrow-amber)';

            // Center (500, 275) <--> W2 (770, 140)
            const x1 = isToCenter ? 715 : 555;
            const y1 = isToCenter ? 168 : 248;
            const x2 = isToCenter ? 555 : 715;
            const y2 = isToCenter ? 248 : 168;

            return (
              <g key="link-w2">
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeColor}
                  strokeWidth="2.2"
                  strokeOpacity={worker2Data.linkActive ? '0.9' : '0.4'}
                  strokeDasharray={worker2Data.stateType === 'active' ? '5 4' : 'none'}
                  markerEnd={markerId}
                  className="transition-all duration-300"
                />

                {worker2Data.linkActive && (
                  <circle r="4.5" fill={strokeColor} opacity="0.95">
                    <animateMotion
                      path={`M ${x1} ${y1} L ${x2} ${y2}`}
                      dur="1.5s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}
              </g>
            );
          })()}

          {/* PATH 3: Center <--> Worker 03 */}
          {(() => {
            const isToCenter = worker3Data.flowDirection === 'to-center';
            const isFromCenter = worker3Data.flowDirection === 'from-center';
            const strokeColor =
              worker3Data.stateType === 'ok'
                ? '#10b981'
                : currentPhase === 'phase-1'
                ? '#38bdf8'
                : '#f59e0b';
            const markerId =
              worker3Data.stateType === 'ok'
                ? 'url(#arrow-green)'
                : currentPhase === 'phase-1'
                ? 'url(#arrow-sky)'
                : 'url(#arrow-amber)';

            // Center (500, 275) <--> W3 (500, 480)
            const x1 = 500;
            const y1 = isToCenter ? 415 : 340;
            const x2 = 500;
            const y2 = isToCenter ? 340 : 415;

            return (
              <g key="link-w3">
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={strokeColor}
                  strokeWidth="2.2"
                  strokeOpacity={worker3Data.linkActive ? '0.9' : '0.4'}
                  strokeDasharray={worker3Data.stateType === 'active' ? '5 4' : 'none'}
                  markerEnd={markerId}
                  className="transition-all duration-300"
                />

                {worker3Data.linkActive && (
                  <circle r="4.5" fill={strokeColor} opacity="0.95">
                    <animateMotion
                      path={`M ${x1} ${y1} L ${x2} ${y2}`}
                      dur="1.3s"
                      repeatCount="indefinite"
                    />
                  </circle>
                )}
              </g>
            );
          })()}
        </svg>

        {/* TRANSMISSION SPECS & METRICS LABELS (Thông số đường truyền) */}
        {showMetricsOverlay && (
          <>
            {/* Link 1 Metric Badge (Between Center & Worker 01) */}
            <div
              className="absolute left-[33%] top-[25%] -translate-x-1/2 -translate-y-1/2 z-10 pointer-events-auto"
            >
              <div className="bg-[#121214]/90 backdrop-blur-xs border border-white/[0.08] px-2 py-1 rounded shadow-lg text-[10px] space-y-0.5 max-w-[140px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[#73737c]">Speed:</span>
                  <span className={worker1Data.speed ? 'text-amber-400 font-mono font-medium' : 'text-emerald-400 font-mono'}>
                    {worker1Data.speed || '10 Gbps OK'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[9px] text-[#73737c]">
                  <span>Latency:</span>
                  <span className="text-[#a1a1a8] font-mono">{worker1Data.latency}</span>
                </div>
              </div>
            </div>

            {/* Link 2 Metric Badge (Between Center & Worker 02) */}
            <div
              className="absolute left-[67%] top-[25%] -translate-x-1/2 -translate-y-1/2 z-10 pointer-events-auto"
            >
              <div className="bg-[#121214]/90 backdrop-blur-xs border border-white/[0.08] px-2 py-1 rounded shadow-lg text-[10px] space-y-0.5 max-w-[140px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[#73737c]">Speed:</span>
                  <span className={worker2Data.speed ? 'text-amber-400 font-mono font-medium' : 'text-emerald-400 font-mono'}>
                    {worker2Data.speed || '10 Gbps OK'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[9px] text-[#73737c]">
                  <span>Latency:</span>
                  <span className="text-[#a1a1a8] font-mono">{worker2Data.latency}</span>
                </div>
              </div>
            </div>

            {/* Link 3 Metric Badge (Between Center & Worker 03) */}
            <div
              className="absolute left-[54%] top-[65%] -translate-x-1/2 -translate-y-1/2 z-10 pointer-events-auto"
            >
              <div className="bg-[#121214]/90 backdrop-blur-xs border border-white/[0.08] px-2 py-1 rounded shadow-lg text-[10px] space-y-0.5 max-w-[140px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[#73737c]">Speed:</span>
                  <span className={worker3Data.speed ? 'text-amber-400 font-mono font-medium' : 'text-emerald-400 font-mono'}>
                    {worker3Data.speed || '10 Gbps OK'}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 text-[9px] text-[#73737c]">
                  <span>Latency:</span>
                  <span className="text-[#a1a1a8] font-mono">{worker3Data.latency}</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* NODE 1: WORKER 01 (Top-Left) */}
        <div
          onClick={() => {
            setSelectedNodeId('w1');
            const w = workers[0];
            if (w && onSelectWorker) onSelectWorker(w);
          }}
          className={`absolute left-[7%] sm:left-[12%] lg:left-[14%] top-[6%] sm:top-[8%] z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.03]`}
        >
          <div
            className={`w-36 h-36 sm:w-44 sm:h-44 rounded-full bg-[#121214] flex flex-col items-center justify-center p-3 text-center transition-all duration-300 shadow-xl border-2 ${
              worker1Data.stateType === 'ok'
                ? 'border-emerald-500 shadow-emerald-500/10'
                : 'border-amber-400 shadow-amber-400/10'
            }`}
          >
            {/* Retro-modern Computer/Workstation Illustration */}
            <div className="relative mb-1">
              <svg className="w-10 h-10 sm:w-11 sm:h-11" viewBox="0 0 64 64" fill="none">
                {/* Monitor display */}
                <rect x="12" y="10" width="40" height="28" rx="4" fill="#1e293b" stroke="#64748b" strokeWidth="2.5" />
                <rect x="17" y="15" width="30" height="18" rx="1.5" fill="#0f172a" />
                {/* Code lines on screen */}
                <line x1="20" y1="20" x2="36" y2="20" stroke={worker1Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                <line x1="20" y1="25" x2="42" y2="25" stroke={worker1Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                {/* Neck/Stand */}
                <path d="M 28 38 L 36 38 L 38 43 L 26 43 Z" fill="#475569" />
                {/* Base desktop chassis */}
                <rect x="10" y="43" width="44" height="9" rx="2" fill="#334155" stroke="#475569" strokeWidth="1.5" />
                <circle cx="48" cy="47.5" r="1.5" fill={worker1Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} />
                <line x1="16" y1="47.5" x2="28" y2="47.5" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>

            {/* Label */}
            <div className="text-xs sm:text-sm font-semibold text-[#f3f3f4] group-hover:text-white transition-colors">
              Worker 01
            </div>

            {/* Dynamic Status matching drawings */}
            <div
              className={`text-xs sm:text-[13px] font-medium mt-0.5 transition-colors ${
                worker1Data.stateType === 'ok' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {worker1Data.status}
            </div>

            {/* Transmission speed if present */}
            {worker1Data.speed && (
              <div className="text-[11px] sm:text-xs font-mono text-amber-300 mt-0.5">
                {worker1Data.speed}
              </div>
            )}
          </div>
        </div>

        {/* NODE 2: WORKER 02 (Top-Right) */}
        <div
          onClick={() => {
            setSelectedNodeId('w2');
            const w = workers[1];
            if (w && onSelectWorker) onSelectWorker(w);
          }}
          className={`absolute right-[7%] sm:right-[12%] lg:right-[14%] top-[6%] sm:top-[8%] z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.03]`}
        >
          <div
            className={`w-36 h-36 sm:w-44 sm:h-44 rounded-full bg-[#121214] flex flex-col items-center justify-center p-3 text-center transition-all duration-300 shadow-xl border-2 ${
              worker2Data.stateType === 'ok'
                ? 'border-emerald-500 shadow-emerald-500/10'
                : 'border-amber-400 shadow-amber-400/10'
            }`}
          >
            {/* Retro-modern Computer/Workstation Illustration */}
            <div className="relative mb-1">
              <svg className="w-10 h-10 sm:w-11 sm:h-11" viewBox="0 0 64 64" fill="none">
                <rect x="12" y="10" width="40" height="28" rx="4" fill="#1e293b" stroke="#64748b" strokeWidth="2.5" />
                <rect x="17" y="15" width="30" height="18" rx="1.5" fill="#0f172a" />
                <line x1="20" y1="20" x2="38" y2="20" stroke={worker2Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                <line x1="20" y1="25" x2="32" y2="25" stroke={worker2Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                <path d="M 28 38 L 36 38 L 38 43 L 26 43 Z" fill="#475569" />
                <rect x="10" y="43" width="44" height="9" rx="2" fill="#334155" stroke="#475569" strokeWidth="1.5" />
                <circle cx="48" cy="47.5" r="1.5" fill={worker2Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} />
                <line x1="16" y1="47.5" x2="28" y2="47.5" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>

            <div className="text-xs sm:text-sm font-semibold text-[#f3f3f4] group-hover:text-white transition-colors">
              Worker 02
            </div>

            <div
              className={`text-xs sm:text-[13px] font-medium mt-0.5 transition-colors ${
                worker2Data.stateType === 'ok' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {worker2Data.status}
            </div>

            {worker2Data.speed && (
              <div className="text-[11px] sm:text-xs font-mono text-amber-300 mt-0.5">
                {worker2Data.speed}
              </div>
            )}
          </div>
        </div>

        {/* NODE 3: CENTER SERVER (Cloud Server in Phase 1 / Parameter Server in Phase 2, 3, 4) */}
        <div
          onClick={() => {
            setSelectedNodeId(centerServerData.isCloud ? 'cloud' : 'ps');
            if (onOpenServerDetails) onOpenServerDetails();
          }}
          className="absolute left-1/2 top-[44%] sm:top-[43%] -translate-x-1/2 -translate-y-1/2 z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.03]"
        >
          {centerServerData.isCloud ? (
            /* Cloud Server Shape (Image 1) */
            <div className="relative w-48 h-36 sm:w-56 sm:h-40 flex flex-col items-center justify-center p-3 text-center">
              {/* Organic Cloud SVG background */}
              <svg className="absolute inset-0 w-full h-full drop-shadow-xl" viewBox="0 0 200 130" fill="none">
                <path
                  d="M 50 95 
                     L 155 95 
                     A 28 28 0 0 0 170 42 
                     A 34 34 0 0 0 132 20 
                     A 42 42 0 0 0 68 28 
                     A 30 30 0 0 0 35 68 
                     A 28 28 0 0 0 50 95 Z"
                  fill="#182234"
                  stroke="#38bdf8"
                  strokeWidth="2.5"
                />
              </svg>

              {/* Cloud Server Content */}
              <div className="relative z-10 flex flex-col items-center justify-center -mt-2">
                <CloudIcon className="w-8 h-8 text-sky-400 mb-1" />
                <div className="text-sm sm:text-base font-semibold text-[#f3f3f4]">
                  Cloud Server
                </div>
                <div className="text-xs text-sky-300 font-medium mt-0.5">
                  Distributing Datasets
                </div>
                <div className="text-[10px] text-[#94a3b8] font-mono mt-0.5">
                  CIFAR-10 (50k items)
                </div>
              </div>
            </div>
          ) : (
            /* Parameter Server Circle with Server Rack Icon (Image 2, 3, 4) */
            <div
              className={`w-40 h-40 sm:w-48 sm:h-48 rounded-full bg-[#121214] flex flex-col items-center justify-center p-3 text-center transition-all duration-300 shadow-2xl border-2 ${centerServerData.borderClass}`}
            >
              {/* Server Rack Illustration */}
              <div className="relative mb-1">
                <svg className="w-10 h-10 sm:w-11 sm:h-11" viewBox="0 0 64 64" fill="none">
                  {/* Outer rack chassis */}
                  <rect x="18" y="10" width="28" height="44" rx="2" fill="#1e293b" stroke="#64748b" strokeWidth="2" />
                  {/* Rack units / bays */}
                  <rect x="22" y="14" width="20" height="6" rx="1" fill="#0f172a" />
                  <circle cx="25" cy="17" r="1" fill="#10b981" />
                  <line x1="28" y1="17" x2="38" y2="17" stroke="#475569" strokeWidth="1" />

                  <rect x="22" y="23" width="20" height="6" rx="1" fill="#0f172a" />
                  <circle cx="25" cy="26" r="1" fill={centerServerData.stateType === 'ok' ? '#10b981' : '#f59e0b'} />
                  <line x1="28" y1="26" x2="38" y2="26" stroke="#475569" strokeWidth="1" />

                  <rect x="22" y="32" width="20" height="6" rx="1" fill="#0f172a" />
                  <circle cx="25" cy="35" r="1" fill="#10b981" />
                  <line x1="28" y1="35" x2="38" y2="35" stroke="#475569" strokeWidth="1" />

                  {/* Mesh grill base */}
                  <rect x="22" y="41" width="20" height="9" rx="1" fill="#334155" />
                  <line x1="24" y1="44" x2="38" y2="44" stroke="#475569" strokeWidth="1" strokeDasharray="1 1" />
                  <line x1="24" y1="47" x2="38" y2="47" stroke="#475569" strokeWidth="1" strokeDasharray="1 1" />
                </svg>
              </div>

              <div className="text-xs sm:text-sm font-semibold text-[#f3f3f4] group-hover:text-white transition-colors leading-tight">
                Parameter Server
              </div>

              {/* Status text matching images: Syncing: 1/3 Workers / Syncing... / Sync OK */}
              <div
                className={`text-xs sm:text-[13px] font-medium mt-1 leading-tight ${centerServerData.textColor}`}
              >
                {centerServerData.status}
              </div>

              {/* Substatus: Wait: 8ms / Aggregating / Broadcasting */}
              <div
                className={`text-[11px] sm:text-xs font-mono mt-0.5 leading-tight ${centerServerData.textColor}`}
              >
                {centerServerData.substatus}
              </div>
            </div>
          )}
        </div>

        {/* NODE 4: WORKER 03 (Bottom-Center) */}
        <div
          onClick={() => {
            setSelectedNodeId('w3');
            const w = workers[2];
            if (w && onSelectWorker) onSelectWorker(w);
          }}
          className={`absolute left-1/2 bottom-[4%] sm:bottom-[6%] -translate-x-1/2 z-20 cursor-pointer group transition-transform duration-200 hover:scale-[1.03]`}
        >
          <div
            className={`w-36 h-36 sm:w-44 sm:h-44 rounded-full bg-[#121214] flex flex-col items-center justify-center p-3 text-center transition-all duration-300 shadow-xl border-2 ${
              worker3Data.stateType === 'ok'
                ? 'border-emerald-500 shadow-emerald-500/10'
                : 'border-amber-400 shadow-amber-400/10'
            }`}
          >
            {/* Retro-modern Computer/Workstation Illustration */}
            <div className="relative mb-1">
              <svg className="w-10 h-10 sm:w-11 sm:h-11" viewBox="0 0 64 64" fill="none">
                <rect x="12" y="10" width="40" height="28" rx="4" fill="#1e293b" stroke="#64748b" strokeWidth="2.5" />
                <rect x="17" y="15" width="30" height="18" rx="1.5" fill="#0f172a" />
                <line x1="20" y1="20" x2="40" y2="20" stroke={worker3Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                <line x1="20" y1="25" x2="30" y2="25" stroke={worker3Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} strokeWidth="1.8" strokeLinecap="round" />
                <path d="M 28 38 L 36 38 L 38 43 L 26 43 Z" fill="#475569" />
                <rect x="10" y="43" width="44" height="9" rx="2" fill="#334155" stroke="#475569" strokeWidth="1.5" />
                <circle cx="48" cy="47.5" r="1.5" fill={worker3Data.stateType === 'ok' ? '#10b981' : '#f59e0b'} />
                <line x1="16" y1="47.5" x2="28" y2="47.5" stroke="#64748b" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </div>

            <div className="text-xs sm:text-sm font-semibold text-[#f3f3f4] group-hover:text-white transition-colors">
              Worker 03
            </div>

            <div
              className={`text-xs sm:text-[13px] font-medium mt-0.5 transition-colors ${
                worker3Data.stateType === 'ok' ? 'text-emerald-400' : 'text-amber-400'
              }`}
            >
              {worker3Data.status}
            </div>

            {worker3Data.speed && (
              <div className="text-[11px] sm:text-xs font-mono text-amber-300 mt-0.5">
                {worker3Data.speed}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* FOOTER METRICS SUMMARY BAR */}
      <div className="bg-[#171719] border border-white/[0.06] rounded p-3 text-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[#73737c]">Transmission Protocol:</span>
          <span className="font-mono text-[#f3f3f4] bg-white/[0.04] px-1.5 py-0.5 rounded">
            gRPC Binary Stream (DTP v1.3)
          </span>
          <span className="text-[#73737c]">·</span>
          <span className="text-[#73737c]">Strict BSP Barrier:</span>
          <span className="text-emerald-400 font-medium">3/3 Workers Active</span>
        </div>

        <div className="flex items-center gap-4 text-xs text-[#a1a1a8]">
          <div>
            <span className="text-[#73737c] mr-1.5">Avg RTT:</span>
            <span className="font-mono text-[#f3f3f4]">1.24 ms</span>
          </div>
          <div>
            <span className="text-[#73737c] mr-1.5">Network Jitter:</span>
            <span className="font-mono text-[#f3f3f4]">0.18 ms</span>
          </div>
          <div>
            <span className="text-[#73737c] mr-1.5">Model Weights:</span>
            <span className="font-mono text-[#f3f3f4]">{currentStep?.outputModelVersion || 'v3264'}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
