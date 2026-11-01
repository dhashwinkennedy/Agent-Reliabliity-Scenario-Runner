import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  getAgentFields,
  extractDatasetFields,
  isForbiddenField,
  autoResolveMapping,
  validateMapping,
  serializeInputMapping,
  deserializeInputMapping,
  FINANCIAL_NEWS_AGENT_FIELDS,
} from '../src/utils/inputMapping.js';

describe('Input Field Mapping — Dynamic Agent Schemas, Dataset Resolution, and Security Isolation', () => {
  // Path to the actual benchmark dataset
  const benchmarkDatasetPath = path.resolve(
    process.cwd(),
    '../backend/data/datasets/beab437db45f4aec891955f8c739c372-financial_news_dataset_v1_fixed.json'
  );

  let realBenchmarkRecord: Record<string, unknown>;

  try {
    const rawData = fs.readFileSync(benchmarkDatasetPath, 'utf-8');
    const records = JSON.parse(rawData);
    realBenchmarkRecord = records[0];
  } catch {
    // Fallback benchmark fixture matching the exact backend schema
    realBenchmarkRecord = {
      record_schema_version: '1.0',
      scenario_id: 'NORMAL-001',
      category: 'normal',
      input: {
        schema_version: '1.0',
        scenario_id: 'NORMAL-001',
        ticker: 'ABCM.SYN',
        company_name: 'ABC Motors',
        task: 'Produce a structured analysis',
        retrieval_mode: 'provided_evidence',
        search_query: null,
        evidence: [
          {
            evidence_id: 'E1',
            type: 'news',
            title: 'Quarterly earnings',
            content: 'Revenue was 12000.',
            source_name: 'Synthetic',
            url: 'https://example.invalid',
          },
        ],
        ml_forecast: null,
      },
      ground_truth: {
        annotation_version: '1.0',
        expected_task_completion: true,
        supported_facts: [{ text: 'Revenue was 12000.', evidence_ids: ['E1'] }],
      },
      metadata: {
        evaluator_notes: 'Synthetic record for benchmarking',
      },
    };
  }

  test('generates dynamic mapping fields for financial_news_analysis (Baseline)', () => {
    const fields = getAgentFields('financial_news_analysis');
    assert.equal(fields.length, 9, 'Must generate exactly 9 input fields');

    const expectedFields = [
      { name: 'schema_version', required: true, type: 'string' },
      { name: 'scenario_id', required: true, type: 'string' },
      { name: 'ticker', required: true, type: 'string' },
      { name: 'company_name', required: true, type: 'string' },
      { name: 'task', required: true, type: 'string' },
      { name: 'retrieval_mode', required: false, type: 'enum' },
      { name: 'search_query', required: false, type: 'string | null' },
      { name: 'evidence', required: true, type: 'array' },
      { name: 'ml_forecast', required: false, type: 'object | null' },
    ];

    for (const expected of expectedFields) {
      const found = fields.find((f) => f.name === expected.name);
      assert.ok(found, `Field ${expected.name} must be supported`);
      assert.equal(found.required, expected.required, `${expected.name} required status mismatch`);
      assert.equal(found.type, expected.type, `${expected.name} type mismatch`);
    }
  });

  test('generates identical dynamic mapping fields for financial_news_analysis_egal (EGAL)', () => {
    const fields = getAgentFields('financial_news_analysis_egal');
    assert.equal(fields.length, 9, 'EGAL agent must also support the exact 9 input fields');

    const names = fields.map((f) => f.name);
    assert.deepEqual(names, [
      'schema_version',
      'scenario_id',
      'ticker',
      'company_name',
      'task',
      'retrieval_mode',
      'search_query',
      'evidence',
      'ml_forecast',
    ]);
  });

  test('dynamically extracts fields from generic agent JSON schema', () => {
    const customSchema = {
      type: 'object',
      properties: {
        document_text: { type: 'string', description: 'The text to summarize' },
        max_words: { type: 'integer', description: 'Max word count' },
      },
      required: ['document_text'],
    };

    const fields = getAgentFields('custom_summarizer', customSchema);
    assert.equal(fields.length, 2);
    const docField = fields.find((f) => f.name === 'document_text');
    assert.ok(docField?.required);
    assert.equal(docField?.type, 'string');

    const wordsField = fields.find((f) => f.name === 'max_words');
    assert.equal(wordsField?.required, false);
  });

  test('resolves dataset fields and strictly distinguishes nested "input.*" from top-level fields', () => {
    const extracted = extractDatasetFields(realBenchmarkRecord);

    // Verify nested input fields
    const nestedPaths = extracted.nestedInput.map((f) => f.path);
    assert.ok(nestedPaths.includes('input.schema_version'));
    assert.ok(nestedPaths.includes('input.scenario_id'));
    assert.ok(nestedPaths.includes('input.ticker'));
    assert.ok(nestedPaths.includes('input.company_name'));
    assert.ok(nestedPaths.includes('input.task'));
    assert.ok(nestedPaths.includes('input.retrieval_mode'));
    assert.ok(nestedPaths.includes('input.evidence'));

    // Verify top-level fields
    const topPaths = extracted.topLevel.map((f) => f.path);
    assert.ok(topPaths.includes('record_schema_version'));
    assert.ok(topPaths.includes('scenario_id'));
    assert.ok(topPaths.includes('category'));

    // Verify input object itself is not listed as a top-level field (avoiding recursion)
    assert.ok(!topPaths.includes('input'));
  });

  test('strictly forbids and excludes ground_truth and metadata from available fields', () => {
    const extracted = extractDatasetFields(realBenchmarkRecord);

    const allPaths = extracted.all.map((f) => f.path);
    for (const path of allPaths) {
      assert.ok(!path.includes('ground_truth'), `Forbidden ground_truth found in path: ${path}`);
      assert.ok(!path.includes('metadata'), `Forbidden metadata found in path: ${path}`);
    }

    assert.equal(isForbiddenField('ground_truth'), true);
    assert.equal(isForbiddenField('ground_truth.annotation_version'), true);
    assert.equal(isForbiddenField('ground_truth.supported_facts'), true);
    assert.equal(isForbiddenField('metadata'), true);
    assert.equal(isForbiddenField('metadata.evaluator_notes'), true);
    assert.equal(isForbiddenField('input.ticker'), false);
    assert.equal(isForbiddenField('scenario_id'), false);
  });

  test('auto-resolves mapping against actual uploaded benchmark dataset record', () => {
    const agentFields = getAgentFields('financial_news_analysis');
    const extracted = extractDatasetFields(realBenchmarkRecord);

    const autoMap = autoResolveMapping(agentFields, extracted);

    assert.equal(autoMap['schema_version'], 'input.schema_version');
    assert.equal(autoMap['scenario_id'], 'input.scenario_id');
    assert.equal(autoMap['ticker'], 'input.ticker');
    assert.equal(autoMap['company_name'], 'input.company_name');
    assert.equal(autoMap['task'], 'input.task');
    assert.equal(autoMap['retrieval_mode'], 'input.retrieval_mode');
    assert.equal(autoMap['evidence'], 'input.evidence');

    // Validate the auto-resolved mapping
    const validation = validateMapping(agentFields, autoMap, extracted);
    assert.equal(validation.isValid, true, 'Auto-resolved mapping for benchmark record must be valid');
    assert.equal(validation.missingRequired.length, 0);
    assert.equal(validation.errors.length, 0);
  });

  test('handles fallback aliases when fields have alternative names', () => {
    const agentFields = getAgentFields('financial_news_analysis');
    const flatRecordWithAliases = {
      scenario_id: 'SCENARIO-99',
      symbol: 'MSFT',
      company: 'Microsoft',
      instruction: 'Analyze sentiment',
      articles: [{ evidence_id: 'E1' }],
    };

    const extracted = extractDatasetFields(flatRecordWithAliases);
    const autoMap = autoResolveMapping(agentFields, extracted);

    assert.equal(autoMap['ticker'], 'symbol');
    assert.equal(autoMap['company_name'], 'company');
    assert.equal(autoMap['task'], 'instruction');
    assert.equal(autoMap['evidence'], 'articles');
  });

  test('shows clear validation error when required fields are unmapped', () => {
    const agentFields = getAgentFields('financial_news_analysis');
    const incompleteMapping: Record<string, string> = {
      schema_version: 'input.schema_version',
      // scenario_id missing!
      // ticker missing!
      company_name: 'input.company_name',
      task: 'input.task',
      evidence: '', // empty required
    };

    const validation = validateMapping(agentFields, incompleteMapping);
    assert.equal(validation.isValid, false);
    assert.ok(validation.missingRequired.includes('scenario_id'));
    assert.ok(validation.missingRequired.includes('ticker'));
    assert.ok(validation.missingRequired.includes('evidence'));
    assert.ok(validation.errors.some((e) => e.includes('ticker')));
    assert.ok(validation.errors.some((e) => e.includes('scenario_id')));
    assert.ok(validation.errors.some((e) => e.includes('evidence')));
  });

  test('rejects attempt to map ground_truth or metadata to agent', () => {
    const agentFields = getAgentFields('financial_news_analysis');
    const maliciousMapping: Record<string, string> = {
      schema_version: 'input.schema_version',
      scenario_id: 'input.scenario_id',
      ticker: 'input.ticker',
      company_name: 'input.company_name',
      task: 'ground_truth.annotation_version', // Violation!
      evidence: 'input.evidence',
    };

    const validation = validateMapping(agentFields, maliciousMapping);
    assert.equal(validation.isValid, false);
    assert.ok(validation.errors.some((e) => e.includes('ground truth or metadata')));
  });

  test('serializes mapping into backend contract: { [sourceField]: targetField }', () => {
    const targetToSource = {
      schema_version: 'input.schema_version',
      scenario_id: 'input.scenario_id',
      ticker: 'input.ticker',
      company_name: 'input.company_name',
      task: 'input.task',
      evidence: 'input.evidence',
      retrieval_mode: '', // Should be omitted if unset
    };

    const backendPayload = serializeInputMapping(targetToSource);

    // In backend contract, KEY is dataset source field, VALUE is agent target field
    assert.equal(backendPayload['input.schema_version'], 'schema_version');
    assert.equal(backendPayload['input.scenario_id'], 'scenario_id');
    assert.equal(backendPayload['input.ticker'], 'ticker');
    assert.equal(backendPayload['input.company_name'], 'company_name');
    assert.equal(backendPayload['input.task'], 'task');
    assert.equal(backendPayload['input.evidence'], 'evidence');
    assert.equal(backendPayload[''], undefined);
  });

  test('deserializes backend mapping back into UI targetToSource format', () => {
    const agentFields = FINANCIAL_NEWS_AGENT_FIELDS;
    const backendPayload = {
      'input.ticker': 'ticker',
      'input.company_name': 'company_name',
      'input.evidence': 'evidence',
    };

    const restored = deserializeInputMapping(backendPayload, agentFields);
    assert.equal(restored['ticker'], 'input.ticker');
    assert.equal(restored['company_name'], 'input.company_name');
    assert.equal(restored['evidence'], 'input.evidence');
  });
});
