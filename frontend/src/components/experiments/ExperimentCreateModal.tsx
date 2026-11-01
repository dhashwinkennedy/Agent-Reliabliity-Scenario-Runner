import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { api } from '../../api/client';
import type {
  Dataset,
  DatasetSnapshot,
  AgentMetadata,
  Provider,
  Experiment,
} from '../../types';
import Modal from '../Modal';
import JsonViewer from '../JsonViewer';
import ErrorAlert from '../ErrorAlert';
import InputFieldMapping from './InputFieldMapping';
import {
  AgentFieldDef,
  ExtractedDatasetFields,
  MappingValidationResult,
  getAgentFields,
  extractDatasetFields,
  autoResolveMapping,
  validateMapping,
  serializeInputMapping,
} from '../../utils/inputMapping';
import {
  FlaskConical,
  Database,
  Bot,
  Cpu,
  Layers,
  ArrowRight,
  ShieldCheck,
  RotateCw,
  Plus,
} from 'lucide-react';

interface ExperimentCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (experiment: Experiment) => void;
}

export const ExperimentCreateModal: React.FC<ExperimentCreateModalProps> = ({
  isOpen,
  onClose,
  onCreated,
}) => {
  // Master options from backend
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [agents, setAgents] = useState<AgentMetadata[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [isLoadingOptions, setIsLoadingOptions] = useState(false);

  // Form State
  const [experimentName, setExperimentName] = useState('');
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [selectedSnapshotId, setSelectedSnapshotId] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('financial_news_analysis');
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [temperature, setTemperature] = useState(0.0);
  const [maxTokens, setMaxTokens] = useState(500);

  // Paired Baseline vs EGAL toggle
  const [isPairedComparison, setIsPairedComparison] = useState(true);

  // Input mapping state & sample record
  const [sampleRecord, setSampleRecord] = useState<Record<string, unknown> | null>(null);
  // Target agent field -> Dataset source field path
  const [targetToSourceMapping, setTargetToSourceMapping] = useState<Record<string, string>>({});

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // References to preserve created experiments on retry, preventing duplicates or orphans
  const pendingBaselineExpRef = useRef<Experiment | null>(null);
  const pendingEgalExpRef = useRef<Experiment | null>(null);

  // Reset pending retry references when modal closes
  useEffect(() => {
    if (!isOpen) {
      pendingBaselineExpRef.current = null;
      pendingEgalExpRef.current = null;
    }
  }, [isOpen]);

  // Dynamic agent schema & field definitions
  const currentAgent = agents.find((a) => a.id === selectedAgentId);
  const agentFields: AgentFieldDef[] = useMemo(() => {
    return getAgentFields(selectedAgentId, currentAgent?.input_schema);
  }, [selectedAgentId, currentAgent]);

  // Dynamic dataset field extraction (strictly isolates ground_truth & metadata)
  const datasetFields: ExtractedDatasetFields = useMemo(() => {
    return extractDatasetFields(sampleRecord);
  }, [sampleRecord]);

  // Real-time validation
  const mappingValidation: MappingValidationResult = useMemo(() => {
    return validateMapping(agentFields, targetToSourceMapping, datasetFields);
  }, [agentFields, targetToSourceMapping, datasetFields]);

  // Auto-resolve handler
  const handleAutoResolve = useCallback(() => {
    const resolved = autoResolveMapping(agentFields, datasetFields);
    setTargetToSourceMapping(resolved);
  }, [agentFields, datasetFields]);

  // Load datasets, agents, providers
  useEffect(() => {
    if (!isOpen) return;
    const load = async () => {
      setIsLoadingOptions(true);
      setError(null);
      try {
        const [dsRes, agRes, prRes] = await Promise.all([
          api.listDatasets({ limit: 100 }),
          api.listAgents(),
          api.listProviders(),
        ]);
        setDatasets(dsRes.items || []);
        setAgents(agRes || []);
        setProviders(prRes || []);

        if (dsRes.items && dsRes.items.length > 0) {
          const firstDs = dsRes.items[0];
          setSelectedDatasetId(firstDs.id);
          if (firstDs.snapshots && firstDs.snapshots.length > 0) {
            setSelectedSnapshotId(firstDs.snapshots[0].id);
          }
        }

        if (prRes && prRes.length > 0) {
          setSelectedProviderId(prRes[0].id);
          setSelectedModel(prRes[0].default_model || (prRes[0].models && prRes[0].models[0]) || 'mock-model');
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load options');
      } finally {
        setIsLoadingOptions(false);
      }
    };
    load();
  }, [isOpen]);

  // Update snapshot selection when dataset changes, and fetch sample record for input mapping
  useEffect(() => {
    if (!selectedDatasetId) return;
    const currentDs = datasets.find((d) => d.id === selectedDatasetId);
    if (currentDs?.snapshots && currentDs.snapshots.length > 0) {
      setSelectedSnapshotId(currentDs.snapshots[0].id);
    } else {
      setSelectedSnapshotId('');
    }

    // Fetch sample record for input mapping inspector
    api.getDatasetRecords(selectedDatasetId, { limit: 1 })
      .then((res) => {
        if (res.items && res.items.length > 0) {
          const record = res.items[0].record;
          setSampleRecord(record);
          const extracted = extractDatasetFields(record);
          const autoMap = autoResolveMapping(agentFields, extracted);
          setTargetToSourceMapping(autoMap);
        } else {
          setSampleRecord(null);
          setTargetToSourceMapping({});
        }
      })
      .catch(() => {
        setSampleRecord(null);
        setTargetToSourceMapping({});
      });
  }, [selectedDatasetId, datasets]);

  // Update mapping when agent changes
  useEffect(() => {
    if (sampleRecord) {
      const extracted = extractDatasetFields(sampleRecord);
      const newFields = getAgentFields(selectedAgentId, currentAgent?.input_schema);
      const autoMap = autoResolveMapping(newFields, extracted);
      setTargetToSourceMapping(autoMap);
    }
  }, [selectedAgentId]);

  // Update available models when provider changes
  useEffect(() => {
    if (!selectedProviderId) return;
    const p = providers.find((item) => item.id === selectedProviderId);
    if (p) {
      setSelectedModel(p.default_model || (p.models && p.models[0]) || '');
    }
  }, [selectedProviderId, providers]);

  // Check if selected agent is eligible for paired Baseline vs EGAL
  const isEligibleForPairing =
    selectedAgentId === 'financial_news_analysis' ||
    selectedAgentId === 'financial_news_analysis_egal';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSnapshotId) {
      setError('An immutable dataset snapshot is required. Please create a snapshot for this dataset first.');
      return;
    }
    if (!selectedProviderId) {
      setError('Please select a model provider.');
      return;
    }
    if (!mappingValidation.isValid) {
      setError(
        `Cannot create experiment: ${mappingValidation.missingRequired.length} required agent field(s) (${mappingValidation.missingRequired.join(', ')}) are unmapped.`
      );
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const baseName = experimentName.trim() || `Experiment_${Date.now().toString().slice(-4)}`;
    const serializedMapping = serializeInputMapping(targetToSourceMapping);

    try {
      if (isPairedComparison && isEligibleForPairing) {
        // Step 1: Create or reuse Baseline Experiment
        let baselineExp = pendingBaselineExpRef.current;
        if (!baselineExp) {
          baselineExp = await api.createExperiment({
            name: `${baseName} (Baseline)`,
            dataset_snapshot_id: selectedSnapshotId,
            agent_id: 'financial_news_analysis',
            provider_id: selectedProviderId,
            model: selectedModel,
            configuration: { temperature, max_tokens: maxTokens },
            input_mapping: serializedMapping,
          });
          pendingBaselineExpRef.current = baselineExp;
        }

        // Step 2: Create or reuse EGAL Experiment
        let egalExp = pendingEgalExpRef.current;
        if (!egalExp) {
          egalExp = await api.createExperiment({
            name: `${baseName} (EGAL)`,
            dataset_snapshot_id: selectedSnapshotId,
            agent_id: 'financial_news_analysis_egal',
            provider_id: selectedProviderId,
            model: selectedModel,
            configuration: { temperature, max_tokens: maxTokens },
            input_mapping: serializedMapping,
          });
          pendingEgalExpRef.current = egalExp;
        }

        // Step 3: Link Baseline and EGAL into comparison group
        await api.linkExperimentGroup({
          group_name: baseName,
          experiment_ids: [baselineExp.id, egalExp.id],
        });

        // Clear pending refs on complete success
        pendingBaselineExpRef.current = null;
        pendingEgalExpRef.current = null;

        onCreated(baselineExp);
      } else {
        // Single condition experiment
        const exp = await api.createExperiment({
          name: baseName,
          dataset_snapshot_id: selectedSnapshotId,
          agent_id: selectedAgentId,
          provider_id: selectedProviderId,
          model: selectedModel,
          configuration: { temperature, max_tokens: maxTokens },
          input_mapping: serializedMapping,
        });

        onCreated(exp);
      }
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create experiment');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper to create snapshot on the fly if dataset has none
  const handleQuickCreateSnapshot = async () => {
    if (!selectedDatasetId) return;
    try {
      const snap = await api.createSnapshot(selectedDatasetId, `snap_${Date.now().toString().slice(-4)}`);
      // Update local dataset list
      setDatasets((prev) =>
        prev.map((d) =>
          d.id === selectedDatasetId
            ? { ...d, snapshots: [...(d.snapshots || []), snap] }
            : d
        )
      );
      setSelectedSnapshotId(snap.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create snapshot');
    }
  };

  const currentDataset = datasets.find((d) => d.id === selectedDatasetId);
  const currentProvider = providers.find((p) => p.id === selectedProviderId);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Create Experiment"
      subtitle="Configure an evaluation experiment or paired Baseline vs EGAL comparison group"
      maxWidth="2xl"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting || !selectedSnapshotId || !selectedProviderId || !mappingValidation.isValid}
            title={!mappingValidation.isValid ? `Cannot create experiment: ${mappingValidation.missingRequired.length} required field(s) unmapped` : ''}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors shadow-sm"
          >
            {isSubmitting ? (
              <>
                <RotateCw className="h-3.5 w-3.5 animate-spin" />
                <span>Creating & Initializing...</span>
              </>
            ) : (
              <>
                <FlaskConical className="h-3.5 w-3.5" />
                <span>{isPairedComparison && isEligibleForPairing ? 'Create Comparison Group' : 'Create Experiment'}</span>
              </>
            )}
          </button>
        </>
      }
    >
      {error && (
        <ErrorAlert
          title="Configuration Error"
          message={error}
          className="mb-4"
        />
      )}

      {isLoadingOptions ? (
        <div className="p-12 text-center text-slate-400 text-xs flex items-center justify-center gap-2">
          <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
          <span>Loading backend configuration options...</span>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5 text-xs">
          {/* Experiment / Group Name */}
          <div>
            <label className="block font-medium text-slate-300 mb-1">
              Experiment / Group Name <span className="text-rose-400">*</span>
            </label>
            <input
              type="text"
              value={experimentName}
              onChange={(e) => setExperimentName(e.target.value)}
              placeholder="e.g. Q3 Financial News Sentiment Evaluation"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              required
            />
          </div>

          {/* Dataset & Snapshot Selection */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Dataset <span className="text-rose-400">*</span>
              </label>
              <select
                value={selectedDatasetId}
                onChange={(e) => setSelectedDatasetId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name} ({d.record_count} records)
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="font-medium text-slate-300">
                  Immutable Snapshot <span className="text-rose-400">*</span>
                </label>
                {(!currentDataset?.snapshots || currentDataset.snapshots.length === 0) && (
                  <button
                    type="button"
                    onClick={handleQuickCreateSnapshot}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium"
                  >
                    <Plus className="h-3 w-3" />
                    <span>Create Snapshot</span>
                  </button>
                )}
              </div>
              <select
                value={selectedSnapshotId}
                onChange={(e) => setSelectedSnapshotId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                required
              >
                {currentDataset?.snapshots && currentDataset.snapshots.length > 0 ? (
                  currentDataset.snapshots.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.record_count} items)
                    </option>
                  ))
                ) : (
                  <option value="">No snapshot available - Click create above</option>
                )}
              </select>
            </div>
          </div>

          {/* Agent Selection & Paired Comparison Card */}
          <div className="space-y-2">
            <label className="block font-medium text-slate-300">
              Agent / Architecture <span className="text-rose-400">*</span>
            </label>
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            >
              {agents.map((ag) => (
                <option key={ag.id} value={ag.id}>
                  {ag.display_name || ag.name} ({ag.id})
                </option>
              ))}
            </select>

            {isEligibleForPairing && (
              <div className="mt-3 p-3.5 bg-indigo-950/40 border border-indigo-500/30 rounded-xl flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2 text-slate-200 font-semibold">
                    <ShieldCheck className="h-4 w-4 text-indigo-400" />
                    <span>Paired Baseline-versus-EGAL Comparison Group</span>
                  </div>
                  <p className="text-[11px] text-slate-300 leading-snug">
                    Automatically initializes paired Baseline and EGAL conditions linked under this experiment group for direct comparative analysis.
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer ml-3 shrink-0">
                  <input
                    type="checkbox"
                    checked={isPairedComparison}
                    onChange={(e) => setIsPairedComparison(e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
                </label>
              </div>
            )}
          </div>

          {/* Provider & Model Selection */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Model Provider <span className="text-rose-400">*</span>
              </label>
              <select
                value={selectedProviderId}
                onChange={(e) => setSelectedProviderId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.provider_type})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Selected Model <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                placeholder="e.g. gpt-4o, claude-3-5-sonnet"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                required
              />
            </div>
          </div>

          {/* Parameters */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Temperature ({temperature})
              </label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>

            <div>
              <label className="block font-medium text-slate-300 mb-1">
                Max Tokens
              </label>
              <input
                type="number"
                step="50"
                min="50"
                max="4000"
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Dynamic Input Field Mapping */}
          <InputFieldMapping
            agentFields={agentFields}
            datasetFields={datasetFields}
            mapping={targetToSourceMapping}
            onChange={setTargetToSourceMapping}
            validationResult={mappingValidation}
            sampleRecord={sampleRecord}
            onAutoResolve={handleAutoResolve}
          />
        </form>
      )}
    </Modal>
  );
};

export default ExperimentCreateModal;
