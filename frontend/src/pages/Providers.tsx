import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api/client';
import { buildProviderCreatePayload } from '../utils/providerPayload';
export { buildProviderCreatePayload } from '../utils/providerPayload';
import type {
  Provider,
  ProviderCreateRequest,
  ProviderUpdateRequest,
  ProviderConnectionTest,
} from '../types';
import Header from '../components/Header';
import Modal from '../components/Modal';
import ErrorAlert from '../components/ErrorAlert';
import {
  Cpu,
  Plus,
  Key,
  Globe,
  CheckCircle2,
  XCircle,
  Activity,
  Edit2,
  Trash2,
  RotateCw,
  Sparkles,
  Server,
  Zap,
} from 'lucide-react';

export const Providers: React.FC = () => {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Connection testing state (mapping providerId -> result)
  const [testResults, setTestResults] = useState<Record<string, ProviderConnectionTest>>({});
  const [testingId, setTestingId] = useState<string | null>(null);

  // Discovered models state (mapping providerId -> models[])
  const [discoveredModels, setDiscoveredModels] = useState<Record<string, string[]>>({});
  const [discoveringId, setDiscoveringId] = useState<string | null>(null);

  // Register Provider modal state
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [regId, setRegId] = useState('');
  const [regName, setRegName] = useState('');
  const [regType, setRegType] = useState('openai_compatible');
  const [regApiKey, setRegApiKey] = useState('');
  const [regBaseUrl, setRegBaseUrl] = useState('');
  const [regDefaultModel, setRegDefaultModel] = useState('');
  const [isRegistering, setIsRegistering] = useState(false);

  // Edit Provider modal state
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [editName, setEditName] = useState('');
  const [editApiKey, setEditApiKey] = useState('');
  const [editBaseUrl, setEditBaseUrl] = useState('');
  const [editDefaultModel, setEditDefaultModel] = useState('');
  const [isUpdating, setIsUpdating] = useState(false);

  const loadProviders = useCallback(async () => {
    setIsLoading(true);
    setActionError(null);
    try {
      const res = await api.listProviders();
      setProviders(res || []);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to load providers');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  // Test provider connection
  const handleTestConnection = async (providerId: string) => {
    setTestingId(providerId);
    setActionError(null);
    try {
      const res = await api.testProviderConnection(providerId);
      setTestResults((prev) => ({ ...prev, [providerId]: res }));
      if (res.ok) {
        setActionSuccess(`Provider connected successfully (${res.latency_ms}ms)`);
      } else {
        setActionError(`Connection failed: ${res.errors?.join(', ') || 'Service unreachable'}`);
      }
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Connection test request failed');
    } finally {
      setTestingId(null);
    }
  };

  // Discover models
  const handleDiscoverModels = async (providerId: string) => {
    setDiscoveringId(providerId);
    try {
      const models = await api.getProviderModels(providerId);
      setDiscoveredModels((prev) => ({ ...prev, [providerId]: models }));
      setActionSuccess(`Discovered ${models.length} model(s) for ${providerId}`);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Model discovery failed');
    } finally {
      setDiscoveringId(null);
    }
  };

  // Register provider
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!regId.trim() || !regName.trim() || !regBaseUrl.trim() || !regDefaultModel.trim()) {
      setActionError('Provider ID, Display Name, Base URL, and Default Model are required.');
      return;
    }
    setIsRegistering(true);
    setActionError(null);
    try {
      const payload = buildProviderCreatePayload({
        id: regId,
        name: regName,
        provider_type: regType,
        api_key: regApiKey,
        base_url: regBaseUrl,
        default_model: regDefaultModel,
      });
      await api.createProvider(payload);
      setActionSuccess(`Provider "${regName}" registered.`);
      setIsRegisterOpen(false);
      setRegId('');
      setRegName('');
      setRegType('openai_compatible');
      setRegApiKey('');
      setRegBaseUrl('');
      setRegDefaultModel('');
      loadProviders();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to register provider');
    } finally {
      setIsRegistering(false);
    }
  };

  // Edit provider
  const handleOpenEdit = (p: Provider) => {
    setEditingProvider(p);
    setEditName(p.name);
    setEditApiKey(''); // Write-only! Never populate plaintext key
    setEditBaseUrl(p.base_url || '');
    setEditDefaultModel(p.default_model || '');
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProvider) return;
    setIsUpdating(true);
    setActionError(null);
    try {
      const payload: ProviderUpdateRequest = {
        name: editName ? editName.trim() : undefined,
        api_key: editApiKey ? editApiKey.trim() : undefined,
        base_url: editBaseUrl ? editBaseUrl.trim() : undefined,
        default_model: editDefaultModel ? editDefaultModel.trim() : undefined,
      };
      await api.updateProvider(editingProvider.id, payload);
      setActionSuccess(`Provider "${editingProvider.name}" updated.`);
      setEditingProvider(null);
      loadProviders();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to update provider');
    } finally {
      setIsUpdating(false);
    }
  };

  // Delete provider
  const handleDelete = async (p: Provider) => {
    if (!window.confirm(`Delete provider "${p.name}" (${p.id})?`)) return;
    setActionError(null);
    try {
      await api.deleteProvider(p.id);
      setActionSuccess(`Provider "${p.name}" deleted.`);
      loadProviders();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete provider');
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <Header
        title="Model Providers"
        subtitle="Manage LLM providers, credentials, model discovery, and connection testing"
        onRefresh={loadProviders}
        isRefreshing={isLoading}
        actions={
          <button
            onClick={() => setIsRegisterOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-colors"
          >
            <Plus className="h-4 w-4" />
            <span>Register Provider</span>
          </button>
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

        {actionError && (
          <ErrorAlert
            title="Provider Operation Error"
            message={actionError}
            onRetry={loadProviders}
          />
        )}

        {/* Providers List Container */}
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs text-slate-400 px-1">
            <span>
              Configured Providers: <strong className="text-slate-200">{providers.length}</strong>
            </span>
            <span>API keys are encrypted at rest with AES-GCM and never exposed</span>
          </div>

          {isLoading && providers.length === 0 ? (
            <div className="p-16 text-center text-slate-400 text-xs flex items-center justify-center gap-2 bg-slate-900 border border-slate-800 rounded-xl">
              <RotateCw className="h-4 w-4 animate-spin text-indigo-400" />
              <span>Loading providers...</span>
            </div>
          ) : providers.length === 0 ? (
            <div className="p-16 text-center text-slate-400 space-y-2 bg-slate-900 border border-slate-800 rounded-xl">
              <Cpu className="h-10 w-10 text-slate-600 mx-auto" />
              <p className="text-sm text-slate-300">No providers configured</p>
              <p className="text-xs text-slate-400">Register a provider to execute experiments.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {providers.map((p) => {
                const test = testResults[p.id];
                const models = discoveredModels[p.id] || p.models || [];
                const isTesting = testingId === p.id;
                const isDiscovering = discoveringId === p.id;

                return (
                  <div
                    key={p.id}
                    className="bg-slate-900 border border-slate-800 hover:border-slate-700/80 rounded-xl p-6 shadow-sm flex flex-col justify-between transition-colors"
                  >
                    <div className="space-y-4">
                      {/* Provider Header */}
                      <div className="flex items-start justify-between">
                        <div className="flex items-center gap-3">
                          <div className="h-10 w-10 rounded-lg bg-amber-500/10 border border-amber-500/25 flex items-center justify-center text-amber-400 shrink-0">
                            <Cpu className="h-5 w-5" />
                          </div>
                          <div>
                            <h3 className="text-base font-semibold text-slate-100">{p.name}</h3>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className="text-xs text-slate-400 font-mono">{p.id}</span>
                              <span className="text-[10px] bg-slate-800 text-slate-300 px-2 py-0.5 rounded capitalize">
                                {p.provider_type}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Credential Status Chip */}
                        <div className="flex items-center gap-1.5">
                          {p.api_key_configured ? (
                            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-2 py-0.5 rounded-full">
                              <Key className="h-3 w-3" />
                              <span>Key Configured</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded-full">
                              <span>No Key Required</span>
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Config Details */}
                      <div className="space-y-1.5 text-xs text-slate-400 pt-2 border-t border-slate-800/80">
                        {p.base_url && (
                          <div className="flex items-center justify-between">
                            <span>Base URL</span>
                            <span className="font-mono text-slate-200 truncate max-w-[200px]">
                              {p.base_url}
                            </span>
                          </div>
                        )}
                        <div className="flex items-center justify-between">
                          <span>Default Model</span>
                          <span className="font-mono text-indigo-400">
                            {p.default_model || 'Not specified'}
                          </span>
                        </div>
                      </div>

                      {/* Connection Test Diagnostic Banner */}
                      {test && (
                        <div
                          className={`p-3 rounded-lg border text-xs ${
                            test.ok
                              ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
                              : 'bg-rose-500/10 border-rose-500/25 text-rose-300'
                          }`}
                        >
                          <div className="flex items-center justify-between font-semibold">
                            <div className="flex items-center gap-1.5">
                              {test.ok ? (
                                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                              ) : (
                                <XCircle className="h-4 w-4 text-rose-400" />
                              )}
                              <span>{test.ok ? 'Connection Verified' : 'Connection Failed'}</span>
                            </div>
                            <span className="font-mono text-[11px]">
                              {test.latency_ms} ms
                            </span>
                          </div>
                          {test.errors && test.errors.length > 0 && (
                            <p className="mt-1 text-[11px] text-rose-400 leading-snug">
                              {test.errors.join('; ')}
                            </p>
                          )}
                        </div>
                      )}

                      {/* Discovered Models List */}
                      {models.length > 0 && (
                        <div className="pt-2 border-t border-slate-800/80">
                          <span className="text-[11px] font-medium text-slate-400 block mb-1.5">
                            Available Models ({models.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
                            {models.map((m) => (
                              <span
                                key={m}
                                className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
                                  m === p.default_model
                                    ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/40 font-semibold'
                                    : 'bg-slate-800 text-slate-300 border-slate-700/60'
                                }`}
                              >
                                {m}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="pt-4 mt-4 border-t border-slate-800 flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleTestConnection(p.id)}
                          disabled={isTesting}
                          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
                        >
                          <Zap className={`h-3.5 w-3.5 ${isTesting ? 'animate-spin text-amber-400' : 'text-amber-400'}`} />
                          <span>{isTesting ? 'Testing...' : 'Test Connection'}</span>
                        </button>
                        <button
                          onClick={() => handleDiscoverModels(p.id)}
                          disabled={isDiscovering}
                          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-medium border border-slate-700 flex items-center gap-1.5 transition-colors disabled:opacity-50"
                        >
                          <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
                          <span>{isDiscovering ? 'Discovering...' : 'Discover Models'}</span>
                        </button>
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => handleOpenEdit(p)}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                          title="Edit Provider Settings"
                        >
                          <Edit2 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(p)}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/60 text-slate-400 hover:text-rose-300 border border-slate-700 transition-colors"
                          title="Delete Provider"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>

      {/* Register Provider Modal */}
      <Modal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        title="Register Model Provider"
        subtitle="Configure an LLM provider endpoint and encrypted credentials"
        footer={
          <>
            <button
              type="button"
              onClick={() => setIsRegisterOpen(false)}
              className="px-3.5 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              onClick={handleRegister}
              disabled={isRegistering || !regId || !regName}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors"
            >
              {isRegistering ? (
                <>
                  <RotateCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Registering...</span>
                </>
              ) : (
                <>
                  <Plus className="h-3.5 w-3.5" />
                  <span>Register Provider</span>
                </>
              )}
            </button>
          </>
        }
      >
        <form onSubmit={handleRegister} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Provider ID <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={regId}
                onChange={(e) => setRegId(e.target.value)}
                placeholder="e.g. openrouter"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Display Name <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={regName}
                onChange={(e) => setRegName(e.target.value)}
                placeholder="e.g. OpenRouter"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Provider Type <span className="text-rose-400">*</span>
              </label>
              <select
                value={regType}
                onChange={(e) => setRegType(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="openai_compatible">OpenAI-compatible</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Default Model <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={regDefaultModel}
                onChange={(e) => setRegDefaultModel(e.target.value)}
                placeholder="e.g. anthropic/claude-3.5-sonnet"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              API Key (Encrypted with AES-GCM at rest)
            </label>
            <input
              type="password"
              value={regApiKey}
              onChange={(e) => setRegApiKey(e.target.value)}
              placeholder="sk-or-v1-..."
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            />
            <p className="text-[10px] text-slate-400 mt-1">
              Never stored in plain text or returned back to the browser.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Base URL <span className="text-rose-400">*</span>
            </label>
            <input
              type="url"
              value={regBaseUrl}
              onChange={(e) => setRegBaseUrl(e.target.value)}
              placeholder="https://openrouter.ai/api/v1"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
              required
            />
          </div>
        </form>
      </Modal>

      {/* Edit Provider Modal */}
      <Modal
        isOpen={!!editingProvider}
        onClose={() => setEditingProvider(null)}
        title={`Edit Provider: ${editingProvider?.name}`}
        subtitle={`Provider ID: ${editingProvider?.id}`}
        footer={
          <>
            <button
              type="button"
              onClick={() => setEditingProvider(null)}
              className="px-3.5 py-2 text-xs font-medium text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              onClick={handleUpdate}
              disabled={isUpdating}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors"
            >
              {isUpdating ? (
                <>
                  <RotateCw className="h-3.5 w-3.5 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <span>Save Changes</span>
              )}
            </button>
          </>
        }
      >
        <form onSubmit={handleUpdate} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Display Name
            </label>
            <input
              type="text"
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Update API Key (Leave blank to keep existing key)
            </label>
            <input
              type="password"
              value={editApiKey}
              onChange={(e) => setEditApiKey(e.target.value)}
              placeholder="Enter new key to update..."
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Default Model
            </label>
            <input
              type="text"
              value={editDefaultModel}
              onChange={(e) => setEditDefaultModel(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Base URL
            </label>
            <input
              type="url"
              value={editBaseUrl}
              onChange={(e) => setEditBaseUrl(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            />
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default Providers;
