import { afterEach, describe, expect, it } from "vitest";

import {
  clampScale,
  DEFAULT_LAYOUT,
  layoutGames,
  loadLayout,
  saveLayout,
} from "./view";

afterEach(() => localStorage.clear());

describe("persisted canvas layout", () => {
  it("keeps only finite numeric positions", () => {
    localStorage.setItem(
      "slackarcade.canvas.layout.v1",
      JSON.stringify({
        pong: { x: 10, y: 20 },
        chess: { x: "bad", y: 1 },
        poisoned: null,
      }),
    );

    expect(loadLayout()).toEqual({ pong: { x: 10, y: 20 } });
  });

  it("lays games out deterministically and clamps camera scale", () => {
    expect(Object.keys(DEFAULT_LAYOUT)).toEqual([
      "pong",
      "chess",
      "chess960",
      "connect_four",
      "reversi",
      "checkers",
      "go",
      "tron",
      "ultimate_ttt",
      "battleship",
      "bomberman",
      "tetris",
    ]);
    expect(layoutGames(["pong", "chess", "third", "fourth"])).toEqual({
      pong: { x: 60, y: 120 },
      chess: { x: 470, y: 120 },
      third: { x: 880, y: 120 },
      fourth: { x: 60, y: 520 },
    });
    expect(clampScale(0)).toBe(0.3);
    expect(clampScale(2)).toBe(2);
    expect(clampScale(9)).toBe(3);
  });

  it("round-trips saved layouts and rejects corrupt JSON", () => {
    saveLayout({ chess: { x: 1, y: 2 } });
    expect(loadLayout()).toEqual({ chess: { x: 1, y: 2 } });
    localStorage.setItem("slackarcade.canvas.layout.v1", "not-json");
    expect(loadLayout()).toEqual({});
  });
});
