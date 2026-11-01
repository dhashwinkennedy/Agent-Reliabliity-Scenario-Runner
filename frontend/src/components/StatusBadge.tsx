import React from 'react';
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  XCircle,
  PauseCircle,
  StopCircle,
  FileQuestion,
  Loader2,
} from 'lucide-react';

export type BadgeStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'stopped'
  | 'pending'
  | 'valid'
  | 'invalid'
  | 'warning'
  | 'ready';

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md';
  showIcon?: boolean;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  size = 'md',
  showIcon = true,
}) => {
  const norm = (status || '').toLowerCase() as BadgeStatus;

  let bg = 'bg-slate-800 text-slate-300 border-slate-700';
  let Icon = FileQuestion;

  switch (norm) {
    case 'completed':
    case 'valid':
    case 'ready':
      bg = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25';
      Icon = CheckCircle2;
      break;
    case 'running':
      bg = 'bg-indigo-500/15 text-indigo-400 border-indigo-500/30';
      Icon = Loader2;
      break;
    case 'queued':
    case 'pending':
    case 'draft':
      bg = 'bg-slate-700/40 text-slate-300 border-slate-600/40';
      Icon = Clock;
      break;
    case 'paused':
      bg = 'bg-amber-500/10 text-amber-400 border-amber-500/25';
      Icon = PauseCircle;
      break;
    case 'stopped':
      bg = 'bg-neutral-800 text-neutral-300 border-neutral-700';
      Icon = StopCircle;
      break;
    case 'failed':
    case 'invalid':
      bg = 'bg-rose-500/10 text-rose-400 border-rose-500/25';
      Icon = XCircle;
      break;
    case 'warning':
      bg = 'bg-amber-500/10 text-amber-400 border-amber-500/25';
      Icon = AlertTriangle;
      break;
    default:
      bg = 'bg-slate-800 text-slate-300 border-slate-700';
      Icon = FileQuestion;
      break;
  }

  const padding = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';
  const iconSize = size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-medium rounded-full border ${padding} ${bg} capitalize tracking-tight select-none`}
    >
      {showIcon && (
        <Icon
          className={`${iconSize} shrink-0 ${norm === 'running' ? 'animate-spin' : ''}`}
        />
      )}
      <span>{status || 'Unknown'}</span>
    </span>
  );
};

export default StatusBadge;
