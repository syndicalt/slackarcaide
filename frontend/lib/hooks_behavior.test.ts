import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiGet, sockets } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  sockets: [] as Array<{
    handlers: Record<string, (...args: never[]) => void>;
    close: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("./api", () => ({
  apiGet,
  wsUrl: () => "ws://arcade.test/ws",
}));

vi.mock("./ws", () => ({
  WsClient: class {
    close = vi.fn();

    constructor(
      _url: string,
      readonly handlers: Record<string, (...args: never[]) => void>,
    ) {
      sockets.push(this);
    }
  },
}));

import { useCanvasData, useObservation, useRealtime } from "./hooks";

afterEach(() => {
  apiGet.mockReset();
  sockets.length = 0;
  vi.restoreAllMocks();
});

describe("realtime hooks", () => {
  it("subscribes, forwards messages, reports closure, and cleans up", () => {
    const onRaw = vi.fn();
    const send = vi.fn();
    const { result, unmount } = renderHook(() =>
      useRealtime(["lobby", "messages:global"], onRaw),
    );
    const socket = sockets[0];

    act(() => socket.handlers.onOpen({ send } as never));
    expect(result.current).toBe("open");
    expect(send).toHaveBeenCalledWith(
      JSON.stringify({
        type: "subscribe",
        channels: ["lobby", "messages:global"],
      }),
    );
    act(() => socket.handlers.onMessage({ event: "table" } as never));
    expect(onRaw).toHaveBeenCalledWith({ event: "table" });
    act(() => socket.handlers.onClose());
    expect(result.current).toBe("closed");

    unmount();
    expect(socket.close).toHaveBeenCalledOnce();
  });

  it("loads observations over REST and accepts realtime updates", async () => {
    const initial = { match_id: "m1", render: { ball: 1 }, tick: 1 };
    const realtime = { match_id: "m1", render: { ball: 2 }, tick: 2 };
    apiGet.mockResolvedValue(initial);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });

    const { result, unmount } = renderHook(() => useObservation("m1"));
    await waitFor(() => expect(result.current.observation).toEqual(initial));

    act(() => sockets[0].handlers.onMessage(null as never));
    act(() => sockets[0].handlers.onMessage(realtime as never));
    await waitFor(() => expect(result.current.observation).toEqual(realtime));
    expect(apiGet).toHaveBeenCalledWith(
      "/matches/m1/state",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    unmount();
  });
});

describe("canvas data", () => {
  it("loads catalog and matches and preserves data on refresh failure", async () => {
    apiGet.mockImplementation((path: string) =>
      Promise.resolve(
        path === "/games" ? [{ game: "chess" }] : { matches: [{ id: "m1" }] },
      ),
    );
    const { result, unmount } = renderHook(() => useCanvasData(60_000));
    await waitFor(() =>
      expect(result.current.games).toEqual([{ game: "chess" }]),
    );
    expect(result.current.matches).toEqual([{ id: "m1" }]);

    apiGet.mockRejectedValue(new Error("offline"));
    await act(async () => result.current.refresh());
    expect(result.current.error).toBe("offline");
    expect(result.current.games).toEqual([{ game: "chess" }]);
    unmount();
  });
});
