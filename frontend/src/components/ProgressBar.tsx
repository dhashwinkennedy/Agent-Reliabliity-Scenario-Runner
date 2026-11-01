import React from 'react';

interface ProgressBarProps {
  completed: number;
  failed?: number;
  total: number;
  status?: string;
  size?: 'sm' | 'md';
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  completed,
  failed = 0,
  total,
  status = 'running',
  size = 'md',
}) => {
  const safeTotal = Math.max(1, total);
  const completedPercent = Math.min(100, Math.round((completed / safeTotal) * 100));
  const failedPercent = Math.min(100, Math.round((failed / safeTotal) * 100));
  const height = size === 'sm' ? 'h-1.5' : 'h-2.5';

  return (
    <div className="w-full space-y-1.5">
      <div className="flex justify-between items-center text-xs">
        <span className="text-slate-400 font-medium">
          {completed + failed} / {total} runs ({completedPercent}%)
        </span>
        {failed > 0 && (
          <span className="text-rose-400 text-xs font-medium">
            {failed} failed
          </span>
        )}
      </div>

      <div className={`w-full ${height} bg-slate-800 rounded-full overflow-hidden flex`}>
        {completedPercent > 0 && (
          <div
            style={{ width: `${completedPercent}%` }}
            className={`transition-all duration-300 ${
              status === 'completed'
                ? 'bg-emerald-500'
                : 'bg-indigo-500'
            }`}
          />
        )}
        {failedPercent > 0 && (
          <div
            style={{ width: `${failedPercent}%` }}
            className="bg-rose-500 transition-all duration-300"
          />
        )}
      </div>
    </div>
  );
};

export default ProgressBar;
