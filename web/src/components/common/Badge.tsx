import React from 'react';
import {
  JobState,
  AttemptState,
  CheckpointState,
  DatasetBuildState,
  WorkerState,
  StepState,
  EventSeverity,
  SubsystemStatus,
} from '../../types';

interface BadgeProps {
  children?: React.ReactNode;
  variant?:
    | 'default'
    | 'success'
    | 'warning'
    | 'danger'
    | 'info'
    | 'neutral'
    | 'purple'
    | 'green'
    | 'amber'
    | 'blue'
    | 'red';
  size?: 'sm' | 'md';
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  children,
  variant = 'default',
  size = 'md',
  className = '',
}) => {
  const sizeClasses = size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs font-normal';

  const variantMap: Record<string, string> = {
    default: 'bg-[#171719] text-[#a1a1a8] border border-white/[0.07]',
    neutral: 'bg-[#171719] text-[#a1a1a8] border border-white/[0.07]',
    success: 'bg-emerald-950/20 text-emerald-400 border border-emerald-800/30',
    green: 'bg-emerald-950/20 text-emerald-400 border border-emerald-800/30',
    warning: 'bg-amber-950/20 text-amber-400 border border-amber-800/30',
    amber: 'bg-amber-950/20 text-amber-400 border border-amber-800/30',
    danger: 'bg-rose-950/20 text-rose-400 border border-rose-800/30',
    red: 'bg-rose-950/20 text-rose-400 border border-rose-800/30',
    info: 'bg-blue-950/20 text-blue-400 border border-blue-800/30',
    blue: 'bg-blue-950/20 text-blue-400 border border-blue-800/30',
    purple: 'bg-[#171719] text-[#a1a1a8] border border-white/[0.07]',
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded whitespace-nowrap leading-none select-none font-sans ${sizeClasses} ${variantMap[variant] || variantMap.default} ${className}`}
    >
      {children}
    </span>
  );
};

export const StatusDot: React.FC<{
  status: 'healthy' | 'warning' | 'error' | 'inactive';
  pulse?: boolean;
}> = ({ status, pulse = false }) => {
  const colorMap = {
    healthy: 'bg-emerald-400',
    warning: 'bg-amber-400',
    error: 'bg-rose-400',
    inactive: 'bg-zinc-500',
  };

  return (
    <span className="relative flex h-1.5 w-1.5 shrink-0">
      {pulse && status === 'healthy' && (
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
      )}
      {pulse && status === 'warning' && (
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
      )}
      <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${colorMap[status]}`} />
    </span>
  );
};

export const JobStateBadge: React.FC<{ state: JobState }> = ({ state }) => {
  switch (state) {
    case 'READY':
      return (
        <Badge variant="neutral">
          <span className="text-[#f3f3f4]">Ready</span>
        </Badge>
      );
    case 'DRAFT':
      return <Badge variant="neutral">Draft</Badge>;
    case 'ARCHIVED':
      return <Badge variant="neutral">Archived</Badge>;
    default:
      return <Badge variant="neutral">{state}</Badge>;
  }
};

export const AttemptStateBadge: React.FC<{ state: AttemptState; pulse?: boolean }> = ({
  state,
  pulse = true,
}) => {
  switch (state) {
    case 'RUNNING':
      return (
        <Badge variant="info">
          {pulse && <StatusDot status="healthy" pulse />}
          Running
        </Badge>
      );
    case 'COMPLETED':
      return (
        <Badge variant="success">
          <StatusDot status="healthy" />
          Completed
        </Badge>
      );
    case 'FAILED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Failed
        </Badge>
      );
    case 'ABORTED':
      return (
        <Badge variant="neutral">
          <StatusDot status="inactive" />
          Aborted
        </Badge>
      );
    case 'WAITING_WORKERS':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Waiting for workers
        </Badge>
      );
    case 'PROVISIONING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Provisioning
        </Badge>
      );
    case 'INITIALIZING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Initializing
        </Badge>
      );
    case 'COMPLETING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Completing
        </Badge>
      );
    case 'CREATED':
    default:
      return <Badge variant="neutral">Created</Badge>;
  }
};

