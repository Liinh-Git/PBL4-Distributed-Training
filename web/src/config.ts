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
  if (envUrl && typeof envUrl === 'string' && envUrl.trim() !== '') {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return 'http://localhost:8000';
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
  return 'ws://localhost:8000';
};

export const config: AppConfig = {
  apiBaseUrl: resolveApiBaseUrl(),
  wsBaseUrl: resolveWsBaseUrl(),
};
