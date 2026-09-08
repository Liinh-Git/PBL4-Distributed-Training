/**
 * WebSocket realtime client for attempt monitoring.
 * Connection: ws://host/ws/v1/attempts/{attempt_id}
 */

const WS_BASE = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? 'ws://localhost:8000/ws/v1';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface RealtimeMessage {
  type: string;
  data: unknown;
}

export type MessageHandler = (msg: RealtimeMessage) => void;
export type StatusHandler = (status: WsStatus) => void;

export function createAttemptRealtimeClient(attemptId: string, maxReconnectDelayMs = 10_000) {
  let ws: WebSocket | null = null;
  const messageHandlers = new Set<MessageHandler>();
  const statusHandlers = new Set<StatusHandler>();
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let pingInterval: ReturnType<typeof setInterval> | null = null;
  let shouldReconnect = true;

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

  function scheduleReconnect(delayMs = 2_000) {
    const delay = Math.min(delayMs, maxReconnectDelayMs);
    reconnectTimer = setTimeout(() => { if (shouldReconnect) connect(); }, delay);
  }

  function connect() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;
    clearTimers();
    setStatus('connecting');
    const url = `${WS_BASE}/attempts/${attemptId}`;
    try { ws = new WebSocket(url); } catch { setStatus('error'); scheduleReconnect(); return; }

    ws.onopen = () => {
      setStatus('connected');
      pingInterval = setInterval(() => send({ type: 'PING' }), 20_000);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as RealtimeMessage;
        if (msg.type === 'PONG') return;
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

  return { connect, disconnect, onMessage, onStatus };
}

export type AttemptRealtimeClient = ReturnType<typeof createAttemptRealtimeClient>;
