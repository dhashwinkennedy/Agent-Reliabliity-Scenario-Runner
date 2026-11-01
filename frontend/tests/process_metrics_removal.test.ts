import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ApiClient } from '../src/api/client';
import type { Evaluation } from '../src/types';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Process Metrics Complete Removal Verification', () => {
  const client = new ApiClient('http://127.0.0.1:8000/api');

  test('1. ApiClient has no process metrics methods', () => {
    // None of the process metrics methods should exist on the ApiClient prototype or instance
    assert.equal(typeof (client as any).getProcessMetrics, 'undefined');
    assert.equal(typeof (client as any).listProcessEvaluations, 'undefined');
    assert.equal(typeof (client as any).getRunProcessEvents, 'undefined');

    // Standard outcome evaluation and experiment lifecycle methods must exist
    assert.equal(typeof client.getExperiment, 'function');
    assert.equal(typeof client.getRuns, 'function');
    assert.equal(typeof client.getResults, 'function');
    assert.equal(typeof client.getEvaluation, 'function');
    assert.equal(typeof client.createEvaluation, 'function');
    assert.equal(typeof client.getMetrics, 'function');
    assert.equal(typeof client.getExportUrl, 'function');
  });

  test('2. ExperimentDetail source contains exactly the 7 required tabs in order', () => {
    const experimentDetailPath = path.resolve(__dirname, '../src/components/experiments/ExperimentDetail.tsx');
    const content = fs.readFileSync(experimentDetailPath, 'utf-8');

    // TabType definition check
    assert.match(
      content,
      /type\s+TabType\s*=\s*(?:\|\s*)?'overview'\s*\|\s*'runs'\s*\|\s*'results'\s*\|\s*'evaluation'\s*\|\s*'provenance'\s*\|\s*'mapping'\s*\|\s*'exports'/,
      'TabType must only contain the 7 valid tabs'
    );
    assert.doesNotMatch(content, /'process'/, 'TabType must not contain "process"');

    // Tab buttons list check
    const requiredTabIds = [
      'overview',
      'runs',
      'results',
      'evaluation',
      'provenance',
      'mapping',
      'exports',
    ];

    for (const tabId of requiredTabIds) {
      assert.ok(content.includes(`id: '${tabId}'`), `Tab ${tabId} must be present`);
    }

    assert.ok(content.includes("label: 'Overview'"), 'Overview tab label must be present');
    assert.ok(content.includes("label: `Runs (${runsTotal})`"), 'Runs tab dynamic label must be present');
    assert.ok(content.includes("label: 'Persisted Results'"), 'Persisted Results tab label must be present');
    assert.ok(content.includes("label: 'Evaluation Metrics'"), 'Evaluation Metrics tab label must be present');
    assert.ok(content.includes("label: 'Provenance Manifest'"), 'Provenance Manifest tab label must be present');
    assert.ok(content.includes("label: 'Input Mapping'"), 'Input Mapping tab label must be present');
    assert.ok(content.includes("label: 'Exports'"), 'Exports tab label must be present');

    // Process tab must not exist in tab list or JSX blocks
    assert.doesNotMatch(content, /id:\s*'process'/);
    assert.doesNotMatch(content, /label:\s*'Process Metrics'/);
    assert.doesNotMatch(content, /activeTab\s*===\s*'process'/);
    assert.doesNotMatch(content, /processMetrics/);
  });

  test('3. Evaluation Metrics tab preserves all 6 outcome evaluation metrics', () => {
    const experimentDetailPath = path.resolve(__dirname, '../src/components/experiments/ExperimentDetail.tsx');
    const content = fs.readFileSync(experimentDetailPath, 'utf-8');

    const requiredOutcomeMetrics = [
      { key: 'task_completion_rate', label: 'Task Completion Rate' },
      { key: 'unsupported_action_rate', label: 'Unsupported Action Rate' },
      { key: 'recovery_rate', label: 'Recovery Rate' },
      { key: 'consistency_rate', label: 'Consistency Rate' },
      { key: 'false_success_rate', label: 'False Success Rate' },
      { key: 'coveragePct', label: 'Run Coverage' },
    ];

    for (const metric of requiredOutcomeMetrics) {
      assert.ok(content.includes(metric.key), `Evaluation tab must reference metric ${metric.key}`);
      assert.ok(content.includes(metric.label), `Evaluation tab must display label ${metric.label}`);
    }

    // Verify Evaluation object structure supports all 6 outcome metrics
    const sampleEvaluation: Evaluation = {
      id: 'eval_outcome_001',
      experiment_id: 'exp_001',
      created_at: '2026-10-27T12:00:00Z',
      metric_definition_version: 'research-metrics-v1',
      evaluation_schema_version: 'evaluation-v1',
      status: 'completed',
      manifest: {
        coverage_percentage: 100.0,
        completed_run_count: 50,
        expected_run_count: 50,
      },
      metrics: {
        task_completion_rate: {
          metric_name: 'task_completion_rate',
          metric_version: 'research-metrics-v1',
          numerator: 45,
          denominator: 50,
          percentage: 90.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Deterministic evaluation'],
        },
        unsupported_action_rate: {
          metric_name: 'unsupported_action_rate',
          metric_version: 'research-metrics-v1',
          numerator: 1,
          denominator: 10,
          percentage: 10.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates ungrounded actions'],
        },
        recovery_rate: {
          metric_name: 'recovery_rate',
          metric_version: 'research-metrics-v1',
          numerator: 8,
          denominator: 10,
          percentage: 80.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates recovery from disruption'],
        },
        consistency_rate: {
          metric_name: 'consistency_rate',
          metric_version: 'research-metrics-v1',
          numerator: 40,
          denominator: 50,
          percentage: 80.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates decision stability'],
        },
        false_success_rate: {
          metric_name: 'false_success_rate',
          metric_version: 'research-metrics-v1',
          numerator: 2,
          denominator: 50,
          percentage: 4.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates false positives'],
        },
      },
    };

    assert.equal(sampleEvaluation.metrics?.task_completion_rate?.percentage, 90.0);
    assert.equal(sampleEvaluation.metrics?.unsupported_action_rate?.percentage, 10.0);
    assert.equal(sampleEvaluation.metrics?.recovery_rate?.percentage, 80.0);
    assert.equal(sampleEvaluation.metrics?.consistency_rate?.percentage, 80.0);
    assert.equal(sampleEvaluation.metrics?.false_success_rate?.percentage, 4.0);
    assert.equal(sampleEvaluation.manifest?.coverage_percentage, 100.0);
  });

  test('4. Type definitions and API client source do not retain ProcessMetricsSummary', () => {
    const typesPath = path.resolve(__dirname, '../src/types/index.ts');
    const typesContent = fs.readFileSync(typesPath, 'utf-8');
    assert.doesNotMatch(typesContent, /ProcessMetricsSummary/);

    const clientPath = path.resolve(__dirname, '../src/api/client.ts');
    const clientContent = fs.readFileSync(clientPath, 'utf-8');
    assert.doesNotMatch(clientContent, /ProcessMetricsSummary/);
    assert.doesNotMatch(clientContent, /process-metrics/);
    assert.doesNotMatch(clientContent, /process-evaluations/);
    assert.doesNotMatch(clientContent, /process-events/);
  });
});
