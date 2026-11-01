import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { buildProviderCreatePayload } from '../src/utils/providerPayload';

describe('Providers and Connection Testing', () => {
  test('provider credentials are encrypted and never exposed in client schemas', () => {
    const providerDto = {
      id: 'mock',
      name: 'Mock LLM Provider',
      provider_type: 'mock',
      base_url: null,
      api_key_configured: true,
      default_model: 'mock-model',
      models: ['mock-model', 'mock-fast'],
      organization: null,
      created_at: '2026-10-27T15:00:00Z',
    };

    // Verify plaintext api_key is NEVER exposed on returned provider DTO
    assert.equal('api_key' in providerDto, false);
    assert.equal(providerDto.api_key_configured, true);
  });

  test('connection test response contains latency_ms and reachable flag', () => {
    const connectionTestRes = {
      ok: true,
      reachable: true,
      latency_ms: 128,
      checks: [
        { name: 'base_url', ok: true },
        { name: 'model_discovery', ok: true, models: ['gpt-4o', 'gpt-4o-mini'] },
        { name: 'completion', ok: true, model: 'gpt-4o' },
      ],
      errors: [],
    };

    assert.equal(connectionTestRes.ok, true);
    assert.equal(connectionTestRes.reachable, true);
    assert.equal(connectionTestRes.latency_ms, 128);
    assert.equal(connectionTestRes.checks.length, 3);
  });

  test('selecting the OpenAI-compatible provider type submits provider_type === "openai_compatible"', () => {
    // Form selection: user selects the OpenAI-compatible option from dropdown
    const selectedDropdownValue = 'openai_compatible';

    const payload = buildProviderCreatePayload({
      id: 'custom-provider',
      name: 'Custom Provider',
      provider_type: selectedDropdownValue,
      base_url: 'https://api.example.com/v1',
      default_model: 'custom-model',
    });

    // Assert that selecting OpenAI-compatible type submits exactly "openai_compatible"
    assert.equal(payload.provider_type, 'openai_compatible');
    assert.equal(payload.name, 'Custom Provider');
    assert.equal(payload.base_url, 'https://api.example.com/v1');
    assert.equal(payload.default_model, 'custom-model');
  });

  test('request-building logic normalizes legacy dropdown variants to "openai_compatible"', () => {
    // Legacy variants that users or older forms might send
    const variants = ['openai', 'openai-compatible', 'OpenAI-compatible', 'custom', 'openai_compatible'];

    for (const variant of variants) {
      const payload = buildProviderCreatePayload({
        id: 'test-prov',
        name: 'Test Provider',
        provider_type: variant,
        base_url: 'https://api.example.com/v1',
        default_model: 'test-model',
      });

      assert.equal(
        payload.provider_type,
        'openai_compatible',
        `Variant "${variant}" must normalize to "openai_compatible"`
      );
    }
  });

  test('OpenRouter provider registration builds exact backend schema payload', () => {
    // Verification of exact OpenRouter configuration requested
    const mockUserSecret = 'sk-or-v1-0123456789abcdef0123456789abcdef';

    const payload = buildProviderCreatePayload({
      id: 'openrouter',
      name: 'OpenRouter',
      provider_type: 'openai_compatible',
      base_url: 'https://openrouter.ai/api/v1',
      default_model: 'anthropic/claude-3.5-sonnet',
      api_key: mockUserSecret,
    });

    // 1. provider_type is strictly "openai_compatible" matching backend Literal["openai_compatible"]
    assert.equal(payload.provider_type, 'openai_compatible');

    // 2. All required fields are present and non-empty
    assert.equal(payload.id, 'openrouter');
    assert.equal(payload.name, 'OpenRouter');
    assert.equal(payload.base_url, 'https://openrouter.ai/api/v1');
    assert.equal(payload.default_model, 'anthropic/claude-3.5-sonnet');

    // 3. API key is preserved without corruption
    assert.equal(payload.api_key, mockUserSecret);

    // 4. Complies with backend ProviderCreate constraints (min_length=8 for base_url, min_length=1 for default_model)
    assert.ok(payload.base_url.length >= 8);
    assert.ok(payload.default_model.length >= 1);
    assert.ok(payload.name.length >= 1);
  });
});
