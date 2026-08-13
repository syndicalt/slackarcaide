import { describe, expect, it } from "vitest";

import { hasRenderer } from "./index";

describe("game renderer registry", () => {
  it("renders both chess variants with the chess board", () => {
    expect(hasRenderer("chess")).toBe(true);
    expect(hasRenderer("chess960")).toBe(true);
  });

  it.each([
    "connect_four",
    "reversi",
    "checkers",
    "go",
    "pong",
    "tron",
    "ultimate_ttt",
    "battleship",
    "bomberman",
    "tetris",
  ])("registers the %s production renderer", (game) =>
    expect(hasRenderer(game)).toBe(true),
  );

  it("rejects unregistered renderers", () => {
    expect(hasRenderer("unknown-game")).toBe(false);
  });
});
