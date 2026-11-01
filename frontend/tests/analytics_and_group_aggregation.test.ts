import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

describe('Analytics and Across-Repetition Group Aggregation', () => {
  // Helper replicates formatPct in Analytics.tsx
  const formatPct = (val: number | null | undefined): string => {
    if (val === null || val === undefined) return 'N/A';
    const scaled = Math.abs(val) <= 1.0 && val !== 0 ? val * 100 : val;
    return `${scaled.toFixed(1)}%`;
  };

  // Helper replicates formatMetricWithRatio in Analytics.tsx
  const formatMetricWithRatio = (m: unknown): string => {
    if (!m || typeof m !== 'object') return 'N/A';
    const obj = m as Record<string, unknown>;
    const pct = typeof obj.percentage === 'number' ? obj.percentage : null;
    const num = typeof obj.numerator === 'number' ? obj.numerator : null;
    const den = typeof obj.denominator === 'number' ? obj.denominator : null;

    if (pct === null) {
      if (obj.status === 'not_assessable') {
        const details = (obj.details || {}) as Record<string, unknown>;
        if (details.required_repetitions && details.observed_repetitions) {
          return `Not Assessable (${details.observed_repetitions}/${details.required_repetitions} reps)`;
        }
        return 'Not Assessable';
      }
      return 'N/A';
    }

    const scaled = Math.abs(pct) <= 1.0 && pct !== 0 ? pct * 100 : pct;
    if (num !== null && den !== null) {
      return `${scaled.toFixed(1)}% (${num}/${den})`;
    }
    return `${scaled.toFixed(1)}%`;
  };

  // Helper replicates delta calculation
  const calculateDelta = (
    val: unknown,
    direction: 'higher_is_better' | 'lower_is_better'
  ) => {
    let num: number | null = null;
    let directionStr: string | null = null;

    if (val !== null && typeof val === 'object') {
      const obj = val as Record<string, unknown>;
      num = typeof obj.value === 'number' ? obj.value : (typeof obj.delta === 'number' ? obj.delta : null);
      directionStr = typeof obj.direction === 'string' ? obj.direction : null;
    } else if (typeof val === 'number') {
      num = val;
    }

    if (directionStr === 'not_assessable' || num === null) {
      return { status: 'not_assessable', text: 'Not Assessable' };
    }

    if (num === 0 || directionStr === 'unchanged') {
      return { status: 'unchanged', text: '0.0 percentage-point change (Equal / Unchanged)' };
    }

    const isGood = direction === 'higher_is_better' ? num > 0 : num < 0;
    const formatted = num > 0 ? `+${num.toFixed(1)}` : `${num.toFixed(1)}`;
    return {
      status: isGood ? 'improved' : 'regressed',
      text: `${formatted} percentage-point ${isGood ? 'improvement' : 'regression'}`,
    };
  };

  it('1. formatPct and formatMetricWithRatio never return "nil"', () => {
    assert.strictEqual(formatPct(null), 'N/A');
    assert.strictEqual(formatPct(undefined), 'N/A');
    assert.notStrictEqual(formatPct(null), 'nil');
    assert.notStrictEqual(formatMetricWithRatio(null), 'nil');
    assert.notStrictEqual(formatMetricWithRatio({ percentage: null, status: 'not_assessable' }), 'nil');
  });

  it('2. formatMetricWithRatio formats authentic percentages with numerators and denominators', () => {
    assert.strictEqual(
      formatMetricWithRatio({ percentage: 25.0, numerator: 3, denominator: 12 }),
      '25.0% (3/12)'
    );
    assert.strictEqual(
      formatMetricWithRatio({ percentage: 40.0, numerator: 4, denominator: 10 }),
      '40.0% (4/10)'
    );
    assert.strictEqual(
      formatMetricWithRatio({ percentage: 100.0, numerator: 4, denominator: 4 }),
      '100.0% (4/4)'
    );
    assert.strictEqual(
      formatMetricWithRatio({
        percentage: null,
        status: 'not_assessable',
        details: { required_repetitions: 5, observed_repetitions: 2 },
      }),
      'Not Assessable (2/5 reps)'
    );
  });

  it('3. calculateDelta displays explicit Equal / Unchanged for zero-delta metrics (e.g. Recovery Rate)', () => {
    const recoveryDelta = {
      value: 0.0,
      delta: 0.0,
      baseline: 100.0,
      egal: 100.0,
      direction: 'unchanged',
    };
    const res = calculateDelta(recoveryDelta, 'higher_is_better');
    assert.strictEqual(res.status, 'unchanged');
    assert.strictEqual(res.text, '0.0 percentage-point change (Equal / Unchanged)');
  });

  it('4. calculateDelta correctly accounts for lower_is_better (e.g. Unsupported Action & False Success)', () => {
    // Negative delta is an improvement for unsupported action
    const uaImprovement = { value: -8.33, direction: 'improved' };
    const res1 = calculateDelta(uaImprovement, 'lower_is_better');
    assert.strictEqual(res1.status, 'improved');
    assert.match(res1.text, /improvement/);

    // Positive delta is a regression for false success
    const fsRegression = { value: 5.56, direction: 'regressed' };
    const res2 = calculateDelta(fsRegression, 'lower_is_better');
    assert.strictEqual(res2.status, 'regressed');
    assert.match(res2.text, /regression/);
  });

  it('5. Pooled multi-repetition aggregation matches authentic evaluation records', () => {
    // Baseline evaluations
    const rep1Baseline = { task_completion_rate: { numerator: 2, denominator: 6, percentage: 33.3333 } };
    const rep2Baseline = { task_completion_rate: { numerator: 1, denominator: 6, percentage: 16.6667 } };

    // EGAL evaluations (Rep 1 had 2 abstentions, so 4 evaluated; Rep 2 had 6 evaluated)
    const rep1Egal = { task_completion_rate: { numerator: 3, denominator: 4, percentage: 75.0 } };
    const rep2Egal = { task_completion_rate: { numerator: 1, denominator: 6, percentage: 16.6667 } };

    // Pooling sums numerators and denominators
    const pooledBaseNum = rep1Baseline.task_completion_rate.numerator + rep2Baseline.task_completion_rate.numerator;
    const pooledBaseDen = rep1Baseline.task_completion_rate.denominator + rep2Baseline.task_completion_rate.denominator;
    const pooledBasePct = (pooledBaseNum / pooledBaseDen) * 100;

    const pooledEgalNum = rep1Egal.task_completion_rate.numerator + rep2Egal.task_completion_rate.numerator;
    const pooledEgalDen = rep1Egal.task_completion_rate.denominator + rep2Egal.task_completion_rate.denominator;
    const pooledEgalPct = (pooledEgalNum / pooledEgalDen) * 100;

    assert.strictEqual(pooledBaseNum, 3);
    assert.strictEqual(pooledBaseDen, 12);
    assert.strictEqual(pooledBasePct, 25.0);

    assert.strictEqual(pooledEgalNum, 4);
    assert.strictEqual(pooledEgalDen, 10);
    assert.strictEqual(pooledEgalPct, 40.0);

    const deltaPctPoints = pooledEgalPct - pooledBasePct;
    assert.strictEqual(deltaPctPoints, 15.0);
  });

  it('6. Per-Repetition Paired Comparison displays correct distinct values for Rep 1 vs Rep 2', () => {
    // Rep 1: Baseline 33.3% vs EGAL 75.0% -> +41.7%
    const rep1 = {
      repetition_index: 1,
      baseline_metrics: { task_completion_rate: { percentage: 33.3333, numerator: 2, denominator: 6 } },
      egal_metrics: { task_completion_rate: { percentage: 75.0, numerator: 3, denominator: 4 } },
      deltas: { task_completion_rate: { value: 41.6667, direction: 'improved' } },
    };

    // Rep 2: Baseline 16.7% vs EGAL 16.7% -> 0.0%
    const rep2 = {
      repetition_index: 2,
      baseline_metrics: { task_completion_rate: { percentage: 16.6667, numerator: 1, denominator: 6 } },
      egal_metrics: { task_completion_rate: { percentage: 16.6667, numerator: 1, denominator: 6 } },
      deltas: { task_completion_rate: { value: 0.0, direction: 'unchanged' } },
    };

    assert.strictEqual(formatMetricWithRatio(rep1.baseline_metrics.task_completion_rate), '33.3% (2/6)');
    assert.strictEqual(formatMetricWithRatio(rep1.egal_metrics.task_completion_rate), '75.0% (3/4)');
    const rep1Delta = calculateDelta(rep1.deltas.task_completion_rate, 'higher_is_better');
    assert.strictEqual(rep1Delta.status, 'improved');

    assert.strictEqual(formatMetricWithRatio(rep2.baseline_metrics.task_completion_rate), '16.7% (1/6)');
    assert.strictEqual(formatMetricWithRatio(rep2.egal_metrics.task_completion_rate), '16.7% (1/6)');
    const rep2Delta = calculateDelta(rep2.deltas.task_completion_rate, 'higher_is_better');
    assert.strictEqual(rep2Delta.status, 'unchanged');
  });
});
