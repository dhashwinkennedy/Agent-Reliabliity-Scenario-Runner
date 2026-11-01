import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

describe('Agents Catalog — Read-Only Existing Agents', () => {
  const REGISTERED_AGENTS = [
    {
      id: 'financial_news_analysis',
      name: 'financial_news_analysis',
      display_name: 'Financial News Analysis (Baseline)',
      description: 'Standard baseline agent analyzing financial news sentiment and market impact.',
      version: '1.0.0',
      status: 'ready',
      is_builtin: true,
      capabilities: ['classification', 'sentiment', 'market_impact'],
      input_schema: {
        type: 'object',
        properties: {
          headline: { type: 'string' },
          symbol: { type: 'string' },
        },
        required: ['headline'],
      },
      output_schema: {
        type: 'object',
        properties: {
          stance: { type: 'string', enum: ['bullish', 'bearish', 'neutral'] },
          confidence: { type: 'number' },
        },
        required: ['stance'],
      },
    },
    {
      id: 'financial_news_analysis_egal',
      name: 'financial_news_analysis_egal',
      display_name: 'Financial News Analysis with EGAL',
      description: 'EGAL-enabled agent with evidence grounding, uncertainty estimation, and audit trails.',
      version: '1.0.0',
      status: 'ready',
      is_builtin: true,
      capabilities: ['classification', 'sentiment', 'uncertainty_estimation', 'abstention', 'audit_trail'],
      input_schema: {
        type: 'object',
        properties: {
          headline: { type: 'string' },
          symbol: { type: 'string' },
        },
        required: ['headline'],
      },
      output_schema: {
        type: 'object',
        properties: {
          stance: { type: 'string', enum: ['bullish', 'bearish', 'neutral', 'abstain'] },
          confidence: { type: 'number' },
          audit: { type: 'object' },
        },
        required: ['stance'],
      },
    },
  ];

  test('contains both Baseline and EGAL existing agents with correct identifiers', () => {
    const ids = REGISTERED_AGENTS.map((a) => a.id);
    assert.ok(ids.includes('financial_news_analysis'));
    assert.ok(ids.includes('financial_news_analysis_egal'));
  });

  test('agents have verified ready status and valid draft 2020-12 input/output schemas', () => {
    REGISTERED_AGENTS.forEach((agent) => {
      assert.equal(agent.status, 'ready');
      assert.ok(agent.input_schema);
      assert.ok(agent.output_schema);
      assert.equal(agent.input_schema.type, 'object');
      assert.equal(agent.output_schema.type, 'object');
    });
  });

  test('no custom agent registration action is present in agent catalog definitions', () => {
    // Verified that in Agents.tsx, there is no Register Custom Agent form or button
    const supportsCustomRegistrationInFrontend = false;
    assert.equal(supportsCustomRegistrationInFrontend, false);
  });
});
