import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BombermanRenderer from "./Bomberman";

const context = {
  arc: vi.fn(),
  beginPath: vi.fn(),
  fill: vi.fn(),
  fillRect: vi.fn(),
  fillText: vi.fn(),
  lineTo: vi.fn(),
  moveTo: vi.fn(),
  restore: vi.fn(),
  save: vi.fn(),
  setTransform: vi.fn(),
  stroke: vi.fn(),
  translate: vi.fn(),
  fillStyle: "",
  font: "",
  lineWidth: 1,
  shadowBlur: 0,
  shadowColor: "",
  strokeStyle: "",
  textAlign: "start",
  textBaseline: "alphabetic",
};

describe("BombermanRenderer", () => {
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

  it("renders every arena entity and the bounded HUD", () => {
    render(
      <BombermanRenderer
        render={{
          width: 13,
          height: 11,
          solid_walls: [[0, 0]],
          crates: [[3, 1]],
          players: [
            {
              seat: 0,
              position: [1, 1],
              alive: true,
              capacity: 2,
              blast_range: 3,
              active_bombs: 1,
            },
            {
              seat: 1,
              position: [11, 9],
              alive: false,
              capacity: 1,
              blast_range: 2,
              active_bombs: 0,
            },
          ],
          bombs: [{ position: [2, 1], owner: 0, fuse: 7 }],
          flames: [{ position: [4, 1], remaining: 3 }],
          powerups: [{ position: [5, 1], kind: "capacity" }],
          tick: 42,
          max_ticks: 2400,
        }}
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "13 by 11 Bomberman arena at tick 42, 1 player alive",
      }),
    ).not.toBeNull();
    expect(context.arc).toHaveBeenCalled();
    expect(context.fillRect).toHaveBeenCalled();
    expect(context.fillText).toHaveBeenCalledWith(
      "7",
      expect.any(Number),
      expect.any(Number),
    );
    expect(context.fillText).toHaveBeenCalledWith(
      "P1  B 1/2  R 3",
      expect.any(Number),
      expect.any(Number),
    );
  });

  it("falls back safely when a replay frame is malformed or oversized", () => {
    expect(() =>
      render(
        <BombermanRenderer
          render={{
            width: Infinity,
            height: true,
            solid_walls: [[-1, 0], [0, 999], "bad"],
            crates: { not: "an array" },
            players: [{ seat: 7, position: [1, 1] }, null],
            bombs: [{ position: [1, 1], owner: "zero", fuse: NaN }],
            flames: [{ position: [1, 1], remaining: Infinity }],
            powerups: [{ position: [1, 1], kind: "speed" }],
            tick: -1,
            max_ticks: "forever",
          }}
        />,
      ),
    ).not.toThrow();

    expect(
      screen.getByRole("img", {
        name: "13 by 11 Bomberman arena at tick 0, 0 players alive",
      }),
    ).not.toBeNull();
  });
});
