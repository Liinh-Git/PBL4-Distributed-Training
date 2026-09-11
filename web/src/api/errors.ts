/**
 * API Error Normalization & Abstraction
 *
 * Provides a uniform error structure across network failures, validation errors,
 * business rule conflicts (409), not found (404), and server errors (5xx).
 */

import { ApiErrorDetail, ApiErrorResponse } from '../types/api';

export interface ApiErrorOptions {
  status: number;
  code: string;
  message: string;
  details?: Record<string, any> | null;
  requestId?: string;
  commandId?: string | null;
  url?: string;
  method?: string;
  rawError?: unknown;
}

export class AppApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, any> | null;
  readonly requestId?: string;
  readonly commandId?: string | null;
  readonly url?: string;
  readonly method?: string;
  readonly rawError?: unknown;

  constructor(options: ApiErrorOptions) {
    super(options.message || `API Error (${options.code})`);
    this.name = 'AppApiError';
    this.status = options.status;
    this.code = options.code;
    this.details = options.details ?? null;
    this.requestId = options.requestId;
    this.commandId = options.commandId;
    this.url = options.url;
    this.method = options.method;
    this.rawError = options.rawError;

    // Maintain proper prototype chain in transpiled ES
    Object.setPrototypeOf(this, new.target.prototype);
  }

  get isNetworkError(): boolean {
    return this.status === 0 || this.code === 'NETWORK_ERROR';
  }

  get isValidationError(): boolean {
    return this.status === 422 || this.code === 'VALIDATION_ERROR';
  }

  get isNotFound(): boolean {
    return this.status === 404 || this.code === 'NOT_FOUND';
  }

  get isConflict(): boolean {
    return this.status === 409 || this.code === 'CONFLICT';
  }

  get isServerError(): boolean {
    return this.status >= 500;
  }

  /**
   * Parse error from an HTTP Response and response body.
   */
  static fromResponse(
    status: number,
    body: unknown,
    url?: string,
    method?: string,
    headerRequestId?: string | null
  ): AppApiError {
    let code = `HTTP_${status}`;
    let message = `Request failed with status ${status}`;
    let details: Record<string, any> | null = null;
    let requestId: string | undefined = headerRequestId || undefined;
    let commandId: string | null = null;

    if (body && typeof body === 'object') {
      const errorObj = (body as ApiErrorResponse).error as ApiErrorDetail | undefined;
      if (errorObj && typeof errorObj === 'object') {
        code = errorObj.code || code;
        message = errorObj.message || message;
        details = errorObj.details || null;
        requestId = errorObj.request_id || requestId;
        commandId = errorObj.command_id || null;
      } else if ('message' in body && typeof (body as any).message === 'string') {
        message = (body as any).message;
      } else if ('detail' in body) {
        const detail = (body as any).detail;
        if (typeof detail === 'string') {
          message = detail;
        } else if (typeof detail === 'object' && detail !== null) {
          code = detail.code || code;
          message = detail.message || message;
          details = detail.details || detail;
        }
      }
    }

    return new AppApiError({
      status,
      code,
      message,
      details,
      requestId,
      commandId,
      url,
      method,
      rawError: body,
    });
  }

  /**
   * Create a network or unexpected error instance.
   */
  static fromNetworkError(error: unknown, url?: string, method?: string): AppApiError {
    const message =
      error instanceof Error
        ? error.message
        : 'Network connection failure or server unreachable.';

    return new AppApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message,
      details: null,
      url,
      method,
      rawError: error,
    });
  }
}
