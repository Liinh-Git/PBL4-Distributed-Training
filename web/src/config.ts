/**
 * Application environment configuration.
 *
 * Source of truth for API base URLs and runtime communication endpoints.
 */

export interface AppConfig {
  apiBaseUrl: string;
  wsBaseUrl: string;
}

const getEnvVar = (key: 'VITE_API_BASE_URL' | 'VITE_WS_BASE_URL'): string | undefined => {
  if (typeof import.meta !== 'undefined' && import.meta.env) {
    return import.meta.env[key];
  }
  if (typeof process !== 'undefined' && process.env) {
    return process.env[key];
  }
  return undefined;
};

const resolveApiBaseUrl = (): string => {
  const envUrl = getEnvVar('VITE_API_BASE_URL');
  if (envUrl !== undefined && typeof envUrl === 'string') {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return '';
};

const resolveWsBaseUrl = (): string => {
  const envUrl = getEnvVar('VITE_WS_BASE_URL');
  if (envUrl && typeof envUrl === 'string' && envUrl.trim() !== '') {
    return envUrl.trim().replace(/\/+$/, '');
  }
  // If API base URL is configured as http/https, derive ws/wss
  const apiBase = resolveApiBaseUrl();
  if (apiBase.startsWith('https://')) {
    return apiBase.replace('https://', 'wss://');
  }
  if (apiBase.startsWith('http://')) {
    return apiBase.replace('http://', 'ws://');
  }
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}`;
  }
  return '';
};

export const config: AppConfig = {
  apiBaseUrl: resolveApiBaseUrl(),
  wsBaseUrl: resolveWsBaseUrl(),
};
