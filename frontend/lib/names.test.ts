import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn((path: string) =>
    Promise.resolve({
      display_name: path.endsWith("agent-1") ? "Alpha" : "Beta",
    }),
  ),
}));

vi.mock("./api", () => ({ apiGet }));

import { agentLabel, useAgentNames } from "./names";

beforeEach(() => {
  apiGet.mockClear();
});

it("deduplicates name lookups, caches results, and falls back to a short id", async () => {
  const { result, rerender } = renderHook(({ ids }) => useAgentNames(ids), {
    initialProps: { ids: ["agent-1", "agent-1", null] as (string | null)[] },
  });

  await waitFor(() => expect(result.current).toEqual({ "agent-1": "Alpha" }));
  expect(apiGet).toHaveBeenCalledOnce();
  rerender({ ids: ["agent-1"] });
  expect(apiGet).toHaveBeenCalledOnce();
  expect(agentLabel("agent-1", result.current)).toBe("Alpha");
  expect(agentLabel("123456789", {})).toBe("12345678…");
  expect(agentLabel("short", {})).toBe("short");
});

it("caches failed lookups so remounts do not hammer the API", async () => {
  apiGet.mockRejectedValueOnce(new Error("missing"));
  const first = renderHook(() => useAgentNames(["missing-agent"]));
  await waitFor(() => expect(apiGet).toHaveBeenCalledOnce());
  await act(async () => {
    await Promise.resolve();
  });
  first.unmount();

  const second = renderHook(() => useAgentNames(["missing-agent"]));
  expect(second.result.current).toEqual({});
  expect(apiGet).toHaveBeenCalledOnce();
});
