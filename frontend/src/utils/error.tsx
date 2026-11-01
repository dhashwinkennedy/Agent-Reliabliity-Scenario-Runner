// Research Arena - Structured Error Formatting & Parsing Utilities
import React from 'react';

export interface FormattedError {
  code?: string;
  message: string;
  details?: unknown;
}

/**
 * Parses any error representation into a structured FormattedError.
 * Safely extracts human-readable message and optional error code.
 * Guaranteed to never return an object directly for React rendering.
 */
export function parseError(err: unknown): FormattedError {
  if (!err) {
    return { message: '' };
  }

  // 1. Plain string
  if (typeof err === 'string') {
    // Check if the string is JSON-encoded object like '{"code": "...", "message": "..."}'
    const trimmed = err.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsedJson = JSON.parse(trimmed);
        if (parsedJson && typeof parsedJson === 'object') {
          return parseError(parsedJson);
        }
      } catch {
        // Not valid JSON, keep as string
      }
    }
    return { message: err };
  }

  // 2. Error or ApiError instance
  if (err instanceof Error) {
    const code = 'code' in err && typeof (err as { code: unknown }).code === 'string'
      ? (err as { code: string }).code
      : undefined;
    const details = 'details' in err ? (err as { details: unknown }).details : undefined;
    return {
      code,
      message: err.message || 'An error occurred',
      details,
    };
  }

  // 3. Object with keys {code, message} or FastAPI detail
  if (typeof err === 'object') {
    const obj = err as Record<string, unknown>;

    // Nested error object: { error: { code, message } }
    if (obj.error && typeof obj.error === 'object') {
      return parseError(obj.error);
    }

    const code = typeof obj.code === 'string'
      ? obj.code
      : typeof obj.error_code === 'string'
      ? obj.error_code
      : undefined;

    let message = '';
    if (typeof obj.message === 'string') {
      message = obj.message;
    } else if (typeof obj.msg === 'string') {
      message = obj.msg;
    } else if (typeof obj.detail === 'string') {
      message = obj.detail;
    } else if (typeof obj.error === 'string') {
      message = obj.error;
    } else if (Array.isArray(obj.detail)) {
      message = obj.detail
        .map((d: unknown) => {
          if (d && typeof d === 'object') {
            const item = d as Record<string, unknown>;
            const loc = Array.isArray(item.loc) ? item.loc.filter((p) => p !== 'body').join('.') : '';
            const msg = typeof item.msg === 'string' ? item.msg : 'Invalid input';
            return loc ? `${loc}: ${msg}` : msg;
          }
          return String(d);
        })
        .join('; ');
    } else if (code) {
      message = code;
    } else {
      try {
        message = JSON.stringify(err);
      } catch {
        message = 'An unknown error occurred';
      }
    }

    return {
      code,
      message,
      details: obj.details,
    };
  }

  return { message: String(err) };
}

/**
 * Returns a human-readable error message string.
 */
export function formatErrorMessage(err: unknown): string {
  return parseError(err).message;
}

/**
 * Returns the error code if present.
 */
export function formatErrorCode(err: unknown): string | undefined {
  return parseError(err).code;
}

/**
 * Evaluates whether an agent output represents a domain abstention (e.g. EGAL financial abstention),
 * distinguishing it from a technical run failure.
 */
export function isAbstention(output: unknown): { isAbstain: boolean; reason?: string } {
  if (!output || typeof output !== 'object') {
    return { isAbstain: false };
  }

  const obj = output as Record<string, unknown>;

  // Check recommendation field
  const rec = String(
    obj.recommendation ||
    obj.financial_recommendation ||
    obj.action ||
    ''
  ).toUpperCase();

  const isAbstain = rec === 'ABSTAIN' || rec === 'HOLD_ABSTAIN' || obj.is_abstention === true;
  const reason = typeof obj.abstention_reason === 'string'
    ? obj.abstention_reason
    : typeof obj.reason === 'string' && isAbstain
    ? obj.reason
    : undefined;

  return { isAbstain, reason };
}

interface ErrorTextProps {
  error: unknown;
  className?: string;
  showCode?: boolean;
}

/**
 * React Component to safely render error text with an optional code label.
 * NEVER crashes React by ensuring no raw objects are passed as children.
 */
export const ErrorText: React.FC<ErrorTextProps> = ({
  error,
  className = '',
  showCode = true,
}) => {
  if (!error) return null;

  const parsed = parseError(error);
  if (!parsed.message && !parsed.code) return null;

  return (
    <span className={`inline-flex items-center gap-1.5 flex-wrap ${className}`}>
      {showCode && parsed.code && (
        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-rose-950/80 border border-rose-800/80 text-rose-300 shrink-0">
          {parsed.code}
        </span>
      )}
      <span className="break-words">{parsed.message || parsed.code}</span>
    </span>
  );
};

export default ErrorText;
