/**
 * Input Mapping Utilities for Research Arena
 *
 * Provides dynamic agent schema inspection, dataset field extraction,
 * auto-resolution, security filters (strictly excluding ground_truth and metadata),
 * and bidirectional serialization compliant with backend mapping contracts.
 */

export interface AgentFieldDef {
  name: string;
  label: string;
  type: string;
  required: boolean;
  description: string;
  defaultValue?: unknown;
}

export interface DatasetFieldItem {
  path: string; // e.g. "input.ticker" or "scenario_id"
  label: string; // e.g. "input.ticker (Nested)" or "scenario_id (Top-level)"
  group: 'nestedInput' | 'topLevel';
  type: string;
  sampleValue?: unknown;
}

export interface ExtractedDatasetFields {
  nestedInput: DatasetFieldItem[];
  topLevel: DatasetFieldItem[];
  all: DatasetFieldItem[];
}

export interface MappingValidationResult {
  isValid: boolean;
  missingRequired: string[];
  errors: string[];
  warnings: string[];
}

/**
 * Baseline and EGAL agents require these exact 9 fields defined in FinancialNewsInput.
 */
export const FINANCIAL_NEWS_AGENT_FIELDS: AgentFieldDef[] = [
  {
    name: 'schema_version',
    label: 'schema_version',
    type: 'string',
    required: true,
    description: "Contract schema version ('1.0')",
    defaultValue: '1.0',
  },
  {
    name: 'scenario_id',
    label: 'scenario_id',
    type: 'string',
    required: true,
    description: 'Scenario identifier (e.g. NORMAL-001, AMB-002)',
  },
  {
    name: 'ticker',
    label: 'ticker',
    type: 'string',
    required: true,
    description: 'Stock ticker symbol or UNKNOWN',
  },
  {
    name: 'company_name',
    label: 'company_name',
    type: 'string',
    required: true,
    description: 'Target company or entity name (e.g. ABC Motors)',
  },
  {
    name: 'task',
    label: 'task',
    type: 'string',
    required: true,
    description: 'Specific analytical task instructions for the model',
  },
  {
    name: 'retrieval_mode',
    label: 'retrieval_mode',
    type: 'enum',
    required: false,
    description: "Retrieval mode: 'provided_evidence' or 'tavily_live'",
    defaultValue: 'provided_evidence',
  },
  {
    name: 'search_query',
    label: 'search_query',
    type: 'string | null',
    required: false,
    description: 'Optional live search query when using retrieval',
  },
  {
    name: 'evidence',
    label: 'evidence',
    type: 'array',
    required: true,
    description: 'List of EvidenceRecord objects provided for analysis',
  },
  {
    name: 'ml_forecast',
    label: 'ml_forecast',
    type: 'object | null',
    required: false,
    description: 'Optional quantitative ML model forecast priors',
  },
];

/**
 * Returns dynamic field definitions for the specified agent.
 */
export function getAgentFields(
  agentId: string,
  inputSchema?: Record<string, unknown> | null
): AgentFieldDef[] {
  if (
    agentId === 'financial_news_analysis' ||
    agentId === 'financial_news_analysis_egal'
  ) {
    return FINANCIAL_NEWS_AGENT_FIELDS.map((f) => ({ ...f }));
  }

  // If inputSchema with JSON-schema properties is supplied
  if (inputSchema && typeof inputSchema === 'object' && inputSchema.properties) {
    const props = inputSchema.properties as Record<string, Record<string, unknown>>;
    const requiredList = Array.isArray(inputSchema.required)
      ? (inputSchema.required as string[])
      : [];

    return Object.entries(props).map(([name, prop]) => ({
      name,
      label: (prop.title as string) || name,
      type: (prop.type as string) || (prop.$ref ? 'object' : 'any'),
      required: requiredList.includes(name),
      description: (prop.description as string) || '',
      defaultValue: prop.default,
    }));
  }

  // Generic fallback if schema is unspecified
  return [
    {
      name: 'input',
      label: 'Input Payload',
      type: 'any',
      required: true,
      description: 'Primary input payload for the agent',
    },
  ];
}

