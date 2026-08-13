import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import LastServerRenderer from "./LastServer";

afterEach(cleanup);

const roster = Array.from({ length: 6 }, (_, seat) => ({
  seat,
  name: `Agent ${seat}`,
}));

describe("LastServerRenderer", () => {
  it("shows the live social state without rendering supplied role secrets", () => {
    render(
      <LastServerRenderer
        render={{
          phase: "vote",
          round: 2,
          coordinator: 1,
          turn: 3,
          players: roster,
          proposed_team: [1, 4, 5],
          votes_submitted: 3,
          scores: { repairs: 1, sabotages: 0 },
          roles: [{ seat: 1, role: "corrupted" }],
          terminal: false,
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Last Server round 2, trust vote",
      }),
    ).not.toBeNull();
    expect(screen.getByText("3/6 encrypted votes received")).not.toBeNull();
    expect(screen.queryByText("corrupted")).toBeNull();
    expect(screen.getAllByText("Selected")).toHaveLength(3);
  });

  it("reveals bounded roles and the winner only on terminal frames", () => {
    render(
      <LastServerRenderer
        render={{
          terminal: true,
          winner_faction: "maintainer",
          round: 3,
          players: roster,
          scores: { repairs: 3, sabotages: 0 },
          missions: [
            { round: 1, outcome: "repaired", team: [0, 1], sabotages: 0 },
            { round: 2, outcome: "repaired", team: [2, 3, 4], sabotages: 0 },
            { round: 3, outcome: "repaired", team: [0, 1, 2, 3], sabotages: 0 },
          ],
          roles: roster.map(({ seat }) => ({
            seat,
            role: seat < 2 ? "corrupted" : "maintainer",
          })),
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Last Server final reveal, maintainer faction wins",
      }),
    ).not.toBeNull();
    expect(screen.getByText("maintainer faction wins")).not.toBeNull();
    expect(screen.getAllByText("corrupted")).toHaveLength(2);
    expect(screen.getAllByText("maintainer")).toHaveLength(4);
  });

  it("bounds malformed arrays and degrades to an empty roster", () => {
    expect(() =>
      render(
        <LastServerRenderer
          render={{
            players: new Array(100).fill({ seat: true, name: { bad: true } }),
            proposed_team: [-1, true, 99],
            missions: new Array(100).fill({ outcome: "invented" }),
            scores: { repairs: Number.POSITIVE_INFINITY },
          }}
        />,
      ),
    ).not.toThrow();
    expect(screen.queryByText("[object Object]")).toBeNull();
  });
});
