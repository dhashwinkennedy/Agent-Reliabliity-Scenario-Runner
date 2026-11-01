import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { parseError } from '../utils/error';

interface ErrorAlertProps {
  title?: string;
  message: unknown;
  code?: string;
  onRetry?: () => void;
  className?: string;
}

export const ErrorAlert: React.FC<ErrorAlertProps> = ({
  title = 'An error occurred',
  message,
  code,
  onRetry,
  className = '',
}) => {
  const parsed = parseError(message);
  const displayCode = code || parsed.code;
  const displayMessage = parsed.message || (displayCode ? `Error code: ${displayCode}` : 'An unexpected error occurred');

  return (
    <div
      className={`p-4 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-200 flex items-start gap-3 ${className}`}
    >
      <AlertCircle className="h-5 w-5 text-rose-400 shrink-0 mt-0.5" />
      <div className="flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <h4 className="text-sm font-semibold text-rose-300">{title}</h4>
          {displayCode && (
            <span className="text-[10px] font-mono uppercase bg-rose-950/60 border border-rose-800/60 px-1.5 py-0.5 rounded text-rose-300">
              {displayCode}
            </span>
          )}
        </div>
        <p className="text-xs text-rose-200/90 mt-1 leading-relaxed break-words">{displayMessage}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-900/60 hover:bg-rose-800/80 border border-rose-700/60 rounded-lg text-xs font-medium text-rose-100 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            <span>Try Again</span>
          </button>
        )}
      </div>
    </div>
  );
};

export default ErrorAlert;
