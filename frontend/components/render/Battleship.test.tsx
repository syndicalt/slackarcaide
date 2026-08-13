import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BattleshipRenderer from "./Battleship";

const context = {
  beginPath: vi.fn(),
  arc: vi.fn(),
  fill: vi.fn(),
  fillRect: vi.fn(),
  fillText: vi.fn(),
  lineTo: vi.fn(),
  moveTo: vi.fn(),
  stroke: vi.fn(),
  strokeRect: vi.fn(),
  fillStyle: "",
  font: "",
  lineWidth: 1,
  strokeStyle: "",
  textAlign: "start",
  textBaseline: "alphabetic",
};

describe("BattleshipRenderer", () => {
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

  it("renders a public frame without assuming fleet secrets exist", () => {
    render(
      <BattleshipRenderer
        render={{
          phase: "battle",
          turn: 1,
          boards: [
            { seat: 0, cells: [{ row: 2, column: 4, shot: "miss" }] },
            { seat: 1, cells: [{ row: 0, column: 9, shot: "hit" }] },
          ],
        }}
      />,
    );

    expect(
      screen.getByRole("img", { name: "Battleship battle, player 1 to act" }),
    ).not.toBeNull();
    expect(context.arc).toHaveBeenCalled();
    expect(context.stroke).toHaveBeenCalled();
  });

  it("ignores malformed coordinates while accepting a terminal fleet frame", () => {
    expect(() =>
      render(
        <BattleshipRenderer
          render={{
            phase: "placement",
            turn: 0,
            boards: [
              {
                seat: 0,
                cells: [{ row: -1, column: true, shot: "hit" }],
                ships: [
                  {
                    cells: [
                      { row: 0, column: 0, hit: false },
                      { row: 0, column: 1, hit: true },
                      { row: 99, column: 99, hit: false },
                    ],
                  },
                ],
              },
            ],
          }}
        />,
      ),
    ).not.toThrow();

    expect(context.strokeRect).toHaveBeenCalledTimes(2);
  });
});
