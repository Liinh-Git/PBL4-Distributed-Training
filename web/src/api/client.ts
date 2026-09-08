/**
 * Centralized HTTP client for the Management Backend.
 * All fetch calls go through here — no ad-hoc fetches in components.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1';

export interface ApiClientError extends Error {
  status: number
  code: string
  detail?: unknown
}

export function isApiClientError(e: unknown): e is ApiClientError {
  return e instanceof Error && (e as ApiClientError).code !== undefined
}

function makeApiError(status: number, code: string, message: string, detail?: unknown): ApiClientError {
  const err = new Error(message) as ApiClientError
  err.name = 'ApiClientError'
  err.status = status
  err.code = code
  err.detail = detail
  return err
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      ...init,
    });
  } catch (err) {
    throw makeApiError(0, 'NETWORK_ERROR', `Network error: ${String(err)}`);
  }

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `Request failed: ${response.status} ${response.statusText}`;
    let detail: unknown;
    try {
      const body = await response.json();
      if (body?.error?.code) code = body.error.code;
      if (body?.error?.message) message = body.error.message;
      if (body?.detail) {
        detail = body.detail;
        if (typeof body.detail === 'string') message = body.detail;
      }
    } catch {
      // ignore JSON parse errors on error bodies
    }
    throw makeApiError(response.status, code, message, detail);
  }

  // 204 No Content
  if (response.status === 204) return undefined as T;

  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
