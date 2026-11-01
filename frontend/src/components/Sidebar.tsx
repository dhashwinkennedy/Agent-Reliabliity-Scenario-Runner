import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Database,
  Bot,
  Cpu,
  FlaskConical,
  BarChart3,
  Sparkles,
} from 'lucide-react';

interface NavItem {
  name: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { name: 'Dashboard', path: '/', icon: LayoutDashboard },
  { name: 'Datasets', path: '/datasets', icon: Database },
  { name: 'Agents', path: '/agents', icon: Bot },
  { name: 'Providers', path: '/providers', icon: Cpu },
  { name: 'Experiments', path: '/experiments', icon: FlaskConical },
  { name: 'Analytics', path: '/analytics', icon: BarChart3 },
];

export const Sidebar: React.FC = () => {
  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col shrink-0 select-none">
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 gap-3 border-b border-slate-800">
        <div className="h-9 w-9 rounded-lg bg-gradient-to-tr from-indigo-600 to-cyan-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
          <FlaskConical className="h-5 w-5" />
        </div>
        <div>
          <h1 className="font-semibold text-slate-100 text-base leading-tight tracking-tight">
            Research Arena
          </h1>
          <p className="text-xs text-indigo-400 font-medium">Evaluation Platform</p>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Platform
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600/15 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`
            }
          >
            <item.icon className="h-4 w-4 shrink-0" />
            <span>{item.name}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer Info */}
      <div className="p-4 border-t border-slate-800 text-xs text-slate-500">
        <div className="flex items-center gap-2 text-slate-400 font-medium mb-1">
          <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
          <span>Baseline & EGAL</span>
        </div>
        <p className="text-[11px] text-slate-400">
          Repetition & Provenance Isolated
        </p>
      </div>
    </aside>
  );
};

export default Sidebar;
