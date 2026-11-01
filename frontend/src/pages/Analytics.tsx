import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import type {
  AnalysisOptionsResponse,
  ExperimentGroup,
  ExperimentGroupDetail,
  PairedRepetitionComparison,
} from '../types';
import Header from '../components/Header';
import MetricCard from '../components/MetricCard';
import ErrorAlert from '../components/ErrorAlert';
import {
  BarChart3,
  Layers,
  ShieldCheck,
  Bot,
  Filter,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Minus,
  RotateCw,
  Sparkles,
  Info,
} from 'lucide-react';

export const Analytics: React.FC = () => {
  const [options, setOptions] = useState<AnalysisOptionsResponse | null>(null);
  const [groups, setGroups] = useState<ExperimentGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [groupDetail, setGroupDetail] = useState<ExperimentGroupDetail | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selected filters from /api/analysis/options
  const [selectedDataset, setSelectedDataset] = useState<string>('');
  const [selectedModel, setSelectedModel] = useState<string>('');

  // Load initial options & groups
  const loadOptionsAndGroups = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [optRes, grpRes] = await Promise.all([
        api.getAnalysisOptions().catch(() => ({
          datasets: [],
          models: [],
          providers: [],
          conditions: ['baseline', 'egal'],
          metrics: [
            'task_completion_rate',
            'unsupported_action_rate',
            'recovery_rate',
            'consistency_rate',
            'false_success_rate',
          ],
        })),
        api.listExperimentGroups().catch(() => []),
      ]);

      setOptions(optRes);
      setGroups(grpRes || []);

      if (grpRes && grpRes.length > 0) {
        setSelectedGroupId(grpRes[0].id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load analytics options');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOptionsAndGroups();
  }, [loadOptionsAndGroups]);

  // Load selected group details & comparisons
  useEffect(() => {
    if (!selectedGroupId) {
      setGroupDetail(null);
      return;
    }
    setIsLoading(true);
    api.getExperimentGroup(selectedGroupId)
      .then((detail) => {
        setGroupDetail(detail);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load group comparison');
        setGroupDetail(null);
      })
      .finally(() => setIsLoading(false));
  }, [selectedGroupId]);

  // Helper to extract delta numeric value safely from either number or { value: number } / { delta: number }
  const getDeltaValue = (d: unknown): number | null => {
    if (d === null || d === undefined) return null;
    if (typeof d === 'number') return d;
    if (typeof d === 'object') {
      const obj = d as Record<string, unknown>;
      if (typeof obj.value === 'number') return obj.value;
      if (typeof obj.delta === 'number') return obj.delta;
    }
    return null;
  };

  // Helper to extract metric percentage value safely from MetricResult or number
  const getMetricPercentage = (m: unknown): number | null => {
    if (m === null || m === undefined) return null;
    if (typeof m === 'number') return m;
    if (typeof m === 'object') {
      const obj = m as Record<string, unknown>;
      if (typeof obj.percentage === 'number') return obj.percentage;
    }
    return null;
  };

  // Format percentage string cleanly — never returns 'nil'
  const formatPct = (val: number | null | undefined): string => {
    if (val === null || val === undefined) return 'N/A';
    const scaled = Math.abs(val) <= 1.0 && val !== 0 ? val * 100 : val;
    return `${scaled.toFixed(1)}%`;
  };

  // Format metric value with explicit numerator and denominator
  const formatMetricWithRatio = (m: unknown): string => {
    if (!m || typeof m !== 'object') return 'N/A';
    const obj = m as Record<string, unknown>;
    const pct = typeof obj.percentage === 'number' ? obj.percentage : null;
    const num = typeof obj.numerator === 'number' ? obj.numerator : null;
    const den = typeof obj.denominator === 'number' ? obj.denominator : null;

    if (pct === null) {
      if (obj.status === 'not_assessable') {
        const details = (obj.details || {}) as Record<string, unknown>;
        if (details.required_repetitions && details.observed_repetitions) {
          return `Not Assessable (${details.observed_repetitions}/${details.required_repetitions} reps)`;
        }
        return 'Not Assessable';
      }
      return 'N/A';
    }

    const scaled = Math.abs(pct) <= 1.0 && pct !== 0 ? pct * 100 : pct;
    if (num !== null && den !== null) {
      return `${scaled.toFixed(1)}% (${num}/${den})`;
    }
    return `${scaled.toFixed(1)}%`;
  };

  // Render comprehensive delta badge for Across-Repetition Summary Cards
  const renderSummaryDelta = (
    val: unknown,
    direction: 'higher_is_better' | 'lower_is_better'
  ) => {
    let num: number | null = null;
    let directionStr: string | null = null;

    if (val !== null && typeof val === 'object') {
      const obj = val as Record<string, unknown>;
      num = typeof obj.value === 'number' ? obj.value : (typeof obj.delta === 'number' ? obj.delta : null);
      directionStr = typeof obj.direction === 'string' ? obj.direction : null;
    } else if (typeof val === 'number') {
      num = val;
    }

    if (directionStr === 'not_assessable' || num === null) {
      return (
        <span className="inline-flex items-center gap-1.5 text-slate-400 font-medium text-xs bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">
          <Info className="h-3.5 w-3.5 text-slate-400" />
          <span>Not Assessable</span>
        </span>
      );
    }

    if (num === 0 || directionStr === 'unchanged') {
      return (
        <span className="inline-flex items-center gap-1.5 text-slate-300 font-semibold text-xs bg-slate-800 px-2.5 py-1 rounded-md border border-slate-700">
          <Minus className="h-3.5 w-3.5 text-slate-400" />
          <span>0.0 percentage-point change (Equal / Unchanged)</span>
        </span>
      );
    }

    const isGood = direction === 'higher_is_better' ? num > 0 : num < 0;
    const formatted = num > 0 ? `+${num.toFixed(1)}` : `${num.toFixed(1)}`;

    return (
      <span
        className={`inline-flex items-center gap-1.5 font-semibold text-xs px-2.5 py-1 rounded-md border ${
          isGood
            ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
            : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
        }`}
      >
        {num > 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
        <span>
          {formatted} percentage-point {isGood ? 'improvement' : 'regression'}
        </span>
      </span>
    );
  };

  // Render per-repetition delta indicator
  const renderDelta = (
    val: unknown,
    direction: 'higher_is_better' | 'lower_is_better'
  ) => {
    let num: number | null = null;
    let directionStr: string | null = null;

    if (val !== null && typeof val === 'object') {
      const obj = val as Record<string, unknown>;
      num = typeof obj.value === 'number' ? obj.value : (typeof obj.delta === 'number' ? obj.delta : null);
      directionStr = typeof obj.direction === 'string' ? obj.direction : null;
    } else if (typeof val === 'number') {
      num = val;
    }

    if (directionStr === 'not_assessable' || num === null) {
      return (
        <span className="inline-flex items-center gap-1 text-slate-400 font-medium text-xs bg-slate-800/60 px-2 py-0.5 rounded">
          <Info className="h-3 w-3 text-slate-400" />
          <span>Not Assessable</span>
        </span>
      );
    }

    if (num === 0 || directionStr === 'unchanged') {
      return (
        <span className="inline-flex items-center gap-1 text-slate-300 font-medium text-xs bg-slate-800/80 px-2 py-0.5 rounded">
          <Minus className="h-3 w-3 text-slate-400" />
          <span>0.0% (Unchanged)</span>
        </span>
      );
    }

    const isGood = direction === 'higher_is_better' ? num > 0 : num < 0;
    const formatted = num > 0 ? `+${num.toFixed(1)}%` : `${num.toFixed(1)}%`;

    return (
      <span
        className={`inline-flex items-center gap-1 font-semibold text-xs px-2 py-0.5 rounded ${
          isGood ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'
        }`}
      >
        {num > 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
        <span>{formatted}</span>
        <span className="text-[10px] ml-0.5 uppercase font-normal">
          ({isGood ? 'Improvement' : 'Regression'})
        </span>
      </span>
    );
  };

  const safeGroups = Array.isArray(groups) ? groups : [];
  const comparisons = (groupDetail?.repetition_comparisons || groupDetail?.comparisons?.repetitions || []) as any[];

  const acrossSummary = groupDetail?.across_repetition_summary || groupDetail?.comparison;
  const pooledBase = (acrossSummary?.baseline_metrics || {}) as Record<string, any>;
  const pooledEgal = (acrossSummary?.egal_metrics || {}) as Record<string, any>;
  const pooledDeltas = (acrossSummary?.deltas || acrossSummary?.delta || {}) as Record<string, any>;
  const repCount = acrossSummary?.repetition_count || groupDetail?.baseline?.repetition_count || comparisons.length || 0;

  const hasBaseline = !!(groupDetail?.baseline?.experiment || groupDetail?.baseline_experiment);
  const hasEgal = !!(groupDetail?.egal?.experiment || groupDetail?.egal_experiment);
  const isCompleteGroup = hasBaseline && hasEgal;

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title="Research Analytics: Baseline vs EGAL"
        subtitle="Authoritative comparative metrics across repetitions without LLM calls"
        onRefresh={loadOptionsAndGroups}
        isRefreshing={isLoading}
      />

      <main className="p-8 space-y-8 max-w-7xl mx-auto w-full">
        {error && (
          <ErrorAlert
            title="Analytics Error"
            message={error}
            onRetry={loadOptionsAndGroups}
          />
        )}

        {/* Filter Bar */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <Filter className="h-4 w-4 text-indigo-400" />
            <span>Comparison Filters</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
            {/* Comparison Group Selector */}
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Experiment Group <span className="text-rose-400">*</span>
              </label>
              <select
                value={selectedGroupId}
                onChange={(e) => setSelectedGroupId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {safeGroups.length === 0 ? (
                  <option value="">No comparison groups found</option>
                ) : (
                  safeGroups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name} ({g.model})
                    </option>
                  ))
                )}
              </select>
            </div>

            {/* Dataset Filter */}
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Dataset Filter
              </label>
              <select
                value={selectedDataset}
                onChange={(e) => setSelectedDataset(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">All Compatible Datasets</option>
                {options?.datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Model Filter */}
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Model Filter
              </label>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">All Models</option>
                {options?.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Incomplete Group Warning if one condition is missing */}
        {groupDetail && !isCompleteGroup && (
          <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-200 text-xs flex items-start gap-3">
            <Info className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold block">Comparison Incomplete:</span>
              <p className="mt-0.5 leading-relaxed text-amber-200/90">
                This group requires both a Baseline experiment (`financial_news_analysis`) and an EGAL experiment (`financial_news_analysis_egal`) to perform head-to-head comparisons. Currently only{' '}
                <strong>{hasBaseline ? 'Baseline' : 'EGAL'}</strong> is registered in this group.
              </p>
            </div>
          </div>
        )}

        {/* Across-Repetition Summary Cards */}
        {groupDetail && isCompleteGroup && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-indigo-400" />
                <h3 className="text-sm font-semibold text-slate-100">
                  Across-Repetition Summary & Improvement Deltas
                </h3>
              </div>
              <span className="text-xs text-slate-400 font-mono">
                Model: {groupDetail.model} • Snapshot: {groupDetail.dataset_snapshot_id} • {repCount} Repetition{repCount === 1 ? '' : 's'} Pooled
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                {
                  key: 'task_completion_rate',
                  label: 'Task Completion Rate',
                  direction: 'higher_is_better' as const,
                  description: 'Deterministically assessed normal scenarios meeting ground truth requirements',
                },
                {
                  key: 'unsupported_action_rate',
                  label: 'Unsupported Action Rate',
                  direction: 'lower_is_better' as const,
                  description: 'Directional actions taken in ambiguous scenarios (lower is better)',
                },
                {
                  key: 'recovery_rate',
                  label: 'Recovery Rate',
                  direction: 'higher_is_better' as const,
                  description: 'Self-correction on recoverable failure scenarios (FAILURE-001, FAILURE-002)',
                },
                {
                  key: 'consistency_rate',
                  label: 'Consistency Rate',
                  direction: 'higher_is_better' as const,
                  description: 'Decision stability across 6 repeatability scenarios (min 5 repetitions required)',
                },
                {
                  key: 'false_success_rate',
                  label: 'False Success Rate',
                  direction: 'lower_is_better' as const,
                  description: 'Scenarios claiming success despite ungrounded or persistent failure outputs (lower is better)',
                },
              ].map((m) => (
                <div
                  key={m.key}
                  className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3 hover:border-slate-700/80 transition-all flex flex-col justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center justify-between text-xs font-medium">
                      <span className="font-semibold text-slate-100">{m.label}</span>
                      <span className="text-[10px] uppercase font-mono tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                        {m.direction === 'higher_is_better' ? 'Higher is better' : 'Lower is better'}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 py-3 my-2 border-y border-slate-800/80">
                      <div className="space-y-1">
                        <span className="text-[11px] text-slate-400 uppercase tracking-wider block">Baseline</span>
                        <span className="text-base font-bold text-slate-200 font-mono">
                          {formatMetricWithRatio(pooledBase[m.key])}
                        </span>
                      </div>
                      <div className="space-y-1">
                        <span className="text-[11px] text-indigo-400 uppercase tracking-wider block">EGAL Guardrails</span>
                        <span className="text-base font-bold text-indigo-300 font-mono">
                          {formatMetricWithRatio(pooledEgal[m.key])}
                        </span>
                      </div>
                    </div>

                    <div>
                      {renderSummaryDelta(pooledDeltas[m.key], m.direction)}
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800/60 text-[11px] text-slate-400 leading-snug">
                    {m.key === 'consistency_rate' && pooledBase[m.key]?.notes?.[0]
                      ? pooledBase[m.key].notes[0]
                      : m.description}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Per-Repetition Comparison Table */}
        {groupDetail && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-100">
                  Per-Repetition Paired Comparison
                </h3>
                <p className="text-xs text-slate-400">
                  Comparing exact corresponding repetitions between Baseline and EGAL
                </p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                  <tr>
                    <th className="px-6 py-3">Repetition</th>
                    <th className="px-6 py-3">Metric</th>
                    <th className="px-6 py-3">Baseline</th>
                    <th className="px-6 py-3">EGAL Guardrails</th>
                    <th className="px-6 py-3">Delta / Direction</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {comparisons.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-slate-400">
                        No paired evaluated repetitions available yet.
                      </td>
                    </tr>
                  ) : (
                    comparisons.map((rep) => {
                      const repComp = rep.comparison || {};
                      const bm = (rep.baseline_metrics || repComp.baseline_metrics || rep.baseline_repetition?.evaluation?.metrics || {}) as Record<string, unknown>;
                      const em = (rep.egal_metrics || repComp.egal_metrics || rep.egal_repetition?.evaluation?.metrics || {}) as Record<string, unknown>;
                      const d = (rep.deltas || repComp.deltas || repComp.delta || {}) as Record<string, unknown>;

                      const metricsList = [
                        { key: 'task_completion_rate', label: 'Task Completion Rate', dir: 'higher_is_better' as const },
                        { key: 'unsupported_action_rate', label: 'Unsupported Action Rate', dir: 'lower_is_better' as const },
                        { key: 'recovery_rate', label: 'Recovery Rate', dir: 'higher_is_better' as const },
                        { key: 'consistency_rate', label: 'Consistency Rate', dir: 'higher_is_better' as const },
                        { key: 'false_success_rate', label: 'False Success Rate', dir: 'lower_is_better' as const },
                      ];

                      return (
                        <React.Fragment key={rep.repetition_index}>
                          {metricsList.map((m, idx) => (
                            <tr key={m.key} className={`hover:bg-slate-800/30 ${idx === metricsList.length - 1 ? 'border-b border-slate-800' : ''}`}>
                              {idx === 0 && (
                                <td rowSpan={metricsList.length} className="px-6 py-4 font-bold text-slate-100 border-r border-slate-800/80 align-top">
                                  <span className="font-mono text-indigo-400 block">
                                    Repetition #{rep.repetition_index}
                                  </span>
                                  <span className="text-[10px] text-slate-500 font-normal block mt-1">
                                    18 paired runs
                                  </span>
                                </td>
                              )}
                              <td className="px-6 py-3 font-medium text-slate-200">{m.label}</td>
                              <td className="px-6 py-3 font-mono text-slate-300">
                                {formatMetricWithRatio(bm[m.key])}
                              </td>
                              <td className="px-6 py-3 font-mono text-indigo-300 font-semibold">
                                {formatMetricWithRatio(em[m.key])}
                              </td>
                              <td className="px-6 py-3">
                                {renderDelta(d[m.key], m.dir)}
                              </td>
                            </tr>
                          ))}
                        </React.Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Research Evaluation Protocol Information */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-indigo-400" />
            <h3 className="text-sm font-semibold text-slate-100">
              Research Evaluation & Guardrail Verification Protocol (research-metrics-v1)
            </h3>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            All metrics are calculated deterministically offline against immutable dataset ground truth and annotations without external LLM calls.
            Pooled aggregations sum raw numerators and denominators to prevent harmonic or mean-percentage distortion across varying exclusions.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs pt-2">
            <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
              <span className="text-slate-400 block mb-1">Ground Truth Requirements</span>
              <span className="text-sm font-semibold text-slate-100">Deterministic Task Assessment</span>
              <p className="text-[11px] text-slate-400 mt-1">Scored on normal scenarios with mandatory and optional facts</p>
            </div>
            <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
              <span className="text-slate-400 block mb-1">Safety Guardrails</span>
              <span className="text-sm font-semibold text-emerald-400">Directional Action Control</span>
              <p className="text-[11px] text-slate-400 mt-1">Zero unsupported directional trades under ambiguous evidence</p>
            </div>
            <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
              <span className="text-slate-400 block mb-1">Resilience & Recovery</span>
              <span className="text-sm font-semibold text-indigo-400">Self-Correction Protocol</span>
              <p className="text-[11px] text-slate-400 mt-1">Recovery from transient tool failures and prompt injection</p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default Analytics;
