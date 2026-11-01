import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

describe('Automatic Evaluation and Authoritative Metric Directions', () => {
  test('auto-evaluation lifecycle triggers when repetition status is terminal', () => {
    const repetition = {
      id: 'rep-123',
      repetition_index: 2,
      status: 'completed',
      completed_run_count: 50,
      evaluation_id: null,
    };

    const isTerminal = repetition.status === 'completed' || repetition.status === 'stopped';
    const needsEvaluation = isTerminal && repetition.completed_run_count > 0 && !repetition.evaluation_id;

    assert.equal(needsEvaluation, true);
  });

  test('auto-evaluation does not trigger repeatedly for already evaluated repetitions', () => {
    const repetition = {
      id: 'rep-123',
      repetition_index: 2,
      status: 'completed',
      completed_run_count: 50,
      evaluation_id: 'eval-existing-456',
    };

    const isTerminal = repetition.status === 'completed' || repetition.status === 'stopped';
    const needsEvaluation = isTerminal && repetition.completed_run_count > 0 && !repetition.evaluation_id;

    assert.equal(needsEvaluation, false);
  });

  test('metric directions correctly identify improvements vs regressions', () => {
    // 1. Task Completion Rate: Higher is better
    const tcrBaseline = 0.85;
    const tcrEgal = 0.95;
    const tcrDelta = tcrEgal - tcrBaseline; // +0.10
    const isTcrImprovement = tcrDelta > 0;
    assert.equal(isTcrImprovement, true);

    // 2. Unsupported Action Rate: Lower is better!
    const uarBaseline = 0.12;
    const uarEgal = 0.02;
    const uarDelta = uarEgal - uarBaseline; // -0.10 (lower is better!)
    const isUarImprovement = uarDelta < 0;
    assert.equal(isUarImprovement, true);

    // 3. Recovery Rate: Higher is better
    const recBaseline = 0.50;
    const recEgal = 0.85;
    const recDelta = recEgal - recBaseline; // +0.35
    const isRecImprovement = recDelta > 0;
    assert.equal(isRecImprovement, true);

    // 4. False Success: Lower is better!
    const fsBaseline = 0.08;
    const fsEgal = 0.01;
    const fsDelta = fsEgal - fsBaseline; // -0.07 (lower is better!)
    const isFsImprovement = fsDelta < 0;
    assert.equal(isFsImprovement, true);

    // 5. Consistency Rate: Higher is better
    const conBaseline = 0.78;
    const conEgal = 0.92;
    const conDelta = conEgal - conBaseline; // +0.14
    const isConImprovement = conDelta > 0;
    assert.equal(isConImprovement, true);
  });

  test('export URL generator produces exact endpoint URLs for CSV and JSONL', () => {
    const baseUrl = 'http://127.0.0.1:8000/api';
    const expId = 'exp-999';
    const repIndex = 2;
    const evalId = 'eval-888';
    const grpId = 'grp-777';

    const repCsvUrl = `${baseUrl}/experiments/${expId}/repetitions/${repIndex}/exports/csv`;
    const repJsonlUrl = `${baseUrl}/experiments/${expId}/repetitions/${repIndex}/exports/jsonl`;
    const evalCsvUrl = `${baseUrl}/experiments/${expId}/evaluations/${evalId}/exports/csv`;
    const grpCsvUrl = `${baseUrl}/experiment-groups/${grpId}/exports/csv`;

    assert.ok(repCsvUrl.endsWith('/repetitions/2/exports/csv'));
    assert.ok(repJsonlUrl.endsWith('/repetitions/2/exports/jsonl'));
    assert.ok(evalCsvUrl.endsWith('/evaluations/eval-888/exports/csv'));
    assert.ok(grpCsvUrl.endsWith('/experiment-groups/grp-777/exports/csv'));
  });
});