/**
 * Evaluator-only and ground-truth fields that must NEVER be exposed or mapped to an agent.
 */
const FORBIDDEN_FIELDS = new Set(['ground_truth', 'metadata']);

export function isForbiddenField(fieldNameOrPath: string): boolean {
  if (!fieldNameOrPath) return false;
  const normalized = fieldNameOrPath.toLowerCase().trim();
  if (FORBIDDEN_FIELDS.has(normalized)) return true;
  if (normalized.startsWith('ground_truth.') || normalized.startsWith('ground_truth[')) return true;
  if (normalized.startsWith('metadata.') || normalized.startsWith('metadata[')) return true;
  return false;
}

/**
 * Extracts available source fields from a sample dataset record.
 * Clearly separates nested `input` object fields from top-level fields,
 * and rigorously filters out ground_truth and metadata.
 */
export function extractDatasetFields(
  sampleRecord: Record<string, unknown> | null | undefined
): ExtractedDatasetFields {
  const nestedInput: DatasetFieldItem[] = [];
  const topLevel: DatasetFieldItem[] = [];

  if (!sampleRecord || typeof sampleRecord !== 'object') {
    return { nestedInput: [], topLevel: [], all: [] };
  }

  // 1. Process nested "input" object if present (benchmark dataset standard)
  if (
    sampleRecord.input &&
    typeof sampleRecord.input === 'object' &&
    !Array.isArray(sampleRecord.input)
  ) {
    const inputObj = sampleRecord.input as Record<string, unknown>;
    for (const key of Object.keys(inputObj)) {
      if (isForbiddenField(key)) continue;

      const val = inputObj[key];
      const typeStr = Array.isArray(val)
        ? 'array'
        : val === null
        ? 'null'
        : typeof val;

      nestedInput.push({
        path: `input.${key}`,
        label: `input.${key}`,
        group: 'nestedInput',
        type: typeStr,
        sampleValue: val,
      });
    }
  }

  // 2. Process top-level fields
  for (const key of Object.keys(sampleRecord)) {
    // Skip "input" as its properties are handled in nestedInput
    if (key === 'input') continue;
    // Strictly exclude ground_truth, metadata, and private fields
    if (isForbiddenField(key)) continue;
    if (key.startsWith('_')) continue;

    const val = sampleRecord[key];
    const typeStr = Array.isArray(val)
      ? 'array'
      : val === null
      ? 'null'
      : typeof val;

    topLevel.push({
      path: key,
      label: key,
      group: 'topLevel',
      type: typeStr,
      sampleValue: val,
    });
  }

  return {
    nestedInput,
    topLevel,
    all: [...nestedInput, ...topLevel],
  };
}

/**
 * Auto-resolves mapping from agent fields to dataset source paths.
 * Resolves against nested `input.*` first (for benchmark datasets),
 * then top-level fields, with sensible fallback aliases.
 */
