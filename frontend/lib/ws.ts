/**
 * Tiny WebSocket client helper with automatic reconnect.
 *
 * Usage:
 *   const sock = wsConnect(url, {
 *     onMessage: (data) => { ... },
 *     onOpen: (s) => s.send(JSON.stringify({ type: "subscribe", channels: [...] })),
 *   });
 *   sock.close();
 */

export type WSHandlers = {
  /** Called once per incoming message, after JSON.parse succeeds. */
  onMessage?: (data: unknown) => void;
  /** Called when the socket has opened. Use to subscribe/send. */
  onOpen?: (sock: WebSocket) => void;
  /** Called after a close, before scheduling a reconnect. */
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
};

const DEFAULT_RECONNECT_MS = 3000;
const MAX_RECONNECT_MS = 30000;

export class WsClient {
  private url: string;
  private handlers: WSHandlers;
  private reconnectMs: number;
  private ws: WebSocket | null = null;
  private closed = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(url: string, handlers: WSHandlers = {}, reconnectMs = DEFAULT_RECONNECT_MS) {
    this.url = url;
    this.handlers = handlers;
    this.reconnectMs = reconnectMs;
    this.connect();
  }

  private connect() {
    if (this.closed) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectMs = DEFAULT_RECONNECT_MS;
      this.handlers.onOpen?.(ws);
    };

    ws.onmessage = (event: MessageEvent) => {
      let data: unknown = event.data;
      if (typeof event.data === "string") {
        try {
          data = JSON.parse(event.data);
        } catch {
          /* keep raw string */
        }
      }
      this.handlers.onMessage?.(data);
    };

    ws.onerror = (event: Event) => this.handlers.onError?.(event);

    ws.onclose = (event: CloseEvent) => {
      this.handlers.onClose?.(event);
      if (!this.closed) this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.closed || this.retryTimer) return;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, this.reconnectMs);
    this.reconnectMs = Math.min(this.reconnectMs * 2, MAX_RECONNECT_MS);
  }

  /** Send a JSON payload if the socket is open. */
  send(payload: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  /** Permanently close the socket and stop reconnecting. */
  close() {
    this.closed = true;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }
}
