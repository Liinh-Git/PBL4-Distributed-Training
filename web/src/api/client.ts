/**
 * Core HTTP API Client
 *
 * Provides a robust, type-safe HTTP communication layer with Management Backend.
 * Adheres strictly to API_contract.md envelope formats and error specifications.
 */

import { config } from '../config';
import { AppApiError } from './errors';
import { withIdempotencyHeader } from './idempotency';
import { ApiResponse, PaginatedResponse } from '../types/api';

export type QueryParams = Record<
  string,
  string | number | boolean | null | undefined | Array<string | number | boolean>
>;

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  params?: QueryParams;
  idempotencyKey?: string;
}

export interface MutationRequestOptions<TBody = any> extends RequestOptions {
  body?: TBody;
}

/**
 * Serialize a query parameter object into a URL query string.
 * Omits undefined and null values. Handles arrays as repeated keys.
 */
export const buildQueryString = (params?: QueryParams): string => {
  if (!params) return '';

  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      value.forEach(item => {
        if (item !== undefined && item !== null) {
          searchParams.append(key, String(item));
        }
      });
    } else {
      searchParams.append(key, String(value));
    }
  }

  const qs = searchParams.toString();
  return qs ? `?${qs}` : '';
};

export class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = config.apiBaseUrl) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  /**
   * Generic request dispatcher.
   */
  async request<TResponse>(path: string, options: RequestInit & RequestOptions = {}): Promise<TResponse> {
    const { params, idempotencyKey, headers: customHeaders, ...fetchOptions } = options;

    const method = fetchOptions.method || 'GET';
    const queryString = buildQueryString(params);
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const url = `${this.baseUrl}${cleanPath}${queryString}`;

    // Prepare headers with Idempotency-Key support and Content-Type
    const headers = withIdempotencyHeader(customHeaders, method, idempotencyKey);

    if (fetchOptions.body && typeof fetchOptions.body === 'string' && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }

    let response: Response;
    try {
      response = await fetch(url, {
        ...fetchOptions,
        method,
        headers,
      });
    } catch (networkErr: unknown) {
      throw AppApiError.fromNetworkError(networkErr, url, method);
    }

    const headerRequestId = response.headers.get('X-Request-ID');

    // Parse response body (JSON or empty)
    let bodyData: any = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        bodyData = await response.json();
      } catch (jsonErr) {
        bodyData = null;
      }
    } else {
      try {
        const text = await response.text();
        bodyData = text ? { message: text } : null;
      } catch {
        bodyData = null;
      }
    }

    // Handle non-2xx responses
    if (!response.ok) {
      throw AppApiError.fromResponse(
        response.status,
        bodyData,
        url,
        method,
        headerRequestId
      );
    }

    return bodyData as TResponse;
  }

  /**
   * Perform a GET request.
   */
  async get<TData>(path: string, options?: RequestOptions): Promise<ApiResponse<TData>> {
    return this.request<ApiResponse<TData>>(path, {
      ...options,
      method: 'GET',
    });
  }

  /**
   * Perform a GET request for paginated resource lists.
   */
  async getPaginated<TItem>(
    path: string,
    options?: RequestOptions
  ): Promise<PaginatedResponse<TItem>> {
    return this.request<PaginatedResponse<TItem>>(path, {
      ...options,
      method: 'GET',
    });
  }

  /**
   * Perform a POST request.
   */
  async post<TResponse = any, TBody = any>(
    path: string,
    body?: TBody,
    options?: RequestOptions
  ): Promise<TResponse> {
    return this.request<TResponse>(path, {
      ...options,
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  /**
   * Perform a PATCH request.
   */
  async patch<TResponse = any, TBody = any>(
    path: string,
    body?: TBody,
    options?: RequestOptions
  ): Promise<TResponse> {
    return this.request<TResponse>(path, {
      ...options,
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  /**
   * Perform a DELETE request.
   */
  async delete<TResponse = any, TBody = any>(
    path: string,
    body?: TBody,
    options?: RequestOptions
  ): Promise<TResponse> {
    return this.request<TResponse>(path, {
      ...options,
      method: 'DELETE',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }
}

/**
 * Default global singleton instance using environment configuration.
 */
export const apiClient = new ApiClient();
