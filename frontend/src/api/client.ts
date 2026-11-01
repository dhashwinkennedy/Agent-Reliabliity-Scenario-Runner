// Research Arena - Central Typed API Client
import type {
  AgentMetadata,
  AnalysisFilterRequest,
  AnalysisOptionsResponse,
  AnalysisReportResponse,
  ApiErrorDetail,
  ApiErrorResponse,
  Dataset,
  DatasetRecordItem,
  DatasetSnapshot,
  Evaluation,
  EvaluationCreateRequest,
  Experiment,
  ExperimentCreateRequest,
  ExperimentGroup,
  ExperimentGroupCreateRequest,
  ExperimentGroupDetail,
  ExperimentGroupLinkRequest,
  ExperimentRepetition,
  ExperimentRerunRequest,
  PaginatedResponse,
  PaginationParams,
  Provider,
  ProviderConnectionTest,
  ProviderCreateRequest,
  ProviderUpdateRequest,
  Run,
  RunResult,
  RunsResponse,
} from '../types';

export class ApiError extends Error {
  code: string;
  details?: Record<string, unknown>;
  status: number;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message || `API Error: ${detail.code || status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = detail.code || 'UNKNOWN_ERROR';
    this.details = detail.details;
  }
}

const getBaseUrl = (): string => {
  let envBase: string | undefined;
  try {
    envBase = (import.meta as unknown as { env?: Record<string, string> })?.env?.VITE_API_BASE_URL;
  } catch {
    envBase = undefined;
  }
  if (typeof window !== 'undefined') {
    return envBase || '/api';
  }
  const nodeEnv = typeof process !== 'undefined' && process.env ? process.env.VITE_API_BASE_URL : undefined;
  return envBase || nodeEnv || 'http://127.0.0.1:8000/api';
};

const DEFAULT_BASE_URL = getBaseUrl();

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = DEFAULT_BASE_URL) {
    // Ensure baseUrl does not end with a trailing slash
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public extractItems<T>(res: unknown): T[] {
    if (Array.isArray(res)) return res as T[];
    if (res && typeof res === 'object' && 'items' in res && Array.isArray((res as { items: unknown[] }).items)) {
      return (res as { items: T[] }).items;
    }
    return [];
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `${this.baseUrl}${cleanEndpoint}`;

    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    if (!(options.body instanceof FormData) && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return {} as T;
    }

    if (!response.ok) {
      let errorDetail: ApiErrorDetail = {
        code: `HTTP_${response.status}`,
        message: response.statusText,
      };

      try {
        const errorJson = (await response.json()) as unknown;
        errorDetail = this.parseErrorResponse(response.status, response.statusText, errorJson);
      } catch {
        // If response is not JSON, retain default error detail
      }

      throw new ApiError(response.status, errorDetail);
    }

    return (await response.json()) as T;
  }

  private parseErrorResponse(
    status: number,
    statusText: string,
    errorJson: unknown
  ): ApiErrorDetail {
    if (!errorJson || typeof errorJson !== 'object') {
      return {
        code: `HTTP_${status}`,
        message: statusText || `Request failed with status ${status}`,
      };
    }

    const errObj = errorJson as Record<string, unknown>;

    // 1. Structured { error: { code, message, details } }
    if (errObj.error && typeof errObj.error === 'object') {
      const sub = errObj.error as Record<string, unknown>;
      return {
        code: (sub.code as string) || `HTTP_${status}`,
        message: (sub.message as string) || statusText || 'An error occurred',
        details: (sub.details as Record<string, unknown>) || sub,
      };
    }

    // 2. FastAPI validation detail array: { detail: [ { loc, msg, type } ] }
    if (Array.isArray(errObj.detail)) {
      const messages = errObj.detail
        .map((item: unknown) => {
          if (item && typeof item === 'object') {
            const err = item as Record<string, unknown>;
            const locArr = Array.isArray(err.loc) ? err.loc : [];
            const field = locArr.filter((p) => p !== 'body').join('.');
            const msg = (err.msg as string) || 'Invalid value';
            return field ? `${field}: ${msg}` : msg;
          }
          return String(item);
        })
        .filter(Boolean);

      return {
        code: 'VALIDATION_ERROR',
        message: messages.join('; ') || 'Request validation error',
        details: { errors: errObj.detail as unknown as Record<string, unknown> },
      };
    }

    // 3. FastAPI { detail: { code, message } }
    if (errObj.detail && typeof errObj.detail === 'object') {
      const sub = errObj.detail as Record<string, unknown>;
      return {
        code: (sub.code as string) || `HTTP_${status}`,
        message: (sub.message as string) || JSON.stringify(sub),
        details: sub,
      };
    }

    // 4. FastAPI string { detail: "message" }
    if (typeof errObj.detail === 'string') {
      return {
        code: `HTTP_${status}`,
        message: errObj.detail,
      };
    }

    // 5. Generic message
    if (typeof errObj.message === 'string') {
      return {
        code: (errObj.code as string) || `HTTP_${status}`,
        message: errObj.message,
      };
    }

    return {
      code: `HTTP_${status}`,
      message: statusText || `Request failed with status ${status}`,
    };
  }

  // ----------------------------------------------------------------
  // Health
  // ----------------------------------------------------------------
  async getHealth(): Promise<{ status: string; version?: string }> {
    return this.request<{ status: string; version?: string }>('/health');
  }

  // ----------------------------------------------------------------
  // Datasets
  // ----------------------------------------------------------------
  async listDatasets(params: PaginationParams = {}): Promise<PaginatedResponse<Dataset>> {
    const search = new URLSearchParams();
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    const query = search.toString() ? `?${search.toString()}` : '';
    return this.request<PaginatedResponse<Dataset>>(`/datasets${query}`);
  }

  async getDataset(datasetId: string): Promise<Dataset> {
    return this.request<Dataset>(`/datasets/${datasetId}`);
  }

  async uploadDataset(file: File, displayName?: string): Promise<Dataset> {
    const formData = new FormData();
    formData.append('file', file);
    if (displayName) {
      formData.append('display_name', displayName);
    }
    return this.request<Dataset>('/datasets/upload', {
      method: 'POST',
      body: formData,
    });
  }

  async validateDataset(datasetId: string): Promise<Dataset> {
    return this.request<Dataset>(`/datasets/${datasetId}/validate`, {
      method: 'POST',
    });
  }

  async getDatasetRecords(
    datasetId: string,
    params: PaginationParams = {}
  ): Promise<PaginatedResponse<DatasetRecordItem>> {
    const search = new URLSearchParams();
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    const query = search.toString() ? `?${search.toString()}` : '';
    return this.request<PaginatedResponse<DatasetRecordItem>>(`/datasets/${datasetId}/records${query}`);
  }

  async createSnapshot(datasetId: string, name?: string): Promise<DatasetSnapshot> {
    return this.request<DatasetSnapshot>(`/datasets/${datasetId}/snapshots`, {
      method: 'POST',
      body: JSON.stringify(name ? { name } : {}),
    });
  }

  async deleteDataset(datasetId: string): Promise<void> {
    return this.request<void>(`/datasets/${datasetId}`, {
      method: 'DELETE',
    });
  }

  // ----------------------------------------------------------------
  // Agents (Read-only for existing registered agents)
  // ----------------------------------------------------------------
  async listAgents(): Promise<AgentMetadata[]> {
    const res = await this.request<unknown>('/agents');
    return this.extractItems<AgentMetadata>(res);
  }

  async getAgent(agentId: string): Promise<AgentMetadata> {
    return this.request<AgentMetadata>(`/agents/${agentId}`);
  }

  // ----------------------------------------------------------------
  // Providers & Models
  // ----------------------------------------------------------------
  async listProviders(): Promise<Provider[]> {
    const res = await this.request<unknown>('/providers');
    return this.extractItems<Provider>(res);
  }

  async getProvider(providerId: string): Promise<Provider> {
    return this.request<Provider>(`/providers/${providerId}`);
  }

  async createProvider(data: ProviderCreateRequest): Promise<Provider> {
    return this.request<Provider>('/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateProvider(providerId: string, data: ProviderUpdateRequest): Promise<Provider> {
    return this.request<Provider>(`/providers/${providerId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteProvider(providerId: string): Promise<void> {
    return this.request<void>(`/providers/${providerId}`, {
      method: 'DELETE',
    });
  }

  async getProviderModels(providerId: string): Promise<string[]> {
    const res = await this.request<unknown>(`/providers/${providerId}/models`);
    return this.extractItems<string>(res);
  }

  async listAllModels(): Promise<string[]> {
    const res = await this.request<unknown>('/models');
    return this.extractItems<string>(res);
  }

  async testProviderConnection(providerId: string): Promise<ProviderConnectionTest> {
    return this.request<ProviderConnectionTest>(`/providers/${providerId}/test-connection`, {
      method: 'POST',
    });
  }

  // ----------------------------------------------------------------
  // Experiments
  // ----------------------------------------------------------------
  async listExperiments(): Promise<Experiment[]> {
    const res = await this.request<unknown>('/experiments');
    return this.extractItems<Experiment>(res);
  }

  async getExperiment(experimentId: string): Promise<Experiment> {
    return this.request<Experiment>(`/experiments/${experimentId}`);
  }

  async createExperiment(data: ExperimentCreateRequest): Promise<Experiment> {
    return this.request<Experiment>('/experiments', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async startExperiment(experimentId: string): Promise<Experiment> {
    return this.request<Experiment>(`/experiments/${experimentId}/start`, {
      method: 'POST',
    });
  }

  async controlExperiment(
    experimentId: string,
    action: 'pause' | 'resume' | 'stop'
  ): Promise<Experiment> {
    return this.request<Experiment>(`/experiments/${experimentId}/${action}`, {
      method: 'POST',
    });
  }

  async getRuns(
    experimentId: string,
    params: PaginationParams & { repetition_id?: string; repetition_index?: number } = {}
  ): Promise<RunsResponse> {
    const search = new URLSearchParams();
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    if (params.repetition_id) search.set('repetition_id', params.repetition_id);
    if (params.repetition_index !== undefined) search.set('repetition_index', String(params.repetition_index));
    const query = search.toString() ? `?${search.toString()}` : '';
    return this.request<RunsResponse>(`/experiments/${experimentId}/runs${query}`);
  }

  async getResults(
    experimentId: string,
    params: PaginationParams & { all?: boolean; repetition_id?: string; repetition_index?: number } = {}
  ): Promise<PaginatedResponse<RunResult>> {
    const search = new URLSearchParams();
    if (params.offset !== undefined) search.set('offset', String(params.offset));
    if (params.limit !== undefined) search.set('limit', String(params.limit));
    if (params.all) search.set('all', 'true');
    if (params.repetition_id) search.set('repetition_id', params.repetition_id);
    if (params.repetition_index !== undefined) search.set('repetition_index', String(params.repetition_index));
    const query = search.toString() ? `?${search.toString()}` : '';
    return this.request<PaginatedResponse<RunResult>>(`/experiments/${experimentId}/results${query}`);
  }

  async getRun(runId: string): Promise<Run> {
    return this.request<Run>(`/runs/${runId}`);
  }

  async getManifest(experimentId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(`/experiments/${experimentId}/manifest`);
  }

  // ----------------------------------------------------------------
  // Repetitions & Reruns
  // ----------------------------------------------------------------
  async rerunExperiment(
    experimentId: string,
    data: ExperimentRerunRequest = {}
  ): Promise<ExperimentRepetition> {
    return this.request<ExperimentRepetition>(`/experiments/${experimentId}/rerun`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listRepetitions(experimentId: string): Promise<ExperimentRepetition[]> {
    const res = await this.request<unknown>(`/experiments/${experimentId}/repetitions`);
    return this.extractItems<ExperimentRepetition>(res);
  }

  async getRepetition(
    experimentId: string,
    repetitionIdOrIndex: string | number
  ): Promise<ExperimentRepetition> {
    return this.request<ExperimentRepetition>(
      `/experiments/${experimentId}/repetitions/${repetitionIdOrIndex}`
    );
  }

  async getRepetitionRuns(
    experimentId: string,
    repetitionIdOrIndex: string | number
  ): Promise<Run[]> {
    const res = await this.request<unknown>(
      `/experiments/${experimentId}/repetitions/${repetitionIdOrIndex}/runs`
    );
    return this.extractItems<Run>(res);
  }

  async getRepetitionResults(
    experimentId: string,
    repetitionIdOrIndex: string | number
  ): Promise<RunResult[]> {
    const res = await this.request<unknown>(
      `/experiments/${experimentId}/repetitions/${repetitionIdOrIndex}/results`
    );
    return this.extractItems<RunResult>(res);
  }

  async getRepetitionEvaluation(
    experimentId: string,
    repetitionIdOrIndex: string | number
  ): Promise<Evaluation> {
    return this.request<Evaluation>(
      `/experiments/${experimentId}/repetitions/${repetitionIdOrIndex}/evaluation`
    );
  }

  // ----------------------------------------------------------------
  // Evaluations
  // ----------------------------------------------------------------
  async createEvaluation(
    experimentId: string,
    data: EvaluationCreateRequest = {}
  ): Promise<Evaluation> {
    const search = new URLSearchParams();
    if (data.repetition_id) search.set('repetition_id', data.repetition_id);
    if (data.repetition_index !== undefined) search.set('repetition_index', String(data.repetition_index));
    const query = search.toString() ? `?${search.toString()}` : '';
    return this.request<Evaluation>(`/experiments/${experimentId}/evaluations${query}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async listEvaluations(
    experimentId: string,
    repetitionId?: string,
    repetitionIndex?: number
  ): Promise<Evaluation[]> {
    const search = new URLSearchParams();
    if (repetitionId) search.set('repetition_id', repetitionId);
    if (repetitionIndex !== undefined) search.set('repetition_index', String(repetitionIndex));
    const query = search.toString() ? `?${search.toString()}` : '';
    const res = await this.request<unknown>(`/experiments/${experimentId}/evaluations${query}`);
    return this.extractItems<Evaluation>(res);
  }

  async getEvaluation(experimentId: string, evaluationId: string): Promise<Evaluation> {
    return this.request<Evaluation>(`/experiments/${experimentId}/evaluations/${evaluationId}`);
  }

  async getMetrics(experimentId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(`/experiments/${experimentId}/metrics`);
  }

  // ----------------------------------------------------------------
  // Experiment Groups (Baseline vs EGAL)
  // ----------------------------------------------------------------
  async listExperimentGroups(): Promise<ExperimentGroup[]> {
    const res = await this.request<unknown>('/experiment-groups');
    return this.extractItems<ExperimentGroup>(res);
  }

  async createExperimentGroup(data: ExperimentGroupCreateRequest): Promise<ExperimentGroup> {
    return this.request<ExperimentGroup>('/experiment-groups', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async linkExperimentGroup(
    data: ExperimentGroupLinkRequest
  ): Promise<ExperimentGroupDetail> {
    const experimentIds =
      data.experiment_ids && data.experiment_ids.length >= 2
        ? data.experiment_ids
        : data.baseline_experiment_id && data.egal_experiment_id
        ? [data.baseline_experiment_id, data.egal_experiment_id]
        : [];

    const payload: {
      group_name: string;
      group_id?: string;
      experiment_ids: string[];
    } = {
      group_name: data.group_name || data.group_id || 'Comparison Group',
      experiment_ids: experimentIds,
    };
    if (data.group_id) {
      payload.group_id = data.group_id;
    }

    return this.request<ExperimentGroupDetail>(
      '/experiment-groups/link',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  }

  async getExperimentGroup(groupId: string): Promise<ExperimentGroupDetail> {
    return this.request<ExperimentGroupDetail>(`/experiment-groups/${groupId}`);
  }

  // ----------------------------------------------------------------
  // Analytics
  // ----------------------------------------------------------------
  async getAnalysisOptions(): Promise<AnalysisOptionsResponse> {
    return this.request<AnalysisOptionsResponse>('/analysis/options');
  }

  async getAnalysisReport(filter: AnalysisFilterRequest): Promise<AnalysisReportResponse> {
    return this.request<AnalysisReportResponse>('/analysis/report', {
      method: 'POST',
      body: JSON.stringify(filter),
    });
  }

  // ----------------------------------------------------------------
  // Exports (Download helper)
  // ----------------------------------------------------------------
  getExportUrl(type: 'experiment' | 'repetition' | 'evaluation' | 'group', params: {
    experimentId?: string;
    repetitionIdOrIndex?: string | number;
    evaluationId?: string;
    groupId?: string;
    format: 'csv' | 'jsonl';
  }): string {
    const { experimentId, repetitionIdOrIndex, evaluationId, groupId, format } = params;
    if (type === 'repetition' && experimentId && repetitionIdOrIndex !== undefined) {
      return `${this.baseUrl}/experiments/${experimentId}/repetitions/${repetitionIdOrIndex}/exports/${format}`;
    }
    if (type === 'evaluation' && experimentId && evaluationId) {
      return `${this.baseUrl}/experiments/${experimentId}/evaluations/${evaluationId}/exports/${format}`;
    }
    if (type === 'group' && groupId) {
      return `${this.baseUrl}/experiment-groups/${groupId}/exports/${format}`;
    }
    if (type === 'experiment' && experimentId) {
      return `${this.baseUrl}/experiments/${experimentId}/exports/${format}`;
    }
    throw new Error('Invalid export parameters');
  }
}

export const api = new ApiClient();
export default api;
