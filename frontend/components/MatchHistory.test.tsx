import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MatchHistory from "./MatchHistory";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function match(id: string, summary: string) {
  return {
    id,
    game_type: "tron",
    mode: "realtime",
    status: "finished",
    players: [
      { agent_id: "agent-a", seat: 0, name: "Alpha" },
      { agent_id: "agent-b", seat: 1, name: "Beta" },
    ],
    result: {},
    ended_at: "2026-08-13T00:00:00Z",
    tick_or_move_count: 42,
    outcome: "win",
    final_summary: summary,
    winner_seats: [0],
    replay_url: `/matches/${id}/replay`,
  };
}

describe("MatchHistory", () => {
  it("renders durable results and follows the opaque history cursor", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            matches: [match("match-one", "Alpha wins")],
            next_cursor: "opaque-cursor",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            matches: [match("match-two", "Alpha wins again")],
            next_cursor: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<MatchHistory agentId="agent-a" game="tron" pageSize={1} />);

    expect(await screen.findByText("Alpha wins")).not.toBeNull();
    expect(
      screen.getByRole("link", { name: "Watch replay" }).getAttribute("href"),
    ).toBe("/replay/match-one");

    fireEvent.click(screen.getByRole("button", { name: "Load older games" }));
    expect(await screen.findByText("Alpha wins again")).not.toBeNull();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(String(fetch.mock.calls[1][0])).toContain("before=opaque-cursor");
    expect(String(fetch.mock.calls[1][0])).toContain("agent_id=agent-a");
  });
});
