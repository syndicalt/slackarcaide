import { afterEach, describe, expect, it, vi } from "vitest";

import { apiGet, wsHost } from "./api";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api transport", () => {
  it("builds secure websocket URLs from absolute HTTPS bases", () => {
    expect(wsHost("https://arcade.example/api/")).toBe(
      "wss://arcade.example/api/ws",
    );
  });

  it("normalizes malformed error envelopes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: null }), {
        status: 500,
        statusText: "Server Error",
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiGet("/broken")).rejects.toMatchObject({
      message: "Server Error",
      status: 500,
      api: { code: "http_error", message: "Server Error" },
    });
  });

  it("aborts requests after the configured timeout", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );

    await expect(apiGet("/slow", { timeoutMs: 1 })).rejects.toMatchObject({
      name: "TimeoutError",
    });
  });
});
