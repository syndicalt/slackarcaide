import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TetrisRenderer from "./Tetris";

const context = {
  beginPath: vi.fn(),
  clearRect: vi.fn(),
  fillRect: vi.fn(),
  fillText: vi.fn(),
  lineTo: vi.fn(),
  moveTo: vi.fn(),
  setTransform: vi.fn(),
  stroke: vi.fn(),
  strokeRect: vi.fn(),
  fillStyle: "",
  font: "",
  lineWidth: 1,
  strokeStyle: "",
  textAlign: "start",
  textBaseline: "alphabetic",
};

describe("TetrisRenderer", () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      () => context as unknown as CanvasRenderingContext2D,
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("draws both boards, garbage, current/next previews, and the battle HUD", () => {
    render(
      <TetrisRenderer
        render={{
          columns: 10,
          rows: 20,
          tick: 12,
          max_ticks: 1200,
          boards: [
            {
              seat: 0,
              board: Array.from({ length: 20 }, (_, row) =>
                Array.from({ length: 10 }, (_, column) =>
                  row === 19 ? (column === 4 ? null : "G") : null,
                ),
              ),
              current: "T",
              next: ["I", "O"],
              score: 800,
              lines: 4,
              attacks: 4,
              garbage_received: 0,
              pieces: 12,
              top_out: false,
            },
            {
              seat: 1,
              board: [["Z"]],
              current: "S",
              next: ["L", "J"],
              score: 300,
              lines: 2,
              attacks: 1,
              garbage_received: 3,
              pieces: 11,
              top_out: false,
            },
          ],
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "10 by 20 Battle Tetris in progress",
      }),
    ).not.toBeNull();
    expect(context.setTransform).toHaveBeenCalled();
    expect(context.fillRect).toHaveBeenCalled();
    expect(context.fillText).toHaveBeenCalledWith(
      "BATTLE TETRIS  ·  TICK 12 / 1200",
      expect.any(Number),
      expect.any(Number),
    );
    expect(context.fillText).toHaveBeenCalledWith(
      "CURRENT",
      expect.any(Number),
      expect.any(Number),
    );
    expect(context.fillText).toHaveBeenCalledWith(
      "NEXT",
      expect.any(Number),
      expect.any(Number),
    );
  });

  it("renders a terminal winner and top-out overlay", () => {
    render(
      <TetrisRenderer
        render={{
          terminal: true,
          winner: [0],
          boards: [{ seat: 1, top_out: true }],
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "10 by 20 Battle Tetris finished; player 0 wins",
      }),
    ).not.toBeNull();
    expect(context.fillText).toHaveBeenCalledWith(
      "TOP OUT",
      expect.any(Number),
      expect.any(Number),
    );
  });

  it("bounds dimensions and ignores malformed nested render data", () => {
    expect(() =>
      render(
        <TetrisRenderer
          render={{
            columns: 1_000_000,
            rows: Number.POSITIVE_INFINITY,
            tick: -1,
            max_ticks: "forever",
            terminal: true,
            winner: [0, 1],
            boards: [
              {
                seat: 0,
                board: [["I", "unknown", {}, true], "not a row"],
                current: "unknown",
                next: ["T", {}, "I", "extra"],
                score: Number.POSITIVE_INFINITY,
                lines: -4,
                top_out: "yes",
              },
              null,
            ],
          }}
        />,
      ),
    ).not.toThrow();

    expect(
      screen.getByRole("img", {
        name: "10 by 20 Battle Tetris finished in a draw",
      }),
    ).not.toBeNull();
    const canvas = screen.getByRole("img") as HTMLCanvasElement;
    expect(canvas.width).toBeLessThan(2_000);
    expect(canvas.height).toBeLessThan(1_000);
  });
});
