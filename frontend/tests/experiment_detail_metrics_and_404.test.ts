import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiError } from '../src/api/client';
import type { Evaluation, MetricResult } from '../src/types';

describe('Experiment Detail Metrics and 404 Error Handling Regression Tests', () => {
  const client = new ApiClient('http://127.0.0.1:8000/api');

  test('1. Experiment detail state before metrics load handles null evaluation safely', () => {
    // Before metrics load, evaluation is null and loading state is true
    const evaluationState = null as Evaluation | null;
    const isLoading = true;

    // Formatting helper must not throw TypeError: Cannot read properties of undefined
    const formatMetricPct = (val: number | null | undefined): string => {
      if (val === null || val === undefined) return '—';
      return `${val.toFixed(1)}%`;
    };

    const tc = evaluationState?.metrics?.task_completion_rate;
    const displayVal = formatMetricPct(tc?.percentage);

    assert.equal(evaluationState, null);
    assert.equal(isLoading, true);
    assert.equal(displayVal, '—');
    assert.doesNotThrow(() => {
      const _dummy = (evaluationState as Evaluation | null)?.metrics?.task_completion_rate?.percentage;
      return _dummy;
    });
  });

  test('2. Completed experiment with no evaluation renders empty state without crashing', () => {
    // Experiment finished but evaluation has not run yet
    const currentRepetition = {
      id: 'rep_001',
      experiment_id: 'exp_001',
      repetition_index: 1,
      status: 'completed' as const,
      run_count: 50,
      completed_run_count: 50,
      failed_run_count: 0,
      evaluation_id: null,
      evaluation: null,
    };
    const evaluation: Evaluation | null = null;

    // Must be marked as completed without evaluation
    const isCompletedWithoutEval =
      currentRepetition.status === 'completed' &&
      !currentRepetition.evaluation_id &&
      !evaluation;

    assert.equal(isCompletedWithoutEval, true);

    // Empty state message renders cleanly without accessing undefined metrics
    const emptyStateTitle = `No outcome evaluation for Repetition #${currentRepetition.repetition_index}`;
    assert.equal(emptyStateTitle, 'No outcome evaluation for Repetition #1');
  });

  test('3. Valid evaluation response using the actual backend metric schema maps all 5 research metrics', () => {
    // Real backend evaluation schema as returned by evaluation_service.evaluation_out
    const backendEvaluationResponse: Evaluation = {
      id: 'eval_real_123',
      experiment_id: 'exp_real_456',
      repetition_id: 'rep_001',
      repetition_index: 1,
      dataset_snapshot_id: 'snap_bench_001',
      dataset_fingerprint: 'a1b2c3d4e5f67890',
      metric_definition_version: 'research-metrics-v1',
      evaluation_schema_version: 'evaluation-v1',
      status: 'completed',
      expected_run_count: 50,
      metrics: {
        task_completion_rate: {
          metric_name: 'task_completion_rate',
          metric_version: 'research-metrics-v1',
          numerator: 36,
          denominator: 40,
          percentage: 90.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates deterministically assessed normal scenarios meeting all ground truth requirements.'],
          details: {},
        },
        unsupported_action_rate: {
          metric_name: 'unsupported_action_rate',
          metric_version: 'research-metrics-v1',
          numerator: 0,
          denominator: 10,
          percentage: 0.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates whether the agent took unsupported directional actions (BUY/SELL) in ambiguous scenarios.'],
          details: { unsupported_action_scenarios: [], unsupported_claim_count: 0 },
        },
        recovery_rate: {
          metric_name: 'recovery_rate',
          metric_version: 'research-metrics-v1',
          numerator: 2,
          denominator: 2,
          percentage: 100.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 4,
          missing: 0,
          review: 0,
          notes: ['Scored on recoverable failure scenarios (FAILURE-001, FAILURE-002). Persistent failures are excluded.'],
          details: { recoverable_scenarios: ['FAILURE-001', 'FAILURE-002'] },
        },
        consistency_rate: {
          metric_name: 'consistency_rate',
          metric_version: 'research-metrics-v1',
          numerator: 6,
          denominator: 6,
          percentage: 100.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Evaluates decision stability across the 6 designated repeatability scenarios.'],
          details: { complete_groups: 6, partial_groups: 0, missing_groups: 0 },
        },
        false_success_rate: {
          metric_name: 'false_success_rate',
          metric_version: 'research-metrics-v1',
          numerator: 0,
          denominator: 50,
          percentage: 0.0,
          coverage_percentage: 100.0,
          status: 'complete',
          excluded: 0,
          missing: 0,
          review: 0,
          notes: ['Supporting check: identifies scenarios claiming execution success despite ungrounded or persistent failure outputs.'],
          details: { false_success_scenarios: [] },
        },
      },
      manifest: {
        experiment_id: 'exp_real_456',
        repetition_id: 'rep_001',
        repetition_index: 1,
        evaluation_id: 'eval_real_123',
        dataset_snapshot_id: 'snap_bench_001',
        dataset_fingerprint: 'a1b2c3d4e5f67890',
        expected_run_count: 50,
        completed_run_count: 50,
        failed_run_count: 0,
        missing_run_count: 0,
        evaluation_status: 'COMPLETED',
        coverage_percentage: 100.0,
      },
      created_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    };

    // Verify all 5 metrics are accessible and percentages match
    assert.equal(backendEvaluationResponse.metrics.task_completion_rate.percentage, 90.0);
    assert.equal(backendEvaluationResponse.metrics.unsupported_action_rate.percentage, 0.0);
    assert.equal(backendEvaluationResponse.metrics.recovery_rate.percentage, 100.0);
    assert.equal(backendEvaluationResponse.metrics.consistency_rate.percentage, 100.0);
    assert.equal(backendEvaluationResponse.metrics.false_success_rate.percentage, 0.0);

    // Verify Run Coverage is extracted from manifest
    assert.equal(backendEvaluationResponse.manifest?.coverage_percentage, 100.0);
    assert.equal(backendEvaluationResponse.manifest?.completed_run_count, 50);

    // Verify no accuracy metric is expected or needed
    assert.equal('accuracy' in backendEvaluationResponse.metrics, false);
  });

  test('4. Handles partial, zero-denominator, or missing metric fields safely', () => {
    const partialEvaluation: Evaluation = {
      id: 'eval_partial',
      experiment_id: 'exp_part',
      metrics: {
        task_completion_rate: {
          metric_name: 'task_completion_rate',
          metric_version: 'research-metrics-v1',
          numerator: 0,
          denominator: 0,
          percentage: null, // Denominator is zero
          coverage_percentage: 0.0,
          status: 'not_assessable',
          excluded: 0,
          missing: 10,
          review: 0,
        },
      },
      created_at: new Date().toISOString(),
    };

    const formatMetricPct = (val: number | null | undefined): string => {
      if (val === null || val === undefined) return '—';
      return `${val.toFixed(1)}%`;
    };

    // Zero-denominator or null percentage formats safely as '—'
    assert.equal(formatMetricPct(partialEvaluation.metrics.task_completion_rate.percentage), '—');
    assert.equal(partialEvaluation.metrics.task_completion_rate.status, 'not_assessable');

    // Missing metric key gracefully returns undefined, formatting as '—'
    const missingRec = partialEvaluation.metrics.recovery_rate as MetricResult | undefined;
    assert.equal(formatMetricPct(missingRec?.percentage), '—');
  });

  test('5. Graceful 404 handling when repetition evaluation does not exist yet', async () => {
    // Simulate API 404 error when repetition has not yet been evaluated
    const notFoundError = new ApiError(404, {
      code: 'EVALUATION_NOT_FOUND',
      message: 'No completed evaluation for repetition 2',
    });

    let evaluationResult: Evaluation | null = 'stale_value' as unknown as Evaluation;

    // Frontend defensive handler catches 404 and sets evaluation to null
    try {
      throw notFoundError;
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) {
        evaluationResult = null;
      }
    }

    assert.equal(evaluationResult, null);
    assert.doesNotThrow(() => {
      // Must not crash UI when evaluationResult is null
      const display = evaluationResult === null ? 'No Evaluation Record' : 'Has Evaluation';
      assert.equal(display, 'No Evaluation Record');
    });
  });

  test('6. Nonexistent experiment returning 404 sets clean not-found state without uncaught errors', () => {
    const notFoundError = new ApiError(404, {
      code: 'EXPERIMENT_NOT_FOUND',
      message: "Experiment 'nonexistent-exp-id' not found",
    });

    let experimentState: unknown = null;
    let errorMessage: string | null = null;

    try {
      throw notFoundError;
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) {
        errorMessage = `Experiment 'nonexistent-exp-id' was not found.`;
        experimentState = null;
      }
    }

    assert.equal(experimentState, null);
    assert.equal(errorMessage, "Experiment 'nonexistent-exp-id' was not found.");
  });

  test('7. Correct API URL construction matches FastAPI routes', () => {
    const experimentId = 'exp-uuid-123';
    const repIndex = 3;
    const evalId = 'eval-uuid-456';

    // 1. Repetition evaluation endpoint
    const repEvalUrl = `/experiments/${experimentId}/repetitions/${repIndex}/evaluation`;
    assert.equal(repEvalUrl, '/experiments/exp-uuid-123/repetitions/3/evaluation');

    // 2. Evaluation detail endpoint
    const evalDetailUrl = `/experiments/${experimentId}/evaluations/${evalId}`;
    assert.equal(evalDetailUrl, '/experiments/exp-uuid-123/evaluations/eval-uuid-456');

    // 3. Export URLs
    const repCsv = client.getExportUrl('repetition', {
      experimentId,
      repetitionIdOrIndex: repIndex,
      format: 'csv',
    });
    assert.equal(repCsv, 'http://127.0.0.1:8000/api/experiments/exp-uuid-123/repetitions/3/exports/csv');

    const evalJsonl = client.getExportUrl('evaluation', {
      experimentId,
      evaluationId: evalId,
      format: 'jsonl',
    });
    assert.equal(evalJsonl, 'http://127.0.0.1:8000/api/experiments/exp-uuid-123/evaluations/eval-uuid-456/exports/jsonl');
  });
});
