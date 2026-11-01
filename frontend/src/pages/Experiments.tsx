import React, { useEffect, useState, useCallback } from 'react';
import { useSearchParams, useParams, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { Experiment, ExperimentGroup } from '../types';
import Header from '../components/Header';
import ExperimentList from '../components/experiments/ExperimentList';
import ExperimentDetail from '../components/experiments/ExperimentDetail';
import ExperimentCreateModal from '../components/experiments/ExperimentCreateModal';
import ErrorAlert from '../components/ErrorAlert';
import {
  FlaskConical,
  Plus,
  RotateCw,
  ArrowLeft,
  CheckCircle2,
} from 'lucide-react';

export const Experiments: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { id: paramId } = useParams<{ id?: string }>();
  const navigate = useNavigate();

  const selectedExperimentId = paramId || searchParams.get('id');

  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [groups, setGroups] = useState<ExperimentGroup[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Create Modal
  const isCreateOpen = searchParams.get('action') === 'create';

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [expRes, grpRes] = await Promise.all([
        api.listExperiments(),
        api.listExperimentGroups().catch(() => []),
      ]);
      setExperiments(expRes || []);
      setGroups(grpRes || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load experiments');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSelectExperiment = (id: string) => {
    navigate(`/experiments/${id}`);
  };

  const handleBackToList = () => {
    navigate('/experiments');
  };

  // One-Button Rerun from list view
  const handleRerun = async (experimentId: string) => {
    setError(null);
    setActionSuccess(null);
    try {
      const rep = await api.rerunExperiment(experimentId, {
        idempotency_key: `list-rerun-${experimentId}-${Date.now()}`,
      });
      setActionSuccess(`Repetition #${rep.repetition_index} launched for experiment.`);
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Rerun failed');
    }
  };

  // Rerun Both for paired Baseline + EGAL
  const handleRerunBoth = async (baselineId: string, egalId: string) => {
    setError(null);
    setActionSuccess(null);
    try {
      const timestamp = Date.now();
      const [repB, repE] = await Promise.all([
        api.rerunExperiment(baselineId, { idempotency_key: `both-b-${baselineId}-${timestamp}` }),
        api.rerunExperiment(egalId, { idempotency_key: `both-e-${egalId}-${timestamp}` }),
      ]);
      setActionSuccess(
        `Both Baseline (Rep #${repB.repetition_index}) and EGAL (Rep #${repE.repetition_index}) repetitions launched.`
      );
      loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to rerun both conditions');
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title={selectedExperimentId ? 'Experiment Details' : 'Experiments & Repetitions'}
        subtitle={
          selectedExperimentId
            ? 'Execution status, repetition history, runs, and provenance'
            : 'Organized by comparison groups, repetitions, and independent executions'
        }
        onRefresh={loadData}
        isRefreshing={isLoading}
        actions={
          selectedExperimentId ? (
            <button
              onClick={handleBackToList}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold border border-slate-700 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              <span>All Experiments</span>
            </button>
          ) : (
            <button
              onClick={() => setSearchParams({ action: 'create' })}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
            >
              <Plus className="h-4 w-4" />
              <span>Create Experiment</span>
            </button>
          )
        }
      />

      <main className="p-8 space-y-6 max-w-7xl mx-auto w-full">
        {actionSuccess && (
          <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-200 text-xs flex items-center justify-between">
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
            title="Experiment Operation Error"
            message={error}
            onRetry={loadData}
          />
        )}

        {selectedExperimentId ? (
          <ExperimentDetail
            experimentId={selectedExperimentId}
            onBack={handleBackToList}
          />
        ) : (
          <ExperimentList
            experiments={experiments}
            groups={groups}
            onSelectExperiment={handleSelectExperiment}
            onRerunExperiment={handleRerun}
            onRerunBoth={handleRerunBoth}
            isLoading={isLoading}
          />
        )}
      </main>

      {/* Create Experiment Modal */}
      <ExperimentCreateModal
        isOpen={isCreateOpen}
        onClose={() => {
          searchParams.delete('action');
          setSearchParams(searchParams);
        }}
        onCreated={(exp) => {
          loadData();
          navigate(`/experiments/${exp.id}`);
        }}
      />
    </div>
  );
};

export default Experiments;
