/**
 * Centralized HTTP client for the Management Backend.
 * All fetch calls go through here — no ad-hoc fetches in components.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1';

export interface MetaEnvelope {
  request_id?: string;
  [key: string]: unknown;
}

export interface PageInfo {
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface ListResponse<T> {
  data: T[];
  page?: PageInfo;
}

export interface ItemResponse<T> {
  data: T;
  meta: MetaEnvelope;
}

export interface ApiClientError extends Error {
  status: number;
  code: string;
  detail?: unknown;
  requestId?: string;
  commandId?: string;
}

export function isApiClientError(e: unknown): e is ApiClientError {
  return e instanceof Error && (e as ApiClientError).code !== undefined;
}

function makeApiError(
  status: number,
  code: string,
  message: string,
  detail?: unknown,
  requestId?: string,
  commandId?: string,
): ApiClientError {
  const err = new Error(message) as ApiClientError;
  err.name = 'ApiClientError';
  err.status = status;
  err.code = code;
  err.detail = detail;
  err.requestId = requestId;
  err.commandId = commandId;
  return err;
}

export function createIdempotencyKey(prefix = 'idemp'): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

export interface RequestOptions extends RequestInit {
  idempotencyKey?: string;
  retryCount?: number;
}

async function request<T>(path: string, options?: RequestOptions): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    ...((options?.headers as Record<string, string>) || {}),
  };

  if (options?.idempotencyKey) {
    headers['Idempotency-Key'] = options.idempotencyKey;
  }

  let response: Response | undefined;
  const maxRetries = options?.retryCount ?? 1;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      response = await fetch(url, {
        ...options,
        headers,
      });
      break;
    } catch (err) {
      if (attempt === maxRetries) {
        throw makeApiError(0, 'NETWORK_ERROR', `Network error: ${String(err)}`);
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
  }

  if (!response) {
    throw makeApiError(0, 'NETWORK_ERROR', 'Network error: No response received');
  }

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Request failed: ${response.status} ${response.statusText}`;
    let detail: unknown;
    let requestId: string | undefined;
    let commandId: string | undefined;

    try {
      const body = await response.json();
      if (body?.error) {
        if (body.error.code) code = body.error.code;
        if (body.error.message) message = body.error.message;
        if (body.error.details !== undefined) detail = body.error.details;
        if (body.error.request_id) requestId = body.error.request_id;
        if (body.error.command_id) commandId = body.error.command_id;
      } else if (body?.detail) {
        detail = body.detail;
        if (typeof body.detail === 'string') {
          message = body.detail;
        } else if (typeof body.detail === 'object' && body.detail !== null) {
          if (body.detail.code) code = body.detail.code;
          if (body.detail.message) message = body.detail.message;
        }
      }
    } catch {
      // ignore json parse error on error responses
    }
    throw makeApiError(response.status, code, message, detail, requestId, commandId);
  }

  // 204 No Content
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

async function requestItem<T>(path: string, options?: RequestOptions): Promise<T> {
  const envelope = await request<ItemResponse<T>>(path, options);
  if (!envelope || typeof envelope !== 'object' || !('data' in envelope) || !('meta' in envelope)) {
    throw makeApiError(0, 'INVALID_RESPONSE', 'Expected canonical {data, meta} response envelope.');
  }
  return envelope.data;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
  getItem: <T>(path: string, options?: RequestOptions) =>
    requestItem<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  postItem: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    requestItem<T>(path, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body: unknown, options?: RequestOptions) =>
    request<T>(path, {
      ...options,
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  patchItem: <T>(path: string, body: unknown, options?: RequestOptions) =>
    requestItem<T>(path, { ...options, method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
