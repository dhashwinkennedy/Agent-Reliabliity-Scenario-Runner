import React, { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Dataset, AgentMetadata, Provider, Experiment } from '../types';
import Header from '../components/Header';
import StatusBadge from '../components/StatusBadge';
import ProgressBar from '../components/ProgressBar';
import ErrorAlert from '../components/ErrorAlert';
import {
  Database,
  Bot,
  Cpu,
  FlaskConical,
  Activity,
  ArrowRight,
  PlusCircle,
  Play,
  RotateCw,
} from 'lucide-react';

export const Dashboard: React.FC = () => {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [agents, setAgents] = useState<AgentMetadata[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [apiHealth, setApiHealth] = useState<{ status: string; version?: string } | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [healthRes, datasetsRes, agentsRes, providersRes, experimentsRes] = await Promise.all([
        api.getHealth().catch(() => ({ status: 'unreachable' })),
        api.listDatasets({ limit: 100 }),
        api.listAgents(),
        api.listProviders(),
        api.listExperiments(),
      ]);

      setApiHealth(healthRes);
      setDatasets(datasetsRes?.items || []);
      setAgents(Array.isArray(agentsRes) ? agentsRes : (agentsRes as unknown as { items?: AgentMetadata[] })?.items || []);
      setProviders(Array.isArray(providersRes) ? providersRes : (providersRes as unknown as { items?: Provider[] })?.items || []);
      setExperiments(Array.isArray(experimentsRes) ? experimentsRes : (experimentsRes as unknown as { items?: Experiment[] })?.items || []);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load dashboard data';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Compute safe stats
  const safeDatasets = Array.isArray(datasets) ? datasets : [];
  const safeAgents = Array.isArray(agents) ? agents : [];
  const safeProviders = Array.isArray(providers) ? providers : [];
  const safeExperiments = Array.isArray(experiments) ? experiments : [];

  const totalSnapshots = safeDatasets.reduce((acc, d) => acc + (d.snapshots?.length || 0), 0);
  const activeExperiments = safeExperiments.filter((e) => e.status === 'running' || e.status === 'queued');
  const completedExperiments = safeExperiments.filter((e) => e.status === 'completed');

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title="Research Arena Dashboard"
        subtitle="Live platform overview and evaluation activities"
        onRefresh={loadData}
        isRefreshing={isLoading}
        actions={
          <Link
            to="/experiments?action=create"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
          >
            <PlusCircle className="h-4 w-4" />
            <span>Create Experiment</span>
          </Link>
        }
      />

      <main className="p-8 space-y-8 max-w-7xl mx-auto w-full">
        {error && (
          <ErrorAlert
            title="Dashboard Synchronization Error"
            message={error}
            onRetry={loadData}
          />
        )}

        {/* Top 5 Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {/* 1. API Status */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
              <span>API Status</span>
              <Activity
                className={`h-4 w-4 ${
                  apiHealth?.status === 'ok' || apiHealth?.status === 'healthy'
                    ? 'text-emerald-400'
                    : 'text-amber-400'
                }`}
              />
            </div>
            <div className="text-xl font-bold text-slate-100 capitalize">
              {apiHealth?.status || 'Unknown'}
            </div>
            <div className="mt-2 text-xs text-slate-400">
              {apiHealth?.version ? `v${apiHealth.version}` : 'FastAPI Platform'}
            </div>
          </div>

          {/* 2. Datasets */}
          <Link
            to="/datasets"
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition-colors block group"
          >
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
              <span>Datasets</span>
              <Database className="h-4 w-4 text-cyan-400 group-hover:scale-110 transition-transform" />
            </div>
            <div className="text-2xl font-bold text-slate-100">{safeDatasets.length}</div>
            <div className="mt-2 text-xs text-slate-400">
              {totalSnapshots} immutable snapshot{totalSnapshots === 1 ? '' : 's'}
            </div>
          </Link>

          {/* 3. Registered Agents */}
          <Link
            to="/agents"
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition-colors block group"
          >
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
              <span>Agents</span>
              <Bot className="h-4 w-4 text-indigo-400 group-hover:scale-110 transition-transform" />
            </div>
            <div className="text-2xl font-bold text-slate-100">{safeAgents.length}</div>
            <div className="mt-2 text-xs text-slate-400">Baseline & EGAL included</div>
          </Link>

          {/* 4. Providers */}
          <Link
            to="/providers"
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition-colors block group"
          >
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
              <span>Providers</span>
              <Cpu className="h-4 w-4 text-amber-400 group-hover:scale-110 transition-transform" />
            </div>
            <div className="text-2xl font-bold text-slate-100">{safeProviders.length}</div>
            <div className="mt-2 text-xs text-slate-400">Configured LLM backends</div>
          </Link>

          {/* 5. Experiments */}
          <Link
            to="/experiments"
            className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm hover:border-slate-700 transition-colors block group"
          >
            <div className="flex items-center justify-between text-xs text-slate-400 font-medium mb-2">
              <span>Experiments</span>
              <FlaskConical className="h-4 w-4 text-emerald-400 group-hover:scale-110 transition-transform" />
            </div>
            <div className="text-2xl font-bold text-slate-100">{safeExperiments.length}</div>
            <div className="mt-2 text-xs text-slate-400">
              {activeExperiments.length} active • {completedExperiments.length} completed
            </div>
          </Link>
        </div>

        {/* Quick Launch & Guidance Banner */}
        <div className="bg-gradient-to-r from-indigo-950/60 via-slate-900 to-slate-900 border border-indigo-900/40 rounded-xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <h3 className="text-base font-semibold text-slate-100">
              Experiment Repetitions & Baseline–EGAL Grouping
            </h3>
            <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
              Launch isolated single-condition or paired Baseline versus EGAL experiments.
              Rerun any experiment from its detail page with frozen configuration preservation and
              automatic evaluation without overwriting historical runs.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <Link
              to="/experiments"
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors shadow-sm"
            >
              <span>View Experiments</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              to="/analytics"
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors border border-slate-700"
            >
              <span>View Analytics</span>
            </Link>
          </div>
        </div>

        {/* Recent Experiments Section */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Recent Experiments</h3>
              <p className="text-xs text-slate-400">Latest executions and current progress</p>
            </div>
            <Link
              to="/experiments"
              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-1 transition-colors"
            >
              <span>View all</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {isLoading ? (
            <div className="p-12 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
              <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
              <span>Loading experiments...</span>
            </div>
          ) : safeExperiments.length === 0 ? (
            <div className="p-12 text-center text-slate-400 space-y-3">
              <FlaskConical className="h-8 w-8 text-slate-600 mx-auto" />
              <p className="text-sm text-slate-300">No experiments executed yet</p>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                Create your first experiment or comparison group to evaluate agents on financial news.
              </p>
              <Link
                to="/experiments?action=create"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold transition-colors mt-2"
              >
                <PlusCircle className="h-3.5 w-3.5" />
                <span>Create Experiment</span>
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-slate-800/80">
              {safeExperiments.slice(0, 5).map((exp) => (
                <div
                  key={exp.id}
                  className="p-5 hover:bg-slate-800/40 transition-colors flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
                >
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link
                        to={`/experiments/${exp.id}`}
                        className="text-sm font-medium text-slate-200 hover:text-indigo-400 transition-colors truncate"
                      >
                        {exp.name}
                      </Link>
                      <StatusBadge status={exp.status} size="sm" />
                      {exp.group_name && (
                        <span className="text-[10px] bg-slate-800 text-indigo-300 px-2 py-0.5 rounded border border-indigo-900/50">
                          Group: {exp.group_name}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap">
                      <span>Agent: <strong className="text-slate-300">{exp.agent_id}</strong></span>
                      <span>•</span>
                      <span>Model: <strong className="text-slate-300">{exp.model}</strong></span>
                      <span>•</span>
                      <span>Repetitions: <strong className="text-slate-300">{exp.repetition_count || 1}</strong></span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0 w-full sm:w-auto justify-end">
                    <Link
                      to={`/experiments/${exp.id}`}
                      className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition-colors"
                    >
                      View Details
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default Dashboard;
