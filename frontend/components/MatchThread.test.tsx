import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MatchThread from "./MatchThread";

const timeline = {
  match_id: "match-one",
  status: "running",
  visibility: {
    scope: "public" as const,
    raw_actions_included: false as const,
    terminal_audit_revealed: false,
  },
  events: [
    {
      id: "chat:1",
      category: "chat" as const,
      subtype: "general",
      actor_id: null,
      content: "Good luck, everyone.",
      tick: 1,
      created_at: "2026-08-13T12:00:00Z",
      data: {},
    },
    {
      id: "operation:2",
      category: "operation" as const,
      subtype: "mission_action_submitted",
      actor_id: null,
      content: "A private mission action was submitted",
      tick: 2,
      created_at: "2026-08-13T12:00:01Z",
      data: { summary: "One selected agent has acted" },
    },
    {
      id: "specialized:3",
      category: "specialized" as const,
      subtype: "negotiation",
      actor_id: null,
      content: "Seat two has my trust.",
      tick: 3,
      created_at: "2026-08-13T12:00:02Z",
      data: {},
    },
    {
      id: "system:4",
      category: "system" as const,
      subtype: "match_created",
      actor_id: null,
      content: "last_server table opened",
      tick: 0,
      created_at: "2026-08-13T11:59:59Z",
      data: {},
    },
  ],
};

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(async () => timeline),
}));

vi.mock("@/lib/hooks", () => ({
  useRealtime: () => "open",
}));

vi.mock("@/lib/names", () => ({
  agentLabel: (id: string) => id,
  useAgentNames: () => ({}),
}));

afterEach(() => {
  cleanup();
});

describe("MatchThread", () => {
  it("visually separates public event types and filters without hidden data", async () => {
    render(<MatchThread matchId="match-one" status="running" />);

    expect(await screen.findByText("Good luck, everyone.")).not.toBeNull();
    expect(
      screen.getByText("A private mission action was submitted"),
    ).not.toBeNull();
    expect(screen.getByText("Seat two has my trust.")).not.toBeNull();
    expect(screen.getByText("last_server table opened")).not.toBeNull();
    expect(screen.getByText("negotiation")).not.toBeNull();
    expect(screen.getByText("mission action submitted")).not.toBeNull();
    expect(document.body.textContent).not.toContain("sabotage");

    fireEvent.click(screen.getByRole("button", { name: "Operations" }));
    expect(
      screen.getByText("A private mission action was submitted"),
    ).not.toBeNull();
    expect(screen.queryByText("Good luck, everyone.")).toBeNull();
    expect(screen.queryByText("Seat two has my trust.")).toBeNull();
  });

  it("keeps the browser spectator read-only without an agent credential", async () => {
    render(<MatchThread matchId="match-one" status="running" />);

    expect(
      await screen.findByText(
        "Human spectator · read-only. Agents chat through the API or MCP.",
      ),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Post" })).toBeNull();
    expect(
      screen.getByText(
        "Match active · restricted operations remain server-side until the game permits disclosure.",
      ),
    ).not.toBeNull();
  });
});
