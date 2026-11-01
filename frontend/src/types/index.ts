// Research Arena - Core TypeScript Types conforming to FastAPI Backend Schemas

export interface ApiErrorDetail {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ApiErrorResponse {
  error: ApiErrorDetail;
}

export interface PaginationParams {
  offset?: number;
  limit?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
  next_offset: number | null;
}

// ----------------------------------------------------
// Datasets & Snapshots
// ----------------------------------------------------

export type DatasetFormat = 'json' | 'jsonl';
export type ValidationStatus = 'valid' | 'invalid' | 'warning' | 'pending';

export interface Dataset {
  id: string;
  display_name: string;
  original_filename: string;
  format: DatasetFormat;
  size_bytes: number;
  record_count: number;
  validation_status: ValidationStatus;
  validation_errors: string[];
  validation_warnings: string[];
  schema_info?: Record<string, unknown> | null;
  created_at: string;
  snapshots?: DatasetSnapshot[];
}

export interface DatasetRecordItem {
  index: number;
  record: Record<string, unknown>;
}

export interface DatasetSnapshot {
  id: string;
  dataset_id: string;
  name: string;
  fingerprint: string;
  record_count: number;
  created_at: string;
}

// ----------------------------------------------------
// Agents
// ----------------------------------------------------

export interface AgentMetadata {
  id: string;
  name: string;
  display_name: string;
  description: string;
  version: string;
  author?: string;
  status: string; // e.g. "ready", "disabled"
  capabilities: string[];
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  is_builtin: boolean;
  created_at?: string;
}

// ----------------------------------------------------
// Providers & Models
// ----------------------------------------------------

export interface Provider {
  id: string;
  name: string;
  provider_type: 'openai_compatible' | string; // backend strictly enforces "openai_compatible"
  base_url?: string | null;
  api_key_configured: boolean;
  default_model?: string | null;
  models?: string[];
  organization?: string | null;
  created_at: string;
}

export interface ProviderCreateRequest {
  id?: string;
  name: string;
  provider_type: 'openai_compatible' | string;
  api_key?: string;
  base_url?: string;
  default_model?: string;
  organization?: string;
}

export interface ProviderUpdateRequest {
  name?: string;
  api_key?: string;
  base_url?: string;
  default_model?: string;
  organization?: string;
}

export interface ProviderCheck {
  name: string;
  ok: boolean;
  models?: string[];
  model?: string;
}

export interface ProviderConnectionTest {
  ok: boolean;
  reachable: boolean;
  latency_ms: number;
  checks: ProviderCheck[];
  errors: string[];
}

// ----------------------------------------------------
// Experiments & Repetitions
// ----------------------------------------------------

export type ExperimentStatus =
  | 'draft'
  | 'queued'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'stopped';

export interface Experiment {
  id: string;
  name: string;
  description?: string | null;
  dataset_snapshot_id: string;
  agent_id: string;
  provider_id: string;
  model: string;
  status: ExperimentStatus;
  configuration: Record<string, unknown>;
  input_mapping: Record<string, string>;
  repetition_count?: number;
  group_id?: string | null;
  group_name?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface ExperimentCreateRequest {
  name: string;
  description?: string;
  dataset_snapshot_id: string;
  agent_id: string;
  provider_id: string;
  model?: string;
  configuration?: Record<string, unknown>;
  input_mapping?: Record<string, string>;
  group_id?: string;
  group_name?: string;
}

export interface ExperimentRepetition {
  id: string;
  experiment_id: string;
  repetition_index: number;
  status: ExperimentStatus;
  idempotency_key?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  run_count: number;
  completed_run_count: number;
  failed_run_count: number;
  evaluation_id?: string | null;
  evaluation?: Evaluation | null;
  error?: string | ApiErrorDetail | Record<string, unknown> | null;
}

export interface ExperimentRerunRequest {
  idempotency_key?: string;
}

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface Run {
  id: string;
  experiment_id: string;
  repetition_id?: string | null;
  repetition_index?: number | null;
  dataset_item_id: string;
  status: RunStatus;
  input_data: Record<string, unknown>;
  output_data?: Record<string, unknown> | null;
  tokens_used?: number | null;
  latency_ms?: number | null;
  error?: string | ApiErrorDetail | Record<string, unknown> | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface RunsResponse extends PaginatedResponse<Run> {
  total_persisted_runs: number;
  expected_run_count: number;
}

export interface RunResult {
  run_id: string;
  repetition_id?: string | null;
  repetition_index?: number | null;
  dataset_item_id: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  ground_truth?: Record<string, unknown> | null;
  latency_ms?: number | null;
  tokens_used?: number | null;
  error?: string | ApiErrorDetail | Record<string, unknown> | null;
}

// ----------------------------------------------------
// Evaluation & Metrics
// ----------------------------------------------------

export interface MetricResult {
  metric_name: string;
  metric_version: string;
  numerator: number;
  denominator: number;
  percentage?: number | null;
  coverage_percentage?: number | null;
  status: 'complete' | 'partial' | 'not_assessable' | string;
  excluded?: number;
  missing?: number;
  review?: number;
  notes?: string[];
  details?: Record<string, unknown>;
}

export interface EvaluationManifest {
  experiment_id?: string;
  repetition_id?: string | null;
  repetition_index?: number | null;
  evaluation_id?: string;
  dataset_snapshot_id?: string;
  dataset_fingerprint?: string;
  metric_definition_version?: string;
  evaluation_schema_version?: string;
  evaluated_run_ids?: string[];
  expected_run_count?: number;
  completed_run_count?: number;
  failed_run_count?: number;
  missing_run_count?: number;
  excluded_run_count?: number;
  review_required_count?: number;
  evaluation_status?: string;
  coverage_percentage?: number;
  [key: string]: unknown;
}

export interface RunEvaluationItem {
  id: string;
  evaluation_id: string;
  run_id: string;
  scenario_id: string;
  category: string;
  execution_status: string;
  output_schema_valid: boolean;
  task_completion: Record<string, unknown>;
  claim_assessments?: unknown[];
  unsupported_action: Record<string, unknown>;
  recovery: Record<string, unknown>;
  false_success: Record<string, unknown>;
  decision_signature?: Record<string, unknown>;
  exclusions?: unknown[];
  warnings?: unknown[];
  review_required?: boolean;
  created_at?: string;
}

export interface SummaryMetrics {
  total_runs?: number;
  completed_runs?: number;
  failed_runs?: number;
  accuracy?: number;
  macro_f1?: number;
  abstention_rate?: number;
  task_completion_rate?: number;
  unsupported_action_rate?: number;
  recovery_rate?: number;
  consistency_rate?: number;
  false_success_rate?: number;
  coverage?: number;
  [key: string]: unknown;
}

export interface Evaluation {
  id: string;
  experiment_id: string;
  repetition_id?: string | null;
  repetition_index?: number | null;
  dataset_snapshot_id?: string;
  dataset_fingerprint?: string;
  evaluation_schema_version?: string;
  metric_definition_version?: string;
  name?: string;
  metric_version?: string;
  status?: string;
  expected_run_count?: number;
  metrics: Record<string, MetricResult>;
  manifest?: EvaluationManifest;
  run_evaluations?: RunEvaluationItem[];
  created_at: string;
  completed_at?: string | null;
  // Legacy / optional fields for backward compatibility
  summary_metrics?: SummaryMetrics;
  detailed_metrics?: Record<string, unknown>;
  coverage?: Record<string, unknown>;
  exclusions?: Record<string, unknown>;
}

export interface EvaluationCreateRequest {
  name?: string;
  repetition_id?: string;
  repetition_index?: number;
  force?: boolean;
}

// ----------------------------------------------------
// Experiment Groups (Baseline vs EGAL)
// ----------------------------------------------------

export interface ExperimentGroup {
  id: string;
  name: string;
  dataset_snapshot_id: string;
  provider_id: string;
  model: string;
  created_at: string;
  experiment_count?: number;
  has_baseline?: boolean;
  has_egal?: boolean;
}

export interface ExperimentGroupCreateRequest {
  name: string;
  dataset_snapshot_id: string;
  provider_id: string;
  model: string;
}

export interface ExperimentGroupLinkRequest {
  group_name: string;
  experiment_ids?: string[];
  group_id?: string;
  baseline_experiment_id?: string;
  egal_experiment_id?: string;
}

export interface PairedRepetitionComparison {
  repetition_index: number;
  baseline_metrics?: SummaryMetrics | Record<string, unknown> | null;
  egal_metrics?: SummaryMetrics | Record<string, unknown> | null;
  deltas?: Record<string, unknown> | null;
  comparison?: {
    deltas?: Record<string, unknown>;
    baseline_metrics?: Record<string, MetricResult>;
    egal_metrics?: Record<string, MetricResult>;
  };
}

export interface ExperimentGroupDetail {
  id: string;
  name: string;
  group_id?: string;
  group_name?: string;
  dataset_snapshot_id: string;
  provider_id: string;
  model: string;
  created_at: string;
  across_repetition_summary?: any;
  baseline?: {
    experiment?: Experiment | null;
    condition?: string;
    repetitions?: ExperimentRepetition[];
    repetition_count?: number;
    latest_evaluation?: Evaluation | null;
  };
  egal?: {
    experiment?: Experiment | null;
    condition?: string;
    repetitions?: ExperimentRepetition[];
    repetition_count?: number;
    latest_evaluation?: Evaluation | null;
  };
  comparison?: {
    deltas?: Record<string, { delta: number | null; baseline: number | null; egal: number | null; higher_is_better?: boolean; is_improvement?: boolean | null }>;
    baseline_metrics?: Record<string, MetricResult>;
    egal_metrics?: Record<string, MetricResult>;
    [key: string]: unknown;
  };
  repetition_comparisons?: Array<{
    repetition_index: number;
    baseline_repetition?: ExperimentRepetition | null;
    egal_repetition?: ExperimentRepetition | null;
    comparison?: {
      deltas?: Record<string, { delta: number | null; baseline: number | null; egal: number | null; higher_is_better?: boolean; is_improvement?: boolean | null }>;
      baseline_metrics?: Record<string, MetricResult>;
      egal_metrics?: Record<string, MetricResult>;
      [key: string]: unknown;
    };
  }>;
  // Convenience aliases for frontend consumption
  baseline_experiment?: {
    id: string;
    name: string;
    agent_id: string;
    status: ExperimentStatus;
    repetitions: Array<ExperimentRepetition & { evaluation?: Evaluation | null }>;
  } | null;
  egal_experiment?: {
    id: string;
    name: string;
    agent_id: string;
    status: ExperimentStatus;
    repetitions: Array<ExperimentRepetition & { evaluation?: Evaluation | null }>;
  } | null;
  comparisons?: {
    deltas?: Record<string, number>;
    repetitions?: PairedRepetitionComparison[];
  };
}

// ----------------------------------------------------
// Analysis Options & Reports
// ----------------------------------------------------

export interface AnalysisOptionsResponse {
  datasets: Array<{ id: string; name: string }>;
  models: string[];
  providers: string[];
  conditions: string[];
  metrics: string[];
}

export interface AnalysisFilterRequest {
  dataset_id?: string;
  model?: string;
  provider_id?: string;
  group_id?: string;
}

export interface AnalysisReportResponse {
  dataset_id?: string;
  model?: string;
  conditions: Record<string, unknown>;
  comparisons: Record<string, unknown>;
  summary: Record<string, unknown>;
}
