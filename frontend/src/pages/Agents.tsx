import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type { AgentMetadata } from '../types';
import Header from '../components/Header';
import StatusBadge from '../components/StatusBadge';
import Modal from '../components/Modal';
import JsonViewer from '../components/JsonViewer';
import ErrorAlert from '../components/ErrorAlert';
import {
  Bot,
  ShieldCheck,
  Code2,
  CheckCircle2,
  RotateCw,
  Sparkles,
  Layers,
} from 'lucide-react';

export const Agents: React.FC = () => {
  const [agents, setAgents] = useState<AgentMetadata[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Inspector modal state
  const [selectedAgent, setSelectedAgent] = useState<AgentMetadata | null>(null);

  const loadAgents = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.listAgents();
      setAgents(res || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load agent catalog');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title="Agent Catalog"
        subtitle="Registered research agents and evaluation adapters"
        onRefresh={loadAgents}
        isRefreshing={isLoading}
      />

      <main className="p-8 space-y-6 max-w-7xl mx-auto w-full">
        {error && (
          <ErrorAlert
            title="Failed to Load Agents"
            message={error}
            onRetry={loadAgents}
          />
        )}

        {/* Read-Only Notice */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-indigo-400" />
            <span>
              Showing verified registered backend agents. Custom agent registration workflow is disabled in this interface.
            </span>
          </div>
          <span className="font-mono text-slate-300">
            {agents.length} agent{agents.length === 1 ? '' : 's'} registered
          </span>
        </div>

        {/* Agents Grid */}
        {isLoading && agents.length === 0 ? (
          <div className="p-16 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
            <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
            <span>Loading agent catalog...</span>
          </div>
        ) : agents.length === 0 ? (
          <div className="p-16 text-center text-slate-400 space-y-2">
            <Bot className="h-10 w-10 text-slate-600 mx-auto" />
            <p className="text-sm text-slate-300">No registered agents found</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {agents.map((agent) => {
              const isBaseline = agent.id === 'financial_news_analysis';
              const isEgal = agent.id === 'financial_news_analysis_egal';

              return (
                <div
                  key={agent.id}
                  className={`bg-slate-900 border rounded-xl p-6 shadow-sm flex flex-col justify-between transition-all hover:border-slate-700 ${
                    isEgal
                      ? 'border-indigo-500/30 ring-1 ring-indigo-500/20'
                      : isBaseline
                      ? 'border-cyan-500/30'
                      : 'border-slate-800'
                  }`}
                >
                  <div className="space-y-4">
                    {/* Header */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div
                          className={`h-10 w-10 rounded-lg flex items-center justify-center text-white shrink-0 ${
                            isEgal
                              ? 'bg-gradient-to-tr from-indigo-600 to-purple-600 shadow-md shadow-indigo-500/20'
                              : isBaseline
                              ? 'bg-gradient-to-tr from-cyan-600 to-blue-600 shadow-md shadow-cyan-500/20'
                              : 'bg-slate-800 text-slate-300'
                          }`}
                        >
                          {isEgal ? (
                            <ShieldCheck className="h-5 w-5" />
                          ) : (
                            <Bot className="h-5 w-5" />
                          )}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-base font-semibold text-slate-100">
                              {agent.display_name || agent.name}
                            </h3>
                            {isEgal && (
                              <span className="text-[10px] bg-indigo-500/20 text-indigo-300 font-semibold px-2 py-0.5 rounded-full border border-indigo-500/30">
                                EGAL Guardrails
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-400 font-mono mt-0.5">{agent.id}</p>
                        </div>
                      </div>

                      <StatusBadge status={agent.status} size="sm" />
                    </div>

                    {/* Description */}
                    <p className="text-xs text-slate-300 leading-relaxed min-h-[36px]">
                      {agent.description || 'No description provided.'}
                    </p>

                    {/* Metadata & Capabilities */}
                    <div className="space-y-2 pt-2 border-t border-slate-800/80 text-xs">
                      <div className="flex items-center justify-between text-slate-400">
                        <span>Version</span>
                        <span className="font-mono text-slate-200">v{agent.version || '1.0.0'}</span>
                      </div>
                      <div className="flex items-center justify-between text-slate-400">
                        <span>Adapter Type</span>
                        <span className="text-slate-200 capitalize">
                          {agent.is_builtin ? 'Built-in Research Adapter' : 'Custom Registered'}
                        </span>
                      </div>

                      {agent.capabilities && agent.capabilities.length > 0 && (
                        <div className="pt-2">
                          <span className="text-[11px] font-medium text-slate-400 block mb-1.5">
                            Capabilities
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {agent.capabilities.map((cap) => (
                              <span
                                key={cap}
                                className="px-2 py-0.5 rounded bg-slate-800/80 text-slate-300 text-[10px] border border-slate-700/60 font-mono"
                              >
                                {cap}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Schema Inspector Action */}
                  <div className="pt-5 mt-4 border-t border-slate-800 flex items-center justify-between">
                    <span className="text-[11px] text-slate-400 flex items-center gap-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      <span>Ready for evaluation</span>
                    </span>
                    <button
                      onClick={() => setSelectedAgent(agent)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 transition-colors"
                    >
                      <Code2 className="h-3.5 w-3.5 text-indigo-400" />
                      <span>Inspect Schemas</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Agent Schema Inspector Modal */}
      <Modal
        isOpen={!!selectedAgent}
        onClose={() => setSelectedAgent(null)}
        title={`Schemas: ${selectedAgent?.display_name || selectedAgent?.name}`}
        subtitle={`Agent ID: ${selectedAgent?.id}`}
        maxWidth="2xl"
      >
        {selectedAgent && (
          <div className="space-y-6">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Code2 className="h-4 w-4 text-indigo-400" />
                <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                  Input Schema (JSON Schema Draft 2020-12)
                </h4>
              </div>
              <JsonViewer
                data={selectedAgent.input_schema || { note: 'No input schema declared' }}
                maxHeight="max-h-56"
              />
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <Code2 className="h-4 w-4 text-emerald-400" />
                <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-200">
                  Output Schema (JSON Schema Draft 2020-12)
                </h4>
              </div>
              <JsonViewer
                data={selectedAgent.output_schema || { note: 'No output schema declared' }}
                maxHeight="max-h-56"
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default Agents;
