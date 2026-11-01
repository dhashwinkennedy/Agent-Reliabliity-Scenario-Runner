import React, { useState } from 'react';
import type { Experiment, ExperimentGroup } from '../../types';
import StatusBadge from '../StatusBadge';
import {
  FlaskConical,
  ShieldCheck,
  Bot,
  RotateCcw,
  Eye,
  Layers,
  ArrowRight,
  Sparkles,
} from 'lucide-react';

interface ExperimentListProps {
  experiments: Experiment[];
  groups: ExperimentGroup[];
  onSelectExperiment: (experimentId: string) => void;
  onRerunExperiment: (experimentId: string) => void;
  onRerunBoth?: (baselineId: string, egalId: string) => void;
  isLoading?: boolean;
}

export const ExperimentList: React.FC<ExperimentListProps> = ({
  experiments = [],
  groups = [],
  onSelectExperiment,
  onRerunExperiment,
  onRerunBoth,
  isLoading = false,
}) => {
  const safeExperiments = Array.isArray(experiments) ? experiments : [];
  const safeGroups = Array.isArray(groups) ? groups : [];

  // Build a lookup for groups
  const groupMap = new Map<string, ExperimentGroup>();
  safeGroups.forEach((g) => groupMap.set(g.id, g));

  // Partition experiments into grouped and ungrouped
  const groupedExperiments: Record<string, Experiment[]> = {};
  const ungroupedExperiments: Experiment[] = [];

  safeExperiments.forEach((exp) => {
    if (exp.group_id) {
      if (!groupedExperiments[exp.group_id]) {
        groupedExperiments[exp.group_id] = [];
      }
      groupedExperiments[exp.group_id].push(exp);
    } else {
      ungroupedExperiments.push(exp);
    }
  });

  const groupIds = Object.keys(groupedExperiments);

  if (safeExperiments.length === 0 && !isLoading) {
    return (
      <div className="p-16 text-center text-slate-400 bg-slate-900 border border-slate-800 rounded-xl space-y-3">
        <FlaskConical className="h-10 w-10 text-slate-600 mx-auto" />
        <p className="text-sm font-medium text-slate-200">No experiments available</p>
        <p className="text-xs text-slate-400">
          Create a new experiment or comparison group to begin evaluating agents.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* 1. Comparison Groups Section */}
      {groupIds.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <Layers className="h-4 w-4 text-indigo-400" />
            <span>Paired Baseline–EGAL Comparison Groups ({groupIds.length})</span>
          </div>

          <div className="space-y-4">
            {groupIds.map((gid) => {
              const groupExpList = groupedExperiments[gid];
              const groupInfo = groupMap.get(gid);
              const groupName =
                groupInfo?.name || groupExpList[0]?.group_name || groupExpList[0]?.name || 'Comparison Group';

              const baselineExp = groupExpList.find(
                (e) => e.agent_id === 'financial_news_analysis'
              );
              const egalExp = groupExpList.find(
                (e) => e.agent_id === 'financial_news_analysis_egal'
              );

              return (
                <div
                  key={gid}
                  className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm hover:border-slate-700/80 transition-colors"
                >
                  {/* Group Header */}
                  <div className="px-6 py-4 bg-slate-950/60 border-b border-slate-800 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <h3 className="text-base font-bold text-slate-100">{groupName}</h3>
                        <span className="text-[10px] font-mono bg-indigo-950/80 text-indigo-300 border border-indigo-800/60 px-2 py-0.5 rounded">
                          Group ID: {gid.slice(0, 10)}...
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        <span>Model: <strong className="text-slate-200">{groupExpList[0]?.model}</strong></span>
                        <span>•</span>
                        <span>Provider: <strong className="text-slate-200">{groupExpList[0]?.provider_id}</strong></span>
                        <span>•</span>
                        <span>Snapshot: <strong className="font-mono text-slate-200">{groupExpList[0]?.dataset_snapshot_id}</strong></span>
                      </div>
                    </div>

                    {/* Quick Rerun Both Action */}
                    {baselineExp && egalExp && onRerunBoth && (
                      <button
                        onClick={() => onRerunBoth(baselineExp.id, egalExp.id)}
                        className="px-3 py-1.5 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm shrink-0"
                        title="Rerun both Baseline and EGAL conditions under this group"
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                        <span>Rerun Both Conditions</span>
                      </button>
                    )}
                  </div>

                  {/* Paired Conditions Grid */}
                  <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Baseline Condition Card */}
                    {baselineExp ? (
                      <div className="p-4 bg-slate-950/80 rounded-xl border border-slate-800 flex flex-col justify-between space-y-3">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Bot className="h-4 w-4 text-cyan-400" />
                              <span className="font-semibold text-slate-200 text-xs">
                                Baseline Condition
                              </span>
                            </div>
                            <StatusBadge status={baselineExp.status} size="sm" />
                          </div>

                          <div className="text-xs text-slate-400 space-y-1">
                            <div>Agent: <span className="text-slate-300 font-mono">financial_news_analysis</span></div>
                            <div>
                              Repetitions:{' '}
                              <strong className="text-slate-200">
                                {baselineExp.repetition_count || 1}
                              </strong>
                            </div>
                          </div>
                        </div>

                        <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                          <button
                            onClick={() => onSelectExperiment(baselineExp.id)}
                            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1 transition-colors"
                          >
                            <span>Inspect Baseline</span>
                            <ArrowRight className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => onRerunExperiment(baselineExp.id)}
                            className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                            title="Rerun Baseline Repetition"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="p-4 bg-slate-950/40 rounded-xl border border-dashed border-slate-800 text-center text-xs text-slate-500 py-6">
                        No Baseline experiment linked to this group
                      </div>
                    )}

                    {/* EGAL Condition Card */}
                    {egalExp ? (
                      <div className="p-4 bg-slate-950/80 rounded-xl border border-indigo-950/60 ring-1 ring-indigo-500/20 flex flex-col justify-between space-y-3">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <ShieldCheck className="h-4 w-4 text-indigo-400" />
                              <span className="font-semibold text-indigo-300 text-xs">
                                EGAL Guardrails Condition
                              </span>
                            </div>
                            <StatusBadge status={egalExp.status} size="sm" />
                          </div>

                          <div className="text-xs text-slate-400 space-y-1">
                            <div>Agent: <span className="text-indigo-300 font-mono">financial_news_analysis_egal</span></div>
                            <div>
                              Repetitions:{' '}
                              <strong className="text-slate-200">
                                {egalExp.repetition_count || 1}
                              </strong>
                            </div>
                          </div>
                        </div>

                        <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                          <button
                            onClick={() => onSelectExperiment(egalExp.id)}
                            className="px-3 py-1.5 bg-indigo-950/80 hover:bg-indigo-900 text-indigo-200 rounded-lg text-xs font-medium border border-indigo-800/60 flex items-center gap-1 transition-colors"
                          >
                            <span>Inspect EGAL</span>
                            <ArrowRight className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => onRerunExperiment(egalExp.id)}
                            className="p-1.5 rounded-lg bg-indigo-950/80 hover:bg-indigo-900 text-indigo-300 border border-indigo-800/60 transition-colors"
                            title="Rerun EGAL Repetition"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="p-4 bg-slate-950/40 rounded-xl border border-dashed border-slate-800 text-center text-xs text-slate-500 py-6">
                        No EGAL experiment linked to this group
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 2. Individual / Ungrouped Experiments Section */}
      {ungroupedExperiments.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <FlaskConical className="h-4 w-4 text-slate-400" />
            <span>Individual Experiments ({ungroupedExperiments.length})</span>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                  <tr>
                    <th className="px-6 py-3">Experiment Name</th>
                    <th className="px-6 py-3">Agent</th>
                    <th className="px-6 py-3">Model & Provider</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3">Repetitions</th>
                    <th className="px-6 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {ungroupedExperiments.map((exp) => (
                    <tr key={exp.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-4">
                        <button
                          onClick={() => onSelectExperiment(exp.id)}
                          className="font-semibold text-slate-200 hover:text-indigo-400 transition-colors text-left"
                        >
                          {exp.name}
                        </button>
                        <div className="text-[11px] text-slate-400 font-mono mt-0.5">
                          Snapshot: {exp.dataset_snapshot_id}
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {exp.agent_id}
                      </td>
                      <td className="px-6 py-4 text-slate-300">
                        <div>{exp.model}</div>
                        <div className="text-[11px] text-slate-400">{exp.provider_id}</div>
                      </td>
                      <td className="px-6 py-4">
                        <StatusBadge status={exp.status} size="sm" />
                      </td>
                      <td className="px-6 py-4 font-semibold text-slate-200">
                        {exp.repetition_count || 1}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => onSelectExperiment(exp.id)}
                            className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs transition-colors"
                          >
                            Details
                          </button>
                          <button
                            onClick={() => onRerunExperiment(exp.id)}
                            className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                            title="Rerun Repetition"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ExperimentList;