export function autoResolveMapping(
  agentFields: AgentFieldDef[],
  datasetFields: ExtractedDatasetFields
): Record<string, string> {
  const result: Record<string, string> = {};
  const nestedKeys = new Set(datasetFields.nestedInput.map((f) => f.path));
  const topKeys = new Set(datasetFields.topLevel.map((f) => f.path));

  for (const field of agentFields) {
    const target = field.name;

    // 1. Check nested input: input.<name>
    const nestedCandidate = `input.${target}`;
    if (nestedKeys.has(nestedCandidate)) {
      result[target] = nestedCandidate;
      continue;
    }

    // 2. Check top-level: <name>
    if (topKeys.has(target)) {
      result[target] = target;
      continue;
    }

    // 3. Check aliases
    let mapped = false;
    if (target === 'ticker') {
      const alias = ['input.symbol', 'symbol', 'input.stock', 'stock'].find(
        (k) => nestedKeys.has(k) || topKeys.has(k)
      );
      if (alias) {
        result[target] = alias;
        mapped = true;
      }
    } else if (target === 'evidence') {
      const alias = ['input.articles', 'articles', 'input.sources', 'sources', 'input.news', 'news'].find(
        (k) => nestedKeys.has(k) || topKeys.has(k)
      );
      if (alias) {
        result[target] = alias;
        mapped = true;
      }
    } else if (target === 'task') {
      const alias = ['input.instruction', 'instruction', 'input.prompt', 'prompt'].find(
        (k) => nestedKeys.has(k) || topKeys.has(k)
      );
      if (alias) {
        result[target] = alias;
        mapped = true;
      }
    } else if (target === 'company_name') {
      const alias = ['input.company', 'company'].find(
        (k) => nestedKeys.has(k) || topKeys.has(k)
      );
      if (alias) {
        result[target] = alias;
        mapped = true;
      }
    }

    if (!mapped) {
      result[target] = '';
    }
  }

  return result;
}

/**
 * Validates the current field mapping against agent requirements and dataset structure.
 * Returns isValid=false and actionable error messages if required fields are unmapped
 * or if forbidden fields are selected.
 */
export function validateMapping(
  agentFields: AgentFieldDef[],
  mapping: Record<string, string>,
  datasetFields?: ExtractedDatasetFields
): MappingValidationResult {
  const missingRequired: string[] = [];
  const errors: string[] = [];
  const warnings: string[] = [];

  const availablePaths = datasetFields && datasetFields.all.length > 0
    ? new Set(datasetFields.all.map((f) => f.path))
    : null;

  for (const field of agentFields) {
    const mappedSource = (mapping[field.name] || '').trim();

    if (field.required && !mappedSource) {
      missingRequired.push(field.name);
      errors.push(`Required agent field "${field.name}" is not mapped.`);
    }

    if (mappedSource) {
      if (isForbiddenField(mappedSource)) {
        errors.push(
          `Security violation: Field "${mappedSource}" contains evaluator ground truth or metadata and cannot be exposed to the agent.`
        );
      } else if (availablePaths && !availablePaths.has(mappedSource)) {
        warnings.push(
          `Source field "${mappedSource}" mapped to "${field.name}" was not observed in the dataset sample.`
        );
      }
    }
  }

  return {
    isValid: missingRequired.length === 0 && errors.length === 0,
    missingRequired,
    errors,
    warnings,
  };
}

/**
 * Serializes target-to-source mapping into backend's contract format:
 * { [sourceField]: targetField }
 * As defined in backend schemas/api.py: "Dataset source field to agent payload field".
 */
export function serializeInputMapping(targetToSource: Record<string, string>): Record<string, string> {
  const backendMapping: Record<string, string> = {};
  for (const [target, source] of Object.entries(targetToSource)) {
    if (source && source.trim() !== '') {
      backendMapping[source.trim()] = target;
    }
  }
  return backendMapping;
}

/**
 * Deserializes backend mapping into target-to-source mapping.
 * Handles both { [source]: target } and { [target]: source } seamlessly.
 */
export function deserializeInputMapping(
  backendMapping: Record<string, string> | undefined | null,
  agentFields: AgentFieldDef[]
): Record<string, string> {
  if (!backendMapping) return {};
  const targetNames = new Set(agentFields.map((f) => f.name));
  const targetToSource: Record<string, string> = {};

  for (const [key, val] of Object.entries(backendMapping)) {
    if (targetNames.has(val)) {
      targetToSource[val] = key;
    } else if (targetNames.has(key)) {
      targetToSource[key] = val;
    } else {
      targetToSource[key] = val;
    }
  }
  return targetToSource;
}
