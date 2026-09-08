import { useState, useEffect, useCallback } from 'react';
import { systemApi } from '../api/system';
import type { HealthResponse, CapabilitiesResponse, RuntimeSnapshot } from '../domain/types';

interface SystemStatus {
  health: HealthResponse | null;
  capabilities: CapabilitiesResponse | null;
  snapshot: RuntimeSnapshot | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useSystemStatus(pollIntervalMs = 15_000): SystemStatus {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitiesResponse | null>(null);
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const [h, c, s] = await Promise.allSettled([
        systemApi.health(),
        systemApi.capabilities(),
        systemApi.runtimeSnapshot(),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (c.status === 'fulfilled') setCapabilities(c.value);
      if (s.status === 'fulfilled') setSnapshot(s.value);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
    const id = setInterval(fetch, pollIntervalMs);
    return () => clearInterval(id);
  }, [fetch, pollIntervalMs]);

  return { health, capabilities, snapshot, loading, error, refresh: fetch };
}