export const CheckpointStateBadge: React.FC<{ state: CheckpointState }> = ({ state }) => {
  switch (state) {
    case 'COMPLETE':
      return (
        <Badge variant="success">
          <StatusDot status="healthy" />
          Complete
        </Badge>
      );
    case 'WRITING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Writing
        </Badge>
      );
    case 'FAILED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Failed
        </Badge>
      );
    default:
      return <Badge>{state}</Badge>;
  }
};

export const DatasetBuildStateBadge: React.FC<{ state: DatasetBuildState }> = ({ state }) => {
  switch (state) {
    case 'READY':
      return (
        <Badge variant="success">
          <StatusDot status="healthy" />
          Ready
        </Badge>
      );
    case 'MATERIALIZING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          Materializing
        </Badge>
      );
    case 'IMPORTING':
    case 'PREPROCESSING':
    case 'VALIDATING':
    case 'VERIFYING':
    case 'REGISTERING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          {state.charAt(0) + state.slice(1).toLowerCase()}
        </Badge>
      );
    case 'FAILED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Failed
        </Badge>
      );
    case 'DEPRECATED':
      return <Badge variant="neutral">Deprecated</Badge>;
    case 'DELETING':
    case 'DELETED':
      return <Badge variant="danger">{state.toLowerCase()}</Badge>;
    case 'CREATED':
    case 'QUEUED':
    default:
      return <Badge variant="neutral">{state.toLowerCase()}</Badge>;
  }
};

export const WorkerStateBadge: React.FC<{ state: WorkerState }> = ({ state }) => {
  switch (state) {
    case 'READY':
      return (
        <Badge variant="success">
          <StatusDot status="healthy" />
          Ready
        </Badge>
      );
    case 'MODEL_SYNCING':
      return (
        <Badge variant="info">
          <StatusDot status="warning" pulse />
          Syncing model
        </Badge>
      );
    case 'SHARD_READY':
      return (
        <Badge variant="info">
          <StatusDot status="healthy" />
          Shard ready
        </Badge>
      );
    case 'PROVISIONING':
    case 'REGISTERING':
    case 'CONNECTING':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" pulse />
          {state.charAt(0) + state.slice(1).toLowerCase()}
        </Badge>
      );
    case 'DISCONNECTED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Disconnected
        </Badge>
      );
    case 'FAILED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Failed
        </Badge>
      );
    default:
      return <Badge variant="neutral">{state}</Badge>;
  }
};

export const StepStateBadge: React.FC<{ state: StepState }> = ({ state }) => {
  switch (state) {
    case 'COMMITTED':
      return <Badge variant="success">Committed</Badge>;
    case 'COLLECTING_GRADIENTS':
      return <Badge variant="warning">Collecting gradients</Badge>;
    case 'WAITING_PARAMETER_APPLIED':
      return <Badge variant="warning">Applying new parameters</Badge>;
    case 'AGGREGATING':
      return <Badge variant="info">Aggregating</Badge>;
    case 'UPDATING':
      return <Badge variant="info">Updating model</Badge>;
    case 'BROADCASTING':
      return <Badge variant="info">Broadcasting</Badge>;
    case 'CHECKPOINTING':
      return <Badge variant="warning">Saving checkpoint</Badge>;
    case 'CREATED':
    case 'DISPATCHED':
    default:
      return <Badge variant="neutral">{state}</Badge>;
  }
};

export const SubsystemHealthBadge: React.FC<{ status: SubsystemStatus }> = ({ status }) => {
  switch (status) {
    case 'HEALTHY':
      return (
        <Badge variant="success">
          <StatusDot status="healthy" />
          Healthy
        </Badge>
      );
    case 'DEGRADED':
      return (
        <Badge variant="warning">
          <StatusDot status="warning" />
          Degraded
        </Badge>
      );
    case 'DISCONNECTED':
      return (
        <Badge variant="danger">
          <StatusDot status="error" />
          Disconnected
        </Badge>
      );
  }
};

export const SeverityBadge: React.FC<{ severity: EventSeverity }> = ({ severity }) => {
  switch (severity) {
    case 'INFO':
      return <Badge variant="neutral">Info</Badge>;
    case 'WARN':
      return <Badge variant="warning">Warning</Badge>;
    case 'ERROR':
      return <Badge variant="danger">Error</Badge>;
    case 'CRITICAL':
      return <Badge variant="danger">Critical</Badge>;
  }
};
