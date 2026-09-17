/**
 * Idempotency Key utilities for Management Backend mutations.
 *
 * Required by API_contract.md for POST / PATCH / DELETE business workflows.
 */

/**
 * Generate a standard RFC4122 UUID v4 string.
 */
export const generateIdempotencyKey = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Cryptographically robust fallback
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant RFC4122
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
  }
  // Standard math fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

export const MUTATION_METHODS = new Set(['POST', 'PATCH', 'DELETE', 'PUT']);

export const isMutationMethod = (method: string): boolean => {
  return MUTATION_METHODS.has(method.toUpperCase());
};

/**
 * Prepare request headers with an Idempotency-Key for mutation methods.
 *
 * Rules:
 * - If method is POST, PATCH, DELETE and no Idempotency-Key exists: inject new UUID (or explicit key).
 * - If method is GET, HEAD, OPTIONS: never inject Idempotency-Key.
 * - Never overwrite an explicit Idempotency-Key provided in headers.
 */
export const withIdempotencyHeader = (
  headers: HeadersInit | undefined,
  method: string,
  explicitIdempotencyKey?: string
): Record<string, string> => {
  const result: Record<string, string> = {};

  if (headers) {
    if (headers instanceof Headers) {
      headers.forEach((val, key) => {
        result[key] = val;
      });
    } else if (Array.isArray(headers)) {
      headers.forEach(([key, val]) => {
        result[key] = val;
      });
    } else {
      Object.assign(result, headers);
    }
  }

  const upperMethod = method.toUpperCase();
  if (isMutationMethod(upperMethod)) {
    const existingKey = Object.keys(result).find(
      k => k.toLowerCase() === 'idempotency-key'
    );
    if (!existingKey) {
      result['Idempotency-Key'] = explicitIdempotencyKey || generateIdempotencyKey();
    }
  }

  return result;
};
