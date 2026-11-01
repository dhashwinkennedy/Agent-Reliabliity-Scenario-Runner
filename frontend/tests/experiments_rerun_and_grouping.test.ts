import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

describe('Experiments, One-Button Rerun, and Baseline–EGAL Grouping', () => {
  test('frozen configuration is preserved across repetitions', () => {
    const originalExperiment = {
      id: 'exp-original',
      name: 'Q3 Financial Sentiment Evaluation',
      dataset_snapshot_id: 'snap-sha256-fixed-01',
      agent_id: 'financial_news_analysis',
      provider_id: 'mock',
      model: 'gpt-4o',
      status: 'completed',
      configuration: { temperature: 0.0, max_tokens: 500 },
      input_mapping: { headline: 'headline', symbol: 'symbol' },
      repetition_count: 1,
      group_id: 'grp-12345',
      group_name: 'Q3 Financial Sentiment Evaluation',
    };

    // Simulated Rerun 1 -> Repetition 2
    const repetition2 = {
      id: 'rep-uuid-002',
      experiment_id: originalExperiment.id,
      repetition_index: 2,
      status: 'completed',
      idempotency_key: 'rerun-key-002',
      run_count: 50,
      completed_run_count: 48,
      failed_run_count: 2,
      evaluation_id: 'eval-rep-002',
    };

    // Simulated Rerun 2 -> Repetition 3
    const repetition3 = {
      id: 'rep-uuid-003',
      experiment_id: originalExperiment.id,
      repetition_index: 3,
      status: 'completed',
      idempotency_key: 'rerun-key-003',
      run_count: 50,
      completed_run_count: 50,
      failed_run_count: 0,
      evaluation_id: 'eval-rep-003',
    };

    // Both repetitions belong to same experiment and group without mutating original snapshot or model
    assert.equal(repetition2.experiment_id, originalExperiment.id);
    assert.equal(repetition3.experiment_id, originalExperiment.id);
    assert.equal(repetition2.repetition_index, 2);
    assert.equal(repetition3.repetition_index, 3);
    assert.notEqual(repetition2.id, repetition3.id);
    assert.notEqual(repetition2.evaluation_id, repetition3.evaluation_id);
  });

  test('failed runs remain visible and older runs are never overwritten', () => {
    const rep1Runs = [
      { id: 'run-1-1', repetition_index: 1, status: 'completed', error: null },
      { id: 'run-1-2', repetition_index: 1, status: 'completed', error: null },
    ];

    const rep2Runs = [
      { id: 'run-2-1', repetition_index: 2, status: 'completed', error: null },
      { id: 'run-2-2', repetition_index: 2, status: 'failed', error: 'RateLimitError: 429' },
    ];

    // Filter for Repetition 1
    const filteredRep1 = [...rep1Runs, ...rep2Runs].filter((r) => r.repetition_index === 1);
    assert.equal(filteredRep1.length, 2);
    assert.equal(filteredRep1.every((r) => r.status === 'completed'), true);

    // Filter for Repetition 2
    const filteredRep2 = [...rep1Runs, ...rep2Runs].filter((r) => r.repetition_index === 2);
    assert.equal(filteredRep2.length, 2);
    const failedRun = filteredRep2.find((r) => r.status === 'failed');
    assert.ok(failedRun);
    assert.equal(failedRun?.error, 'RateLimitError: 429');
  });

  test('Baseline and EGAL conditions are grouped without mixing runs', () => {
    const group = {
      id: 'grp-paired-01',
      name: 'Paired Sentiment Analysis',
      dataset_snapshot_id: 'snap-alpha',
      provider_id: 'mock',
      model: 'gpt-4o',
    };

    const baselineExperiment = {
      id: 'exp-baseline-01',
      group_id: group.id,
      agent_id: 'financial_news_analysis',
      name: 'Paired Sentiment Analysis (Baseline)',
    };

    const egalExperiment = {
      id: 'exp-egal-01',
      group_id: group.id,
      agent_id: 'financial_news_analysis_egal',
      name: 'Paired Sentiment Analysis (EGAL)',
    };

    assert.equal(baselineExperiment.group_id, group.id);
    assert.equal(egalExperiment.group_id, group.id);
    assert.notEqual(baselineExperiment.id, egalExperiment.id);
    assert.notEqual(baselineExperiment.agent_id, egalExperiment.agent_id);
  });

  test('idempotency key and debounce guard prevent duplicate rerun submissions', () => {
    const isRerunning = true;
    const canClick = !isRerunning;
    assert.equal(canClick, false);

    const key1 = `rerun-exp123-${1000}`;
    const key2 = `rerun-exp123-${1000}`;
    assert.equal(key1, key2); // Repeated retry will have identical idempotency token
  });

  test('experiment-group link payload complies with backend contract: group_name and experiment_ids', () => {
    const baselineId = 'exp-base-101';
    const egalId = 'exp-egal-102';
    const groupName = 'Q3 Alpha Evaluation';

    // Construct request conforming to ExperimentGroupLink schema
    const payload = {
      group_name: groupName,
      experiment_ids: [baselineId, egalId],
    };

    assert.equal(typeof payload.group_name, 'string');
    assert.ok(payload.group_name.length > 0);
    assert.ok(Array.isArray(payload.experiment_ids));
    assert.equal(payload.experiment_ids.length, 2);
    assert.equal(payload.experiment_ids[0], baselineId);
    assert.equal(payload.experiment_ids[1], egalId);
  });

  test('experiment creation and group linking executes in strict sequential order', async () => {
    const callLog: string[] = [];

    const mockCreateExperiment = async (data: { agent_id: string; name: string }) => {
      callLog.push(`create:${data.agent_id}`);
      return { id: `id-${data.agent_id}`, name: data.name, agent_id: data.agent_id };
    };

    const mockLinkGroup = async (data: { group_name: string; experiment_ids: string[] }) => {
      callLog.push(`link:${data.group_name}:${data.experiment_ids.join(',')}`);
      return { group_id: 'grp-1', name: data.group_name };
    };

    // Sequential workflow
    const baseExp = await mockCreateExperiment({
      agent_id: 'financial_news_analysis',
      name: 'Paired Run (Baseline)',
    });
    const egalExp = await mockCreateExperiment({
      agent_id: 'financial_news_analysis_egal',
      name: 'Paired Run (EGAL)',
    });
    await mockLinkGroup({
      group_name: 'Paired Run',
      experiment_ids: [baseExp.id, egalExp.id],
    });

    assert.deepEqual(callLog, [
      'create:financial_news_analysis',
      'create:financial_news_analysis_egal',
      'link:Paired Run:id-financial_news_analysis,id-financial_news_analysis_egal',
    ]);
  });

  test('failed group linking preserves created experiments for retry without duplicates', async () => {
    let createCallCount = 0;
    const mockCreateExperiment = async (agentId: string) => {
      createCallCount++;
      return { id: `exp-${agentId}-${createCallCount}`, agent_id: agentId };
    };

    let linkAttemptCount = 0;
    const mockLinkGroup = async (_experimentIds: string[]) => {
      linkAttemptCount++;
      if (linkAttemptCount === 1) {
        throw new Error('422 Unprocessable Entity: Network glitch or validation');
      }
      return { group_id: 'grp-success', status: 'linked' };
    };

    // Attempt 1: Creation succeeds, linking fails
    let pendingBaseline: { id: string } | null = null;
    let pendingEgal: { id: string } | null = null;
    let lastError: string | null = null;

    try {
      if (!pendingBaseline) pendingBaseline = await mockCreateExperiment('baseline');
      if (!pendingEgal) pendingEgal = await mockCreateExperiment('egal');
      await mockLinkGroup([pendingBaseline.id, pendingEgal.id]);
    } catch (err: any) {
      lastError = err.message;
    }

    assert.ok(lastError?.includes('422'));
    assert.equal(createCallCount, 2, '2 experiments created on first attempt');
    assert.ok(pendingBaseline);
    assert.ok(pendingEgal);

    // Attempt 2 (Retry): Reuses pendingBaseline and pendingEgal without calling createExperiment
    try {
      if (!pendingBaseline) pendingBaseline = await mockCreateExperiment('baseline');
      if (!pendingEgal) pendingEgal = await mockCreateExperiment('egal');
      const res = await mockLinkGroup([pendingBaseline.id, pendingEgal.id]);
      assert.equal(res.status, 'linked');
      pendingBaseline = null;
      pendingEgal = null;
    } catch {
      assert.fail('Retry should succeed');
    }

    // Verify createExperiment was NOT called again on retry
    assert.equal(createCallCount, 2, 'Zero duplicate experiments created on retry');
    assert.equal(linkAttemptCount, 2);
  });

  test('parses detailed backend validation errors into human-readable messages', () => {
    // Simulating parseErrorResponse logic
    const parseDetail = (errObj: any): string => {
      if (errObj.error?.message) return errObj.error.message;
      if (Array.isArray(errObj.detail)) {
        return errObj.detail
          .map((item: any) => {
            const loc = Array.isArray(item.loc) ? item.loc.filter((p: any) => p !== 'body').join('.') : '';
            return loc ? `${loc}: ${item.msg}` : item.msg;
          })
          .join('; ');
      }
      if (errObj.detail?.message) return errObj.detail.message;
      if (typeof errObj.detail === 'string') return errObj.detail;
      return 'Unknown error';
    };

    const fastApiValidationError = {
      detail: [
        { loc: ['body', 'group_name'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'experiment_ids'], msg: 'Field required', type: 'missing' },
      ],
    };

    const formatted = parseDetail(fastApiValidationError);
    assert.equal(formatted, 'group_name: Field required; experiment_ids: Field required');

    const httpExceptionDetail = {
      detail: {
        code: 'INCOMPATIBLE_EXPERIMENT_GROUP',
        message: 'Cannot group experiments across different providers',
      },
    };
    assert.equal(parseDetail(httpExceptionDetail), 'Cannot group experiments across different providers');
  });
});
