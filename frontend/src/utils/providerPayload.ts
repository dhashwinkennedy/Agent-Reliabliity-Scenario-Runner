import type { ProviderCreateRequest } from '../types';

export interface BuildProviderPayloadInput {
  id?: string;
  name: string;
  provider_type: string;
  api_key?: string;
  base_url: string;
  default_model: string;
  organization?: string;
}

/**
 * Builds and normalizes a ProviderCreateRequest payload for the backend API.
 * Ensures provider_type is strictly 'openai_compatible' according to backend Pydantic contract.
 */
export function buildProviderCreatePayload(input: BuildProviderPayloadInput): ProviderCreateRequest {
  const rawType = (input.provider_type || '').trim();
  let normalizedType = rawType;

  // Strict normalization: any variant of openai_compatible, openai, or custom normalizes to 'openai_compatible'
  if (
    rawType.toLowerCase() === 'openai_compatible' ||
    rawType.toLowerCase() === 'openai-compatible' ||
    rawType.toLowerCase() === 'openai' ||
    rawType.toLowerCase() === 'custom'
  ) {
    normalizedType = 'openai_compatible';
  } else if (rawType) {
    normalizedType = rawType.toLowerCase().replace(/-/g, '_');
  } else {
    normalizedType = 'openai_compatible';
  }

  // Sanitize provided ID or generate from name
  const rawId = (input.id && input.id.trim()) ? input.id.trim() : (input.name || 'provider').trim();
  const sanitizedId = rawId
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/^-+|-+$/g, '');

  const payload: ProviderCreateRequest = {
    id: sanitizedId || 'provider-custom',
    name: input.name.trim(),
    provider_type: normalizedType,
    base_url: input.base_url.trim(),
    default_model: input.default_model.trim(),
  };

  if (input.api_key && input.api_key.trim()) {
    payload.api_key = input.api_key.trim();
  }

  if (input.organization && input.organization.trim()) {
    payload.organization = input.organization.trim();
  }

  return payload;
}
