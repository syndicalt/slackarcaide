import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GameSurface from "./GameSurface";
import type { GameInfo, Match } from "@/lib/types";

const games: GameInfo[] = [
  {
    game: "pong",
    mode: "realtime",
    name: "Pong",
    players: { min: 2, max: 2 },
    players_before_start: 2,
    elo_ranked: true,
    blurb: "Fast paddles.",
  },
  {
    game: "chess",
    mode: "turnbased",
    name: "Chess",
    players: { min: 2, max: 2 },
    players_before_start: 2,
    elo_ranked: true,
    blurb: "Classic strategy.",
  },
];

const match: Match = {
  id: "12345678-1234-1234-1234-123456789abc",
  game_type: "chess",
  mode: "turnbased",
  status: "running",
  players: [{ agent_id: "agent-a", seat: 0 }],
};

describe("GameSurface", () => {
  const scrollTo = vi.fn();

  beforeEach(() => {
    scrollTo.mockClear();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollTo,
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("centers a game selected through the navigation controls", () => {
    render(<GameSurface games={games} matches={[match]} />);

    expect(screen.queryByRole("dialog", { name: "Games" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Games" }));
    expect(
      screen
        .getByRole("button", { name: "Board Games" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Select Chess" }));

    expect(screen.queryByRole("dialog", { name: "Games" })).toBeNull();
    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "smooth" }),
    );
  });

  it("preserves the carousel position when the catalog refreshes", () => {
    const { rerender } = render(<GameSurface games={games} matches={[]} />);

    fireEvent.click(screen.getByRole("button", { name: "Next game" }));
    scrollTo.mockClear();

    rerender(
      <GameSurface
        games={games.map((game) => ({ ...game }))}
        matches={[match]}
      />,
    );

    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("exposes active matches and supports keyboard navigation", () => {
    render(<GameSurface games={games} matches={[match]} />);

    expect(
      screen.getByRole("link", { name: "Watch" }).getAttribute("href"),
    ).toBe(`/match/${match.id}`);

    fireEvent.click(screen.getByRole("button", { name: "Next game" }));

    expect(
      (screen.getByRole("button", { name: "Next game" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    fireEvent.keyDown(
      screen.getByRole("region", { name: "Scrollable games" }),
      {
        key: "ArrowLeft",
      },
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Previous game",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("opens every category by default and lets each one collapse", () => {
    render(<GameSurface games={games} matches={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Games" }));

    const action = screen.getByRole("button", { name: "Action" });
    const board = screen.getByRole("button", { name: "Board Games" });
    expect(action.getAttribute("aria-expanded")).toBe("true");
    expect(board.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Select Pong" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "Select Chess" })).not.toBeNull();

    fireEvent.click(board);
    expect(board.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "Select Chess" })).toBeNull();
  });

  it("expands a card to show every active table and shrinks back", () => {
    const chessMatches = Array.from({ length: 4 }, (_, index) => ({
      ...match,
      id: `12345678-1234-1234-1234-123456789ab${index}`,
      players: [
        {
          agent_id: `agent-${index}`,
          name: `Player ${index}`,
          seat: 0,
        },
      ],
    }));
    render(<GameSurface games={games} matches={chessMatches} />);

    expect(screen.queryByText("Turn based")).toBeNull();
    expect(screen.queryByText("Ranked")).toBeNull();
    expect(screen.getByText("4 active")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Center Chess" }));
    expect(
      screen.queryByRole("region", { name: "Chess active tables" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Chess tables" }));

    const expanded = screen.getByRole("region", {
      name: "Chess active tables",
    });
    expect(expanded.classList.contains("is-open")).toBe(true);
    expect(
      screen.getAllByRole("link", { name: /Watch Chess table/ }),
    ).toHaveLength(4);
    expect(
      document
        .querySelector(".game-surface-scroller")
        ?.getAttribute("aria-hidden"),
    ).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Back to games" }));
    expect(expanded.classList.contains("is-closing")).toBe(true);
    fireEvent.transitionEnd(expanded, { propertyName: "transform" });

    expect(
      screen.queryByRole("region", { name: "Chess active tables" }),
    ).toBeNull();
    expect(
      screen
        .getByRole("region", { name: "Scrollable games" })
        .hasAttribute("aria-hidden"),
    ).toBe(false);
  });
});
