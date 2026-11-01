import React from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface MetricCardProps {
  label: string;
  value: string | number | null | undefined;
  subtext?: string;
  delta?: number | null;
  direction?: 'higher_is_better' | 'lower_is_better' | 'neutral';
  numerator?: number | null;
  denominator?: number | null;
  sampleSize?: number | null;
  icon?: React.ReactNode;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subtext,
  delta,
  direction = 'higher_is_better',
  numerator,
  denominator,
  sampleSize,
  icon,
}) => {
  const displayVal =
    value === null || value === undefined
      ? '—'
      : typeof value === 'number'
      ? value % 1 !== 0
        ? (value * 100).toFixed(1) + '%'
        : String(value)
      : String(value);

  // Determine delta badge color
  let isPositive = false;
  let isNeutral = true;

  if (delta !== undefined && delta !== null && delta !== 0) {
    isNeutral = false;
    if (direction === 'higher_is_better') {
      isPositive = delta > 0;
    } else if (direction === 'lower_is_better') {
      isPositive = delta < 0; // Lower is better! E.g. Lower false success is improvement
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700/80 transition-all">
      <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
        <span className="truncate">{label}</span>
        {icon && <div className="text-slate-400">{icon}</div>}
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-bold text-slate-100 tracking-tight">
          {displayVal}
        </span>

        {delta !== undefined && delta !== null && (
          <div
            className={`inline-flex items-center gap-0.5 text-xs font-semibold px-2 py-0.5 rounded-full ${
              isNeutral
                ? 'bg-slate-800 text-slate-400'
                : isPositive
                ? 'bg-emerald-500/15 text-emerald-400'
                : 'bg-rose-500/15 text-rose-400'
            }`}
          >
            {isNeutral ? (
              <Minus className="h-3 w-3" />
            ) : delta > 0 ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            <span>
              {delta > 0 ? `+${(delta * 100).toFixed(1)}%` : `${(delta * 100).toFixed(1)}%`}
            </span>
          </div>
        )}
      </div>

      {/* Numerator / Denominator / Sample size or subtext */}
      <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400 border-t border-slate-800/80 pt-2">
        <span>
          {numerator !== undefined && denominator !== undefined && numerator !== null && denominator !== null ? (
            <span>
              Ratio: <strong className="text-slate-300">{numerator}</strong> /{' '}
              <strong className="text-slate-300">{denominator}</strong>
            </span>
          ) : sampleSize !== undefined && sampleSize !== null ? (
            <span>N = <strong className="text-slate-300">{sampleSize}</strong></span>
          ) : (
            subtext || '—'
          )}
        </span>
        {direction !== 'neutral' && (
          <span className="text-[10px] text-slate-400 uppercase tracking-wider">
            {direction === 'higher_is_better' ? 'Higher is better' : 'Lower is better'}
          </span>
        )}
      </div>
    </div>
  );
};

export default MetricCard;
