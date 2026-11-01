import React, { useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../api/client';
import type {
  Experiment,
  ExperimentRepetition,
  Run,
  RunResult,
  Evaluation,
  RunsResponse,
} from '../../types';
import StatusBadge from '../StatusBadge';
import ProgressBar from '../ProgressBar';
import Pagination from '../Pagination';
import MetricCard from '../MetricCard';
import JsonViewer from '../JsonViewer';
import ErrorAlert from '../ErrorAlert';
import RunDetailModal from './RunDetailModal';
import { ErrorText, parseError, isAbstention } from '../../utils/error';
import {
  Play,
  Pause,
  RotateCcw,
  Square,
  RotateCw,
  Download,
  Layers,
  FileCheck,
  Activity,
  History,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  Code2,
  Eye,
  Sparkles,
} from 'lucide-react';

interface ExperimentDetailProps {
  experimentId: string;
  onBack?: () => void;
}

type TabType =
  | 'overview'
  | 'runs'
  | 'results'
  | 'evaluation'
  | 'provenance'
  | 'mapping'
  | 'exports';

export const ExperimentDetail: React.FC<ExperimentDetailProps> = ({
  experimentId,
  onBack,
}) => {
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [repetitions, setRepetitions] = useState<ExperimentRepetition[]>([]);
  const [selectedRepetitionIndex, setSelectedRepetitionIndex] = useState<number>(1);
  const [activeTab, setActiveTab] = useState<TabType>('overview');

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // One-Button Rerun In-Progress & Debounce Guard
  const [isRerunning, setIsRerunning] = useState(false);

  // Execution control in-progress
  const [isControlling, setIsControlling] = useState(false);

  // Selected Repetition Runs & Pagination
  const [runs, setRuns] = useState<Run[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsOffset, setRunsOffset] = useState(0);
  const [runsLimit, setRunsLimit] = useState(25);
  const [isLoadingRuns, setIsLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const isLoadingRunsRef = useRef(false);

  // Selected Repetition Results & Pagination
  const [results, setResults] = useState<RunResult[]>([]);
  const [resultsTotal, setResultsTotal] = useState(0);
  const [resultsOffset, setResultsOffset] = useState(0);
  const [resultsLimit, setResultsLimit] = useState(25);
  const [isLoadingResults, setIsLoadingResults] = useState(false);

  // Evaluation state for selected repetition
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [isEvaluating, setIsEvaluating] = useState(false);

  // Manifest state
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);

  // Run Detail Modal
  const [inspectRun, setInspectRun] = useState<Run | RunResult | null>(null);

  // Guard to prevent duplicate auto-evaluations
  const autoEvalAttempted = useRef<Record<string, boolean>>({});

  // Helper to format percentage values safely
  const formatMetricPct = (val: number | null | undefined): string => {
    if (val === null || val === undefined) return '—';
    return `${val.toFixed(1)}%`;
  };

  // 1. Load Experiment & Repetitions
  const loadExperiment = useCallback(async () => {
    if (!experimentId) return;
    try {
      const [expRes, repsRes] = await Promise.all([
        api.getExperiment(experimentId),
        api.listRepetitions(experimentId).catch(() => []),
      ]);

      setExperiment(expRes);
      setRepetitions(repsRes || []);

      // If repetitions exist, ensure selectedRepetitionIndex is valid
      if (repsRes && repsRes.length > 0) {
        const found = repsRes.find((r) => r.repetition_index === selectedRepetitionIndex);
        if (!found) {
          // Select latest repetition by default if current not found
          const maxRep = Math.max(...repsRes.map((r) => r.repetition_index));
          setSelectedRepetitionIndex(maxRep);
        }
      }
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 404) {
        setError(`Experiment '${experimentId}' was not found.`);
        setExperiment(null);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load experiment');
      }
    } finally {
      setIsLoading(false);
    }
  }, [experimentId, selectedRepetitionIndex]);

  useEffect(() => {
    loadExperiment();
    const interval = setInterval(loadExperiment, 4000);
    return () => clearInterval(interval);
  }, [loadExperiment]);

  // Current active repetition record
  const safeRepetitions = Array.isArray(repetitions) ? repetitions : [];
  const currentRepetition =
    safeRepetitions.find((r) => r.repetition_index === selectedRepetitionIndex) ||
    safeRepetitions[safeRepetitions.length - 1] ||
    null;

  // 2. Load Runs for Selected Repetition
  const loadRuns = useCallback(
    async (offset = runsOffset, limit = runsLimit, silent = false) => {
      if (!currentRepetition || !experimentId) return;
      if (isLoadingRunsRef.current) return;
      isLoadingRunsRef.current = true;
      if (!silent) setIsLoadingRuns(true);
      try {
        const res: RunsResponse = await api.getRuns(experimentId, {
          offset,
          limit,
          repetition_id: currentRepetition.id,
          repetition_index: currentRepetition.repetition_index,
        });
        setRuns(res.items || []);
        setRunsTotal(res.total || 0);
        setRunsOffset(offset);
        setRunsLimit(limit);
        setRunsError(null);
      } catch (err: unknown) {
        // Fallback to repetition direct runs endpoint only if repIdOrIdx is valid
        const repIdOrIdx = currentRepetition.id || currentRepetition.repetition_index;
        let successFallback = false;
        if (repIdOrIdx !== undefined && repIdOrIdx !== null) {
          try {
            const directRuns = await api.getRepetitionRuns(experimentId, repIdOrIdx);
            setRuns(directRuns.slice(offset, offset + limit));
            setRunsTotal(directRuns.length);
            setRunsError(null);
            successFallback = true;
          } catch {
            // Handled below
          }
        }
        if (!successFallback) {
          setRunsError(parseError(err).message || 'Failed to load runs for this repetition');
        }
      } finally {
        isLoadingRunsRef.current = false;
        if (!silent) setIsLoadingRuns(false);
      }
    },
    [experimentId, currentRepetition, runsOffset, runsLimit]
  );

  // 3. Load Results for Selected Repetition
  const loadResults = useCallback(
    async (offset = resultsOffset, limit = resultsLimit) => {
      if (!currentRepetition || !experimentId) return;
      setIsLoadingResults(true);
      try {
        const res = await api.getResults(experimentId, {
          offset,
          limit,
          repetition_id: currentRepetition.id,
          repetition_index: currentRepetition.repetition_index,
        });
        setResults(res.items || []);
        setResultsTotal(res.total || 0);
        setResultsOffset(offset);
        setResultsLimit(limit);
      } catch (err: unknown) {
        // Fallback to repetition direct results endpoint only if repIdOrIdx is valid
        const repIdOrIdx = currentRepetition.id || currentRepetition.repetition_index;
        if (repIdOrIdx !== undefined && repIdOrIdx !== null) {
          try {
            const directResults = await api.getRepetitionResults(experimentId, repIdOrIdx);
            setResults(directResults.slice(offset, offset + limit));
            setResultsTotal(directResults.length);
          } catch {
            // Error handled gracefully
          }
        }
      } finally {
        setIsLoadingResults(false);
      }
    },
    [experimentId, currentRepetition, resultsOffset, resultsLimit]
  );

  // 4. Load Evaluation for Selected Repetition
  const loadEvaluation = useCallback(async () => {
    if (!currentRepetition || !experimentId) {
      setEvaluation(null);
      return;
    }

    // Fast-path: use embedded evaluation if available from repetition query
    if (currentRepetition.evaluation && typeof currentRepetition.evaluation === 'object') {
      setEvaluation(currentRepetition.evaluation as Evaluation);
    }

    try {
      const repIdOrIdx = currentRepetition.id || currentRepetition.repetition_index;
      // 1. Try repetition-specific evaluation endpoint first
      if (repIdOrIdx !== undefined && repIdOrIdx !== null) {
        try {
          const repEval = await api.getRepetitionEvaluation(experimentId, repIdOrIdx);
          if (repEval) {
            setEvaluation(repEval);
            return;
          }
        } catch {
          // If 404, repetition has not been evaluated yet; continue to fallbacks
        }
      }

      // 2. Query evaluations by repetition
      const evals = await api.listEvaluations(
        experimentId,
        currentRepetition.id,
        currentRepetition.repetition_index
      );
      if (evals && evals.length > 0) {
        setEvaluation(evals[0]);
      } else if (currentRepetition.evaluation_id) {
        try {
          const ev = await api.getEvaluation(experimentId, currentRepetition.evaluation_id);
          setEvaluation(ev);
        } catch {
          setEvaluation(null);
        }
      } else if (!currentRepetition.evaluation) {
        setEvaluation(null);
      }
    } catch {
      if (!currentRepetition.evaluation) {
        setEvaluation(null);
      }
    }
  }, [experimentId, currentRepetition]);

  // 5. Manual Evaluation Handler
  const handleManualEvaluate = async () => {
    if (!currentRepetition || isEvaluating) return;
    setIsEvaluating(true);
    setError(null);
    try {
      const ev = await api.createEvaluation(experimentId, {
        repetition_id: currentRepetition.id,
        repetition_index: currentRepetition.repetition_index,
        name: `Repetition ${currentRepetition.repetition_index} Evaluation`,
        force: true,
      });
      setEvaluation(ev);
      setActionSuccess(`Repetition #${currentRepetition.repetition_index} evaluated successfully.`);
      loadExperiment();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Evaluation execution failed');
    } finally {
      setIsEvaluating(false);
    }
  };

  // 6. Load Manifest
  useEffect(() => {
    if (!experimentId) return;
    api.getManifest(experimentId).then(setManifest).catch(() => setManifest(null));
  }, [experimentId]);

  // Reload data when active tab or selected repetition changes
  useEffect(() => {
    if (activeTab === 'runs') {
      loadRuns(0, runsLimit);
    } else if (activeTab === 'results') {
      loadResults(0, resultsLimit);
    }
    loadEvaluation();
  }, [activeTab, selectedRepetitionIndex, currentRepetition?.id]);

  // Active polling for Runs tab during live execution
  useEffect(() => {
    if (activeTab !== 'runs' || !currentRepetition) return;

    const isRunning =
      currentRepetition.status === 'running' ||
      currentRepetition.status === 'queued' ||
      experiment?.status === 'running';

    if (!isRunning) return;

    const runsInterval = setInterval(() => {
      loadRuns(runsOffset, runsLimit, true);
    }, 3000);

    return () => clearInterval(runsInterval);
  }, [activeTab, currentRepetition?.status, experiment?.status, loadRuns, runsOffset, runsLimit]);

  // 6. Automatic Evaluation Lifecycle for Every Completed Repetition
  useEffect(() => {
    if (!currentRepetition) return;

    const repKey = `${currentRepetition.id || currentRepetition.repetition_index}`;
    const isTerminal =
      currentRepetition.status === 'completed' || currentRepetition.status === 'stopped';

    // If terminal, has runs, not yet evaluated, and not already attempting
    if (
      isTerminal &&
      currentRepetition.completed_run_count > 0 &&
      !currentRepetition.evaluation_id &&
      !evaluation &&
      !autoEvalAttempted.current[repKey] &&
      !isEvaluating
    ) {
      autoEvalAttempted.current[repKey] = true;
      setIsEvaluating(true);

      api.createEvaluation(experimentId, {
        repetition_id: currentRepetition.id,
        repetition_index: currentRepetition.repetition_index,
        name: `Repetition ${currentRepetition.repetition_index} Auto-Evaluation`,
      })
        .then((ev) => {
          setEvaluation(ev);
          setActionSuccess(`Repetition ${currentRepetition.repetition_index} evaluated automatically.`);
          loadExperiment();
        })
        .catch(() => {
          // Evaluation error handled without blocking UI
        })
        .finally(() => {
          setIsEvaluating(false);
        });
    }
  }, [currentRepetition, experimentId, evaluation, isEvaluating, loadExperiment]);

  // 7. One-Button Rerun Handler (With Idempotency & Debounce Guard)
  const handleRerun = async () => {
    if (isRerunning) return;
    setIsRerunning(true);
    setError(null);
    setActionSuccess(null);

    const idempotencyKey = `rerun-${experimentId}-${Date.now()}`;

    try {
      const newRep = await api.rerunExperiment(experimentId, {
        idempotency_key: idempotencyKey,
      });

      setActionSuccess(
        `Repetition ${newRep.repetition_index} created and launched with frozen configuration.`
      );
      setSelectedRepetitionIndex(newRep.repetition_index);
      await loadExperiment();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to launch rerun');
    } finally {
      setIsRerunning(false);
    }
  };

  // 8. Execution Controls (Start, Pause, Resume, Stop)
  const handleControl = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    if (isControlling) return;
    setIsControlling(true);
    setError(null);
    try {
      if (action === 'start') {
        await api.startExperiment(experimentId);
        setActionSuccess('Experiment execution started.');
      } else {
        await api.controlExperiment(experimentId, action);
        setActionSuccess(`Experiment state changed: ${action}.`);
      }
      await loadExperiment();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to ${action} experiment`);
    } finally {
      setIsControlling(false);
    }
  };

  if (isLoading && !experiment) {
    return (
      <div className="p-16 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
        <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
        <span>Loading experiment details...</span>
      </div>
    );
  }

  if (!experiment) {
    return (
      <div className="p-12 text-center text-slate-400 bg-slate-900 border border-slate-800 rounded-xl space-y-4 max-w-lg mx-auto my-12">
        <AlertTriangle className="h-10 w-10 text-amber-400 mx-auto" />
        <div className="space-y-1">
          <h3 className="text-base font-bold text-slate-200">Experiment Not Found</h3>
          <p className="text-xs text-slate-400">
            {error || `The experiment with ID "${experimentId}" could not be found or may have been deleted.`}
          </p>
        </div>
        {onBack && (
          <button
            onClick={onBack}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold border border-slate-700 transition-colors"
          >
            Back to Experiments
          </button>
        )}
      </div>
    );
  }

  const isEgal = experiment.agent_id === 'financial_news_analysis_egal';
  const effectiveStatus = currentRepetition?.status || experiment.status;
  const isRunning = effectiveStatus === 'running' || effectiveStatus === 'queued';
  const isDraft = effectiveStatus === 'draft';
  const isPaused = effectiveStatus === 'paused';

  // Research metrics extraction for active repetition
  const tcMetric = evaluation?.metrics?.task_completion_rate;
  const uaMetric = evaluation?.metrics?.unsupported_action_rate;
  const recMetric = evaluation?.metrics?.recovery_rate;
  const consMetric = evaluation?.metrics?.consistency_rate;
  const fsMetric = evaluation?.metrics?.false_success_rate;
  const coveragePct =
    evaluation?.manifest?.coverage_percentage ??
    evaluation?.metrics?.task_completion_rate?.coverage_percentage ??
    null;

  return (
    <div className="space-y-6">
      {/* Top Banner with Experiment Header & Actions */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
        <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-xl font-bold text-slate-100 tracking-tight">
                {experiment.name}
              </h2>
              <StatusBadge status={effectiveStatus} />
              {isEgal && (
                <span className="text-xs bg-indigo-500/20 text-indigo-300 font-semibold px-2.5 py-0.5 rounded-full border border-indigo-500/30 flex items-center gap-1">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  <span>EGAL Verified</span>
                </span>
              )}
              {experiment.group_name && (
                <span className="text-xs bg-slate-800 text-indigo-300 px-2.5 py-0.5 rounded border border-indigo-900/60 font-mono">
                  Group: {experiment.group_name}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-400 flex-wrap pt-1">
              <span>Agent: <strong className="text-slate-200">{experiment.agent_id}</strong></span>
              <span>•</span>
              <span>Model: <strong className="text-slate-200">{experiment.model}</strong></span>
              <span>•</span>
              <span>Provider: <strong className="text-slate-200">{experiment.provider_id}</strong></span>
              <span>•</span>
              <span>Snapshot: <strong className="font-mono text-slate-200">{experiment.dataset_snapshot_id}</strong></span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            {/* Start Button */}
            {isDraft && (
              <button
                onClick={() => handleControl('start')}
                disabled={isControlling}
                className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5" />
                <span>Start Experiment</span>
              </button>
            )}

            {/* Pause / Resume Controls */}
            {isRunning && (
              <button
                onClick={() => handleControl('pause')}
                disabled={isControlling}
                className="px-3 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <Pause className="h-3.5 w-3.5" />
                <span>Pause</span>
              </button>
            )}

            {isPaused && (
              <button
                onClick={() => handleControl('resume')}
                disabled={isControlling}
                className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <Play className="h-3.5 w-3.5" />
                <span>Resume</span>
              </button>
            )}

            {(isRunning || isPaused) && (
              <button
                onClick={() => handleControl('stop')}
                disabled={isControlling}
                className="px-3 py-2 bg-rose-700 hover:bg-rose-600 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-50"
              >
                <Square className="h-3.5 w-3.5" />
                <span>Stop</span>
              </button>
            )}

            {/* Mandatory One-Button Rerun Feature */}
            <button
              onClick={handleRerun}
              disabled={isRerunning || isRunning}
              className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 disabled:opacity-40 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-all shadow-md shadow-indigo-600/20"
              title="Execute a new repetition with frozen dataset snapshot, agent, model, and configuration"
            >
              {isRerunning ? (
                <>
                  <RotateCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Spawning Repetition...</span>
                </>
              ) : (
                <>
                  <RotateCcw className="h-3.5 w-3.5" />
                  <span>Rerun Experiment</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Repetition Selector Bar */}
        <div className="pt-3 border-t border-slate-800/80 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-400">Repetitions:</span>
            <div className="flex items-center gap-1.5">
              {safeRepetitions.length === 0 ? (
                <span className="text-xs bg-slate-800 text-slate-300 px-2.5 py-1 rounded font-medium">
                  Repetition 1 (Initial)
                </span>
              ) : (
                safeRepetitions.map((rep) => {
                  const isSelected = rep.repetition_index === selectedRepetitionIndex;
                  return (
                    <button
                      key={rep.id || rep.repetition_index}
                      onClick={() => setSelectedRepetitionIndex(rep.repetition_index)}
                      className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors flex items-center gap-1.5 ${
                        isSelected
                          ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/40 font-semibold'
                          : 'bg-slate-800 text-slate-400 border-slate-700/60 hover:text-slate-200'
                      }`}
                    >
                      <span>Repetition {rep.repetition_index}</span>
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          rep.status === 'completed'
                            ? 'bg-emerald-400'
                            : rep.status === 'running'
                            ? 'bg-indigo-400 animate-ping'
                            : 'bg-slate-500'
                        }`}
                      />
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Active Repetition Progress Summary */}
          {currentRepetition && (
            <div className="text-xs text-slate-400 flex items-center gap-3">
              <span>
                Completed:{' '}
                <strong className="text-emerald-400">
                  {currentRepetition.completed_run_count}
                </strong>
              </span>
              <span>•</span>
              <span>
                Failed:{' '}
                <strong className="text-rose-400">
                  {currentRepetition.failed_run_count}
                </strong>
              </span>
              <span>•</span>
              <span>
                Total Runs:{' '}
                <strong className="text-slate-200">
                  {currentRepetition.run_count}
                </strong>
              </span>
            </div>
          )}
        </div>
      </div>

      {actionSuccess && (
        <div className="p-3.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-200 text-xs flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            <span>{actionSuccess}</span>
          </div>
          <button
            onClick={() => setActionSuccess(null)}
            className="text-emerald-400 hover:text-emerald-200 text-xs font-medium"
          >
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <ErrorAlert
          title="Experiment Error"
          message={error}
          onRetry={loadExperiment}
        />
      )}

      {/* Tabs Navigation */}
      <div className="border-b border-slate-800 flex items-center gap-1 overflow-x-auto text-xs">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'runs', label: `Runs (${runsTotal})` },
          { id: 'results', label: 'Persisted Results' },
          { id: 'evaluation', label: 'Evaluation Metrics' },
          { id: 'provenance', label: 'Provenance Manifest' },
          { id: 'mapping', label: 'Input Mapping' },
          { id: 'exports', label: 'Exports' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as TabType)}
            className={`px-4 py-2.5 font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === tab.id
                ? 'border-indigo-500 text-indigo-400 bg-indigo-500/5'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB CONTENT */}

      {/* TAB 1: OVERVIEW */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Progress Bar Card */}
          {currentRepetition && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
              <h3 className="text-sm font-semibold text-slate-100">
                Repetition {currentRepetition.repetition_index} Execution Progress
              </h3>
              <ProgressBar
                completed={currentRepetition.completed_run_count}
                failed={currentRepetition.failed_run_count}
                total={currentRepetition.run_count}
                status={currentRepetition.status}
                size="md"
              />
            </div>
          )}

          {/* Research Outcome Metrics Cards */}
          {evaluation ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                  <span>Research Metrics for Repetition #{selectedRepetitionIndex}</span>
                  <span className="text-[11px] font-normal text-emerald-400 font-mono">
                    ({evaluation.metric_definition_version || 'research-metrics-v1'})
                  </span>
                </h3>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                <MetricCard
                  label="Task Completion Rate"
                  value={formatMetricPct(tcMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={tcMetric?.numerator}
                  denominator={tcMetric?.denominator}
                  subtext="Applicable normal scenarios"
                />
                <MetricCard
                  label="Unsupported Action Rate"
                  value={formatMetricPct(uaMetric?.percentage)}
                  direction="lower_is_better"
                  numerator={uaMetric?.numerator}
                  denominator={uaMetric?.denominator}
                  subtext="Ambiguous scenarios"
                />
                <MetricCard
                  label="Recovery Rate"
                  value={formatMetricPct(recMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={recMetric?.numerator}
                  denominator={recMetric?.denominator}
                  subtext="Recoverable failures"
                />
                <MetricCard
                  label="Consistency Rate"
                  value={formatMetricPct(consMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={consMetric?.numerator}
                  denominator={consMetric?.denominator}
                  subtext="Repeatability scenarios"
                />
                <MetricCard
                  label="False Success Rate"
                  value={formatMetricPct(fsMetric?.percentage)}
                  direction="lower_is_better"
                  numerator={fsMetric?.numerator}
                  denominator={fsMetric?.denominator}
                  subtext="Ungrounded claims"
                />
                <MetricCard
                  label="Run Coverage"
                  value={formatMetricPct(coveragePct)}
                  direction="neutral"
                  subtext="Data completeness"
                  numerator={evaluation.manifest?.completed_run_count}
                  denominator={evaluation.manifest?.expected_run_count}
                />
              </div>
            </div>
          ) : (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 flex items-center justify-between flex-wrap gap-4">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-slate-800 text-slate-400">
                  <FileCheck className="h-5 w-5" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-slate-200">
                    No Outcome Evaluation for Repetition #{selectedRepetitionIndex}
                  </h4>
                  <p className="text-xs text-slate-400">
                    {effectiveStatus === 'completed'
                      ? 'Execution finished. Outcome evaluation can be scored deterministically without LLM calls.'
                      : isRunning
                      ? 'Repetition is currently running. Metrics will be evaluated upon completion.'
                      : 'Repetition execution has not finished yet.'}
                  </p>
                </div>
              </div>
              {effectiveStatus === 'completed' && (
                <button
                  onClick={handleManualEvaluate}
                  disabled={isEvaluating}
                  className="px-3.5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
                >
                  {isEvaluating ? (
                    <>
                      <RotateCw className="h-3.5 w-3.5 animate-spin" />
                      <span>Evaluating...</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5" />
                      <span>Run Evaluation</span>
                    </>
                  )}
                </button>
              )}
            </div>
          )}

          {/* Repetition History Table inside Experiment */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-100">Repetition History</h3>
                <p className="text-xs text-slate-400">
                  Every repetition is preserved independently under this experiment
                </p>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                  <tr>
                    <th className="px-6 py-3">Repetition #</th>
                    <th className="px-6 py-3">Condition</th>
                    <th className="px-6 py-3">Status</th>
                    <th className="px-6 py-3">Runs (Done/Fail/Total)</th>
                    <th className="px-6 py-3">Evaluation Status</th>
                    <th className="px-6 py-3">Started / Finished</th>
                    <th className="px-6 py-3 text-right">Inspect</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80">
                  {safeRepetitions.map((rep) => (
                    <tr
                      key={rep.id || rep.repetition_index}
                      className={`hover:bg-slate-800/40 transition-colors ${
                        rep.repetition_index === selectedRepetitionIndex
                          ? 'bg-indigo-600/10'
                          : ''
                      }`}
                    >
                      <td className="px-6 py-4 font-mono font-bold text-slate-200">
                        #{rep.repetition_index}
                      </td>
                      <td className="px-6 py-4 font-medium text-slate-300">
                        {isEgal ? 'EGAL' : 'Baseline'}
                      </td>
                      <td className="px-6 py-4">
                        <StatusBadge status={rep.status} size="sm" />
                      </td>
                      <td className="px-6 py-4 font-mono">
                        <span className="text-emerald-400">{rep.completed_run_count}</span> /{' '}
                        <span className="text-rose-400">{rep.failed_run_count}</span> /{' '}
                        <span>{rep.run_count}</span>
                      </td>
                      <td className="px-6 py-4">
                        {rep.evaluation_id ? (
                          <span className="text-emerald-400 font-medium flex items-center gap-1">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            <span>Evaluated</span>
                          </span>
                        ) : rep.status === 'completed' ? (
                          <span className="text-indigo-400 flex items-center gap-1 animate-pulse">
                            <RotateCw className="h-3.5 w-3.5 animate-spin" />
                            <span>Auto-evaluating...</span>
                          </span>
                        ) : (
                          <span className="text-slate-500">Pending Execution</span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-slate-400 text-[11px]">
                        <div>{rep.started_at ? new Date(rep.started_at).toLocaleTimeString() : '—'}</div>
                        <div className="text-[10px] text-slate-500">
                          {rep.completed_at ? new Date(rep.completed_at).toLocaleTimeString() : 'In progress'}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => setSelectedRepetitionIndex(rep.repetition_index)}
                          className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs transition-colors"
                        >
                          View Rep #{rep.repetition_index}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: RUNS */}
      {activeTab === 'runs' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm space-y-0">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">
                Runs for Repetition #{selectedRepetitionIndex}
              </h3>
              <p className="text-xs text-slate-400">
                All individual test executions including successful runs and failures
              </p>
            </div>
            {isLoadingRuns && (
              <div className="flex items-center gap-2 text-xs text-indigo-400">
                <RotateCw className="h-3.5 w-3.5 animate-spin" />
                <span>Refreshing...</span>
              </div>
            )}
          </div>

          {runsError && (
            <div className="p-4 border-b border-slate-800">
              <ErrorAlert
                title="Failed to Load Runs"
                message={runsError}
                onRetry={() => loadRuns(runsOffset, runsLimit)}
              />
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                <tr>
                  <th className="px-6 py-3">Run ID</th>
                  <th className="px-6 py-3">Item ID</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Latency</th>
                  <th className="px-6 py-3">Tokens</th>
                  <th className="px-6 py-3">Details / Errors</th>
                  <th className="px-6 py-3 text-right">Inspect</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {isLoadingRuns && runs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-12 text-center text-slate-400">
                      <div className="flex items-center justify-center gap-2">
                        <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
                        <span>Loading runs...</span>
                      </div>
                    </td>
                  </tr>
                ) : runs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-12 text-center text-slate-400">
                      {currentRepetition?.status === 'running' ||
                      currentRepetition?.status === 'queued' ||
                      experiment?.status === 'running' ? (
                        <div className="flex flex-col items-center justify-center gap-2">
                          <RotateCw className="h-5 w-5 animate-spin text-indigo-400" />
                          <span className="text-slate-200 font-medium text-sm">Execution in progress</span>
                          <span className="text-xs text-slate-500 max-w-sm">
                            Runs are queued and executing. They will appear here automatically as execution proceeds.
                          </span>
                        </div>
                      ) : (
                        <span>No runs recorded for this repetition.</span>
                      )}
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-6 py-3.5 font-mono text-indigo-400 font-medium">
                        {r.id.slice(0, 12)}...
                      </td>
                      <td className="px-6 py-3.5 font-mono text-slate-300">
                        {(r as unknown as { dataset_item_id?: string | number; record_index?: number }).dataset_item_id ??
                         (r as unknown as { record_index?: number }).record_index ??
                         '—'}
                      </td>
                      <td className="px-6 py-3.5">
                        <StatusBadge status={r.status} size="sm" />
                      </td>
                      <td className="px-6 py-3.5 font-mono text-slate-300">
                        {r.latency_ms !== null && r.latency_ms !== undefined
                          ? `${r.latency_ms.toFixed(0)} ms`
                          : (r as unknown as { execution_duration_ms?: number }).execution_duration_ms !== null &&
                            (r as unknown as { execution_duration_ms?: number }).execution_duration_ms !== undefined
                          ? `${(r as unknown as { execution_duration_ms: number }).execution_duration_ms.toFixed(0)} ms`
                          : '—'}
                      </td>
                      <td className="px-6 py-3.5 font-mono text-slate-300">
                        {r.tokens_used || '—'}
                      </td>
                      <td className="px-6 py-3.5 max-w-xs truncate">
                        {r.error ? (
                          <ErrorText error={r.error} className="text-rose-400 font-mono text-[11px]" />
                        ) : (() => {
                          const out =
                            (r as unknown as { output_data?: unknown; output?: unknown; normalized_output?: unknown }).output_data ||
                            (r as unknown as { output?: unknown }).output ||
                            (r as unknown as { normalized_output?: unknown }).normalized_output;
                          const { isAbstain, reason } = isAbstention(out);
                          if (isAbstain) {
                            return (
                              <span
                                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-500/15 border border-amber-500/30 text-amber-300 font-mono"
                                title={reason || 'Financial Recommendation: ABSTAIN'}
                              >
                                <span>ABSTAIN</span>
                                {reason && (
                                  <span className="text-[10px] text-amber-400/80 font-normal truncate max-w-[120px]">
                                    ({reason})
                                  </span>
                                )}
                              </span>
                            );
                          }
                          if (out) {
                            return (
                              <span className="text-slate-400 text-[11px] font-mono truncate block max-w-xs">
                                {JSON.stringify(out)}
                              </span>
                            );
                          }
                          return <span className="text-slate-600">—</span>;
                        })()}
                      </td>
                      <td className="px-6 py-3.5 text-right">
                        <button
                          onClick={() => setInspectRun(r)}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-colors"
                          title="Open Run Details"
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <Pagination
            offset={runsOffset}
            limit={runsLimit}
            total={runsTotal}
            onPageChange={(newOffset) => loadRuns(newOffset, runsLimit)}
            onLimitChange={(newLimit) => {
              setRunsLimit(newLimit);
              loadRuns(0, newLimit);
            }}
            isLoading={isLoadingRuns}
          />
        </div>
      )}

      {/* TAB 3: PERSISTED RESULTS */}
      {activeTab === 'results' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm space-y-0">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">
                Persisted Results for Repetition #{selectedRepetitionIndex}
              </h3>
              <p className="text-xs text-slate-400">
                Input, agent output, and ground truth records
              </p>
            </div>
          </div>

          <div className="p-6 space-y-4">
            {isLoadingResults && results.length === 0 ? (
              <div className="p-12 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
                <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
                <span>Loading results...</span>
              </div>
            ) : results.length === 0 ? (
              <p className="text-center text-slate-400 text-xs py-8">
                No results recorded yet for this repetition.
              </p>
            ) : (
              results.map((res) => (
                <div
                  key={res.run_id}
                  className="bg-slate-950 border border-slate-800 rounded-xl p-4 space-y-3"
                >
                  <div className="flex items-center justify-between text-xs border-b border-slate-800/80 pb-2">
                    <span className="font-mono text-indigo-400 font-semibold">
                      Run: {res.run_id} (Item: {res.dataset_item_id})
                    </span>
                    <StatusBadge status={res.status} size="sm" />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <span className="text-[11px] text-slate-400 font-medium block mb-1">
                        Input
                      </span>
                      <JsonViewer data={res.input} maxHeight="max-h-36" />
                    </div>
                    <div>
                      <span className="text-[11px] text-slate-400 font-medium block mb-1">
                        Output
                      </span>
                      <JsonViewer data={res.output} maxHeight="max-h-36" />
                    </div>
                  </div>

                  {res.ground_truth && (
                    <div className="pt-2 border-t border-slate-900 text-xs">
                      <span className="text-[11px] text-slate-400 font-medium block mb-1">
                        Ground Truth
                      </span>
                      <JsonViewer data={res.ground_truth} maxHeight="max-h-24" />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          <Pagination
            offset={resultsOffset}
            limit={resultsLimit}
            total={resultsTotal}
            onPageChange={(newOffset) => loadResults(newOffset, resultsLimit)}
            onLimitChange={(newLimit) => {
              setResultsLimit(newLimit);
              loadResults(0, newLimit);
            }}
            isLoading={isLoadingResults}
          />
        </div>
      )}

      {/* TAB 4: EVALUATION METRICS */}
      {activeTab === 'evaluation' && (
        <div className="space-y-6">
          {evaluation ? (
            <div className="space-y-6">
              {/* Summary Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
                <MetricCard
                  label="Task Completion Rate"
                  value={formatMetricPct(tcMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={tcMetric?.numerator}
                  denominator={tcMetric?.denominator}
                  subtext="Applicable normal scenarios"
                />
                <MetricCard
                  label="Unsupported Action Rate"
                  value={formatMetricPct(uaMetric?.percentage)}
                  direction="lower_is_better"
                  numerator={uaMetric?.numerator}
                  denominator={uaMetric?.denominator}
                  subtext="Ambiguous scenarios"
                />
                <MetricCard
                  label="Recovery Rate"
                  value={formatMetricPct(recMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={recMetric?.numerator}
                  denominator={recMetric?.denominator}
                  subtext="Recoverable failures"
                />
                <MetricCard
                  label="Consistency Rate"
                  value={formatMetricPct(consMetric?.percentage)}
                  direction="higher_is_better"
                  numerator={consMetric?.numerator}
                  denominator={consMetric?.denominator}
                  subtext="Repeatability scenarios"
                />
                <MetricCard
                  label="False Success Rate"
                  value={formatMetricPct(fsMetric?.percentage)}
                  direction="lower_is_better"
                  numerator={fsMetric?.numerator}
                  denominator={fsMetric?.denominator}
                  subtext="Ungrounded claims"
                />
                <MetricCard
                  label="Run Coverage"
                  value={formatMetricPct(coveragePct)}
                  direction="neutral"
                  subtext="Data completeness"
                  numerator={evaluation.manifest?.completed_run_count}
                  denominator={evaluation.manifest?.expected_run_count}
                />
              </div>

              {/* Detailed Metrics Table */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
                <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">
                      Authoritative Research Metric Breakdown
                    </h3>
                    <p className="text-xs text-slate-400 font-mono">
                      Evaluation ID: {evaluation.id} • Definition: {evaluation.metric_definition_version || 'research-metrics-v1'}
                    </p>
                  </div>
                  <span className="text-xs text-emerald-400 font-medium flex items-center gap-1.5 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20">
                    <CheckCircle2 className="h-4 w-4" />
                    <span>Deterministic Metric Engine (No LLM Calls)</span>
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-950/60 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                      <tr>
                        <th className="px-6 py-3">Metric</th>
                        <th className="px-6 py-3">Scope / Evaluated Domain</th>
                        <th className="px-6 py-3">Ratio (Num / Denom)</th>
                        <th className="px-6 py-3">Status</th>
                        <th className="px-6 py-3">Excl / Miss / Rev</th>
                        <th className="px-6 py-3">Score</th>
                        <th className="px-6 py-3">Rule Definition</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/80">
                      <tr className="hover:bg-slate-800/30">
                        <td className="px-6 py-3.5 font-semibold text-slate-100">Task Completion Rate</td>
                        <td className="px-6 py-3.5 text-slate-400">Normal scenarios meeting GT</td>
                        <td className="px-6 py-3.5 font-mono">{tcMetric ? `${tcMetric.numerator} / ${tcMetric.denominator}` : '—'}</td>
                        <td className="px-6 py-3.5"><StatusBadge status={tcMetric?.status || 'complete'} size="sm" /></td>
                        <td className="px-6 py-3.5 font-mono text-slate-400">{tcMetric?.excluded ?? 0} / {tcMetric?.missing ?? 0} / {tcMetric?.review ?? 0}</td>
                        <td className="px-6 py-3.5 font-mono font-bold text-emerald-400">{formatMetricPct(tcMetric?.percentage)}</td>
                        <td className="px-6 py-3.5 text-slate-400 text-[11px]">{tcMetric?.notes?.[0] || 'Evaluates deterministically assessed normal scenarios meeting ground truth.'}</td>
                      </tr>
                      <tr className="hover:bg-slate-800/30">
                        <td className="px-6 py-3.5 font-semibold text-slate-100">Unsupported Action Rate</td>
                        <td className="px-6 py-3.5 text-slate-400">Ambiguous scenarios without evidence</td>
                        <td className="px-6 py-3.5 font-mono">{uaMetric ? `${uaMetric.numerator} / ${uaMetric.denominator}` : '—'}</td>
                        <td className="px-6 py-3.5"><StatusBadge status={uaMetric?.status || 'complete'} size="sm" /></td>
                        <td className="px-6 py-3.5 font-mono text-slate-400">{uaMetric?.excluded ?? 0} / {uaMetric?.missing ?? 0} / {uaMetric?.review ?? 0}</td>
                        <td className="px-6 py-3.5 font-mono font-bold text-indigo-400">{formatMetricPct(uaMetric?.percentage)}</td>
                        <td className="px-6 py-3.5 text-slate-400 text-[11px]">{uaMetric?.notes?.[0] || 'Evaluates whether agent took unsupported directional actions in ambiguous scenarios.'}</td>
                      </tr>
                      <tr className="hover:bg-slate-800/30">
                        <td className="px-6 py-3.5 font-semibold text-slate-100">Recovery Rate</td>
                        <td className="px-6 py-3.5 text-slate-400">Recoverable failures (FAILURE-001/002)</td>
                        <td className="px-6 py-3.5 font-mono">{recMetric ? `${recMetric.numerator} / ${recMetric.denominator}` : '—'}</td>
                        <td className="px-6 py-3.5"><StatusBadge status={recMetric?.status || 'complete'} size="sm" /></td>
                        <td className="px-6 py-3.5 font-mono text-slate-400">{recMetric?.excluded ?? 0} / {recMetric?.missing ?? 0} / {recMetric?.review ?? 0}</td>
                        <td className="px-6 py-3.5 font-mono font-bold text-cyan-400">{formatMetricPct(recMetric?.percentage)}</td>
                        <td className="px-6 py-3.5 text-slate-400 text-[11px]">{recMetric?.notes?.[0] || 'Scored on recoverable failure scenarios; persistent failures excluded.'}</td>
                      </tr>
                      <tr className="hover:bg-slate-800/30">
                        <td className="px-6 py-3.5 font-semibold text-slate-100">Consistency Rate</td>
                        <td className="px-6 py-3.5 text-slate-400">6 designated repeatability scenarios</td>
                        <td className="px-6 py-3.5 font-mono">{consMetric ? `${consMetric.numerator} / ${consMetric.denominator}` : '—'}</td>
                        <td className="px-6 py-3.5"><StatusBadge status={consMetric?.status || 'complete'} size="sm" /></td>
                        <td className="px-6 py-3.5 font-mono text-slate-400">{consMetric?.excluded ?? 0} / {consMetric?.missing ?? 0} / {consMetric?.review ?? 0}</td>
                        <td className="px-6 py-3.5 font-mono font-bold text-amber-400">{formatMetricPct(consMetric?.percentage)}</td>
                        <td className="px-6 py-3.5 text-slate-400 text-[11px]">{consMetric?.notes?.[0] || 'Evaluates decision stability across five repetitions of each repeatability scenario.'}</td>
                      </tr>
                      <tr className="hover:bg-slate-800/30">
                        <td className="px-6 py-3.5 font-semibold text-slate-100">False Success Rate</td>
                        <td className="px-6 py-3.5 text-slate-400">Supporting check (invalid success claims)</td>
                        <td className="px-6 py-3.5 font-mono">{fsMetric ? `${fsMetric.numerator} / ${fsMetric.denominator}` : '—'}</td>
                        <td className="px-6 py-3.5"><StatusBadge status={fsMetric?.status || 'complete'} size="sm" /></td>
                        <td className="px-6 py-3.5 font-mono text-slate-400">{fsMetric?.excluded ?? 0} / {fsMetric?.missing ?? 0} / {fsMetric?.review ?? 0}</td>
                        <td className="px-6 py-3.5 font-mono font-bold text-rose-400">{formatMetricPct(fsMetric?.percentage)}</td>
                        <td className="px-6 py-3.5 text-slate-400 text-[11px]">{fsMetric?.notes?.[0] || 'Identifies scenarios claiming success despite ungrounded or persistent failure outputs.'}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Provenance & Manifest Details */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-100">Evaluation Provenance & Manifest</h3>
                  <span className="text-xs font-mono text-slate-400">
                    Status: <strong className="text-slate-200">{evaluation.manifest?.evaluation_status || evaluation.status || 'COMPLETED'}</strong>
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs font-mono">
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase">Snapshot ID</span>
                    <span className="text-slate-200 truncate block">{evaluation.dataset_snapshot_id || evaluation.manifest?.dataset_snapshot_id || '—'}</span>
                  </div>
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase">Fingerprint</span>
                    <span className="text-indigo-400 truncate block">{evaluation.dataset_fingerprint || evaluation.manifest?.dataset_fingerprint || '—'}</span>
                  </div>
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase">Metric Definition</span>
                    <span className="text-slate-200 truncate block">{evaluation.metric_definition_version || 'research-metrics-v1'}</span>
                  </div>
                  <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
                    <span className="text-slate-500 block text-[10px] uppercase">Schema Version</span>
                    <span className="text-slate-200 truncate block">{evaluation.evaluation_schema_version || 'evaluation-v1'}</span>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                    <h4 className="font-semibold text-slate-200">Metrics Payload</h4>
                    <JsonViewer data={evaluation.metrics} maxHeight="max-h-64" />
                  </div>

                  <div className="p-4 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                    <h4 className="font-semibold text-slate-200">Manifest & Execution Provenance</h4>
                    <JsonViewer
                      data={evaluation.manifest || { note: 'No manifest recorded' }}
                      maxHeight="max-h-64"
                    />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="p-16 text-center text-slate-400 bg-slate-900 border border-slate-800 rounded-xl space-y-4 max-w-lg mx-auto">
              <FileCheck className="h-10 w-10 text-slate-600 mx-auto" />
              <div className="space-y-1">
                <p className="text-sm text-slate-200 font-medium">
                  No evaluation available for Repetition #{selectedRepetitionIndex}
                </p>
                <p className="text-xs text-slate-400">
                  {effectiveStatus === 'completed'
                    ? 'The repetition has completed execution, but outcome evaluation has not been performed yet.'
                    : 'Evaluations can be executed once the repetition runs finish.'}
                </p>
              </div>
              {effectiveStatus === 'completed' && (
                <button
                  onClick={handleManualEvaluate}
                  disabled={isEvaluating}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition-colors shadow-sm"
                >
                  {isEvaluating ? (
                    <>
                      <RotateCw className="h-3.5 w-3.5 animate-spin" />
                      <span>Evaluating...</span>
                    </>
                  ) : (
                    <>
                      <Play className="h-3.5 w-3.5" />
                      <span>Run Evaluation</span>
                    </>
                  )}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* TAB 5: PROVENANCE MANIFEST */}
      {activeTab === 'provenance' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Immutable Provenance Manifest
            </h3>
            <p className="text-xs text-slate-400">
              Frozen configuration snapshot, dataset SHA-256 fingerprint, model, and reproducibility bundle
            </p>
          </div>
          <JsonViewer data={manifest || { note: 'Manifest loading...' }} maxHeight="max-h-96" />
        </div>
      )}

      {/* TAB 7: INPUT MAPPING */}
      {activeTab === 'mapping' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Saved Input Field Mapping</h3>
              <p className="text-xs text-slate-400">
                Immutable field mapping configuration applied to every repetition of this experiment
              </p>
            </div>
            <span className="px-2.5 py-1 text-xs font-medium bg-slate-800 text-slate-300 rounded-lg border border-slate-700">
              {Object.keys(experiment.input_mapping || {}).length} Mapped Fields
            </span>
          </div>

          {experiment.input_mapping && Object.keys(experiment.input_mapping).length > 0 ? (
            <div className="border border-slate-800 rounded-lg overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950 text-slate-400 font-mono text-[11px] border-b border-slate-800">
                  <tr>
                    <th className="px-4 py-2.5">Dataset Source Field</th>
                    <th className="px-4 py-2.5 w-12 text-center">Direction</th>
                    <th className="px-4 py-2.5">Agent Target Field</th>
                    <th className="px-4 py-2.5">Scope</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {Object.entries(experiment.input_mapping).map(([source, target]) => {
                    const isNested = source.startsWith('input.');
                    return (
                      <tr key={source} className="hover:bg-slate-800/30">
                        <td className="px-4 py-2.5 text-indigo-300 font-medium">
                          {source}
                        </td>
                        <td className="px-4 py-2.5 text-center text-slate-500 font-bold">
                          →
                        </td>
                        <td className="px-4 py-2.5 text-emerald-300 font-medium">
                          {target}
                        </td>
                        <td className="px-4 py-2.5 font-sans">
                          {isNested ? (
                            <span className="px-2 py-0.5 text-[10px] bg-indigo-950/60 text-indigo-300 border border-indigo-800/50 rounded">
                              Nested in &apos;input&apos;
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 text-[10px] bg-slate-800 text-slate-300 border border-slate-700 rounded">
                              Top-level
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-lg text-slate-400 text-xs">
              No custom field mappings configured. Agent consumes default input structure.
            </div>
          )}

          <div className="pt-2">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
              Raw Mapping Definition (JSON)
            </span>
            <JsonViewer data={experiment.input_mapping} maxHeight="max-h-64" />
          </div>
        </div>
      )}

      {/* TAB 8: EXPORTS */}
      {activeTab === 'exports' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">
              Export Repetition Data
            </h3>
            <p className="text-xs text-slate-400">
              Download complete run results and evaluation records directly as CSV or JSONL
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Repetition Runs Export */}
            <div className="p-5 bg-slate-950 rounded-xl border border-slate-800 space-y-3">
              <h4 className="text-xs font-semibold text-slate-200">
                Repetition #{selectedRepetitionIndex} Runs & Results
              </h4>
              <p className="text-[11px] text-slate-400">
                Full un-truncated outputs for all runs in this repetition.
              </p>
              <div className="flex items-center gap-2 pt-2">
                <a
                  href={api.getExportUrl('repetition', {
                    experimentId,
                    repetitionIdOrIndex: selectedRepetitionIndex,
                    format: 'csv',
                  })}
                  download
                  className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download CSV</span>
                </a>
                <a
                  href={api.getExportUrl('repetition', {
                    experimentId,
                    repetitionIdOrIndex: selectedRepetitionIndex,
                    format: 'jsonl',
                  })}
                  download
                  className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download JSONL</span>
                </a>
              </div>
            </div>

            {/* Evaluation Export */}
            {evaluation && (
              <div className="p-5 bg-slate-950 rounded-xl border border-slate-800 space-y-3">
                <h4 className="text-xs font-semibold text-slate-200">
                  Evaluation Records
                </h4>
                <p className="text-[11px] text-slate-400">
                  Detailed metric breakdowns, scoring records, and audit exclusions.
                </p>
                <div className="flex items-center gap-2 pt-2">
                  <a
                    href={api.getExportUrl('evaluation', {
                      experimentId,
                      evaluationId: evaluation.id,
                      format: 'csv',
                    })}
                    download
                    className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Download CSV</span>
                  </a>
                  <a
                    href={api.getExportUrl('evaluation', {
                      experimentId,
                      evaluationId: evaluation.id,
                      format: 'jsonl',
                    })}
                    download
                    className="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors"
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span>Download JSONL</span>
                  </a>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Run Detail Modal */}
      <RunDetailModal run={inspectRun} onClose={() => setInspectRun(null)} />
    </div>
  );
};

export default ExperimentDetail;
