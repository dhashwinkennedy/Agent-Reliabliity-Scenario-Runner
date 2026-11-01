import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { Activity, RefreshCw } from 'lucide-react';

interface HeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  subtitle,
  actions,
  onRefresh,
  isRefreshing = false,
}) => {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking');
  const [lastChecked, setLastChecked] = useState<string>('');

  const checkHealth = async () => {
    try {
      await api.getHealth();
      setBackendStatus('connected');
      setLastChecked(new Date().toLocaleTimeString());
    } catch {
      setBackendStatus('disconnected');
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-16 bg-slate-900/60 backdrop-blur-md border-b border-slate-800 px-8 flex items-center justify-between shrink-0 sticky top-0 z-10">
      <div>
        <h2 className="text-lg font-semibold text-slate-100 tracking-tight">{title}</h2>
        {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
      </div>

      <div className="flex items-center gap-4">
        {/* Backend Status Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700/60 text-xs">
          <Activity
            className={`h-3.5 w-3.5 ${
              backendStatus === 'connected'
                ? 'text-emerald-400 animate-pulse'
                : backendStatus === 'disconnected'
                ? 'text-rose-400'
                : 'text-amber-400'
            }`}
          />
          <span className="text-slate-300 font-medium">
            {backendStatus === 'connected'
              ? 'API Connected'
              : backendStatus === 'disconnected'
              ? 'API Disconnected'
              : 'Connecting...'}
          </span>
          {lastChecked && (
            <span className="text-slate-400 text-[10px] hidden sm:inline">
              ({lastChecked})
            </span>
          )}
        </div>

        {/* Refresh button if available */}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors border border-slate-700 disabled:opacity-50"
            title="Refresh Data"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        )}

        {/* Page Actions */}
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
};

export default Header;
