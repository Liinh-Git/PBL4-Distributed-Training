/**
 * WebSocket realtime client for attempt monitoring.
 * Connection: ws://host/ws/v1/attempts/{attempt_id}?after_seq={seq}
 */

const WS_BASE = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? 'ws://localhost:8000/ws/v1';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface RealtimeMessage {
  kind?: string;
  attempt_id?: string | null;
  runtime_event_seq?: number | null;
  occurred_at?: string | null;
  payload?: unknown;
}

export type MessageHandler = (msg: RealtimeMessage) => void;
export type StatusHandler = (status: WsStatus) => void;

export function createAttemptRealtimeClient(
  attemptId: string,
  initialSeq: number | null = null,
  maxReconnectDelayMs = 10_000
) {
  let ws: WebSocket | null = null;
  const messageHandlers = new Set<MessageHandler>();
  const statusHandlers = new Set<StatusHandler>();
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let pingInterval: ReturnType<typeof setInterval> | null = null;
  let shouldReconnect = true;
  let highestContiguousSeq: number | null = initialSeq;

  function setStatus(status: WsStatus) {
    for (const h of statusHandlers) h(status);
  }

  function send(data: object) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data));
  }

  function clearTimers() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pingInterval) { clearInterval(pingInterval); pingInterval = null; }
  }

  let reconnectAttempts = 0;
  const BASE_RECONNECT_MS = 800;

  function scheduleReconnect() {
    clearTimers();
    reconnectAttempts++;
    const expDelay = BASE_RECONNECT_MS * Math.pow(1.8, Math.min(reconnectAttempts - 1, 5));
    const jitter = Math.random() * 400;
    const delay = Math.min(expDelay + jitter, maxReconnectDelayMs);
    reconnectTimer = setTimeout(() => { if (shouldReconnect) connect(); }, delay);
  }

  function setHighestContiguousSeq(seq: number | null) {
    highestContiguousSeq = seq;
  }

  function getHighestContiguousSeq() {
    return highestContiguousSeq;
  }

  function connect() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;
    clearTimers();
    setStatus('connecting');
    const query = highestContiguousSeq !== null ? `?after_seq=${highestContiguousSeq}` : '';
    const url = `${WS_BASE}/attempts/${attemptId}${query}`;
    try { ws = new WebSocket(url); } catch { setStatus('error'); scheduleReconnect(); return; }

    ws.onopen = () => {
      reconnectAttempts = 0;
      setStatus('connected');
      pingInterval = setInterval(() => send({ kind: 'PING' }), 20_000);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as RealtimeMessage;
        const kind = (msg.kind || '').toUpperCase();
        if (kind === 'PONG') return;

        // Auto-track sequence cursor from canonical frames
        if (kind === 'SNAPSHOT') {
          const d = (msg.payload || {}) as { runtime_event_seq?: number; snapshot_seq?: number };
          const seq = msg.runtime_event_seq ?? d?.runtime_event_seq ?? d?.snapshot_seq;
          if (typeof seq === 'number') {
            highestContiguousSeq = seq;
          }
        } else if (kind === 'GAP') {
          const d = (msg.payload || {}) as { authoritative_seq?: number; snapshot_seq?: number };
          const seq = d?.authoritative_seq ?? d?.snapshot_seq;
          if (typeof seq === 'number') {
            highestContiguousSeq = seq;
          }
        } else if (kind === 'EVENT') {
          const seq = msg.runtime_event_seq;
          if (typeof seq === 'number') {
            if (highestContiguousSeq !== null && seq === highestContiguousSeq + 1) {
              highestContiguousSeq = seq;
            }
          }
        }

        for (const h of messageHandlers) h(msg);
      } catch { /* malformed */ }
    };
    ws.onerror = () => setStatus('error');
    ws.onclose = () => {
      clearTimers();
      setStatus('disconnected');
      if (shouldReconnect) scheduleReconnect();
    };
  }

  function disconnect() {
    shouldReconnect = false;
    clearTimers();
    if (ws) { ws.onclose = null; ws.close(); ws = null; }
    setStatus('disconnected');
  }

  function onMessage(handler: MessageHandler) {
    messageHandlers.add(handler);
    return () => messageHandlers.delete(handler);
  }

  function onStatus(handler: StatusHandler) {
    statusHandlers.add(handler);
    return () => statusHandlers.delete(handler);
  }

  return {
    connect,
    disconnect,
    onMessage,
    onStatus,
    setHighestContiguousSeq,
    getHighestContiguousSeq,
  };
}

export type AttemptRealtimeClient = ReturnType<typeof createAttemptRealtimeClient>;
