import { afterEach, describe, expect, it, vi } from "vitest";

import { WsClient } from "./ws";

class FakeWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(value: string) {
    this.sent.push(value);
  }

  close() {
    this.closed = true;
    this.readyState = FakeWebSocket.CLOSED;
  }
}

afterEach(() => {
  vi.useRealTimers();
  FakeWebSocket.instances = [];
  vi.unstubAllGlobals();
});

describe("websocket client", () => {
  it("parses JSON, preserves text, sends only while open, and closes permanently", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const messages: unknown[] = [];
    const opened = vi.fn();
    const client = new WsClient("ws://arcade.test/ws", {
      onOpen: opened,
      onMessage: (message) => messages.push(message),
    });
    const socket = FakeWebSocket.instances[0];

    expect(client.readyState).toBe(0);
    client.send({ ignored: true });
    socket.readyState = FakeWebSocket.OPEN;
    socket.onopen?.();
    client.send({ action: "up" });
    socket.onmessage?.(new MessageEvent("message", { data: '{"tick":1}' }));
    socket.onmessage?.(new MessageEvent("message", { data: "not-json" }));

    expect(opened).toHaveBeenCalledWith(socket);
    expect(socket.sent).toEqual(['{"action":"up"}']);
    expect(messages).toEqual([{ tick: 1 }, "not-json"]);

    client.close();
    expect(socket.closed).toBe(true);
    expect(client.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it("reconnects after a remote close but cancels the timer on explicit close", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const onClose = vi.fn();
    const client = new WsClient("ws://arcade.test/ws", { onClose }, 10);
    const first = FakeWebSocket.instances[0];

    first.onclose?.(new CloseEvent("close"));
    expect(onClose).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(10);
    expect(FakeWebSocket.instances).toHaveLength(2);

    FakeWebSocket.instances[1].onclose?.(new CloseEvent("close"));
    client.close();
    vi.runAllTimers();
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
