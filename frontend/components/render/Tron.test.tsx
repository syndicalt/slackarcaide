import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TronRenderer from "./Tron";

const gradient = { addColorStop: vi.fn() };
const context = {
  arc: vi.fn(),
  beginPath: vi.fn(),
  createRadialGradient: vi.fn(() => gradient),
  fill: vi.fn(),
  fillRect: vi.fn(),
  fillText: vi.fn(),
  lineTo: vi.fn(),
  moveTo: vi.fn(),
  restore: vi.fn(),
  rotate: vi.fn(),
  save: vi.fn(),
  setTransform: vi.fn(),
  stroke: vi.fn(),
  translate: vi.fn(),
  fillStyle: "",
  font: "",
  globalAlpha: 1,
  lineCap: "butt",
  lineJoin: "miter",
  lineWidth: 1,
  shadowBlur: 0,
  shadowColor: "",
  strokeStyle: "",
  textAlign: "start",
  textBaseline: "alphabetic",
};

describe("TronRenderer", () => {
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

  it("draws both trails, rider headings, crashes, and tick HUD", () => {
    render(
      <TronRenderer
        render={{
          width: 41,
          height: 31,
          trails: [
            [
              [10, 15],
              [11, 15],
            ],
            [
              [30, 15],
              [29, 15],
            ],
          ],
          heads: [
            [11, 15],
            [29, 15],
          ],
          directions: ["east", "west"],
          alive: [true, false],
          crashes: [{ seat: 1, at: [28, 15] }],
          tick: 12,
          max_ticks: 2500,
        }}
      />,
    );

    expect(screen.getByLabelText("41 by 31 Light Cycles arena")).not.toBeNull();
    expect(context.stroke).toHaveBeenCalled();
    expect(context.arc).toHaveBeenCalled();
    expect(context.fillText).toHaveBeenCalledWith(
      "TICK 12 / 2500",
      expect.any(Number),
      expect.any(Number),
    );
  });

  it("bounds dimensions and ignores malformed oversized frame data", () => {
    expect(() =>
      render(
        <TronRenderer
          render={{
            width: Number.POSITIVE_INFINITY,
            height: -1,
            trails: [Array.from({ length: 20_000 }, () => [999, false])],
            heads: [[Number.NaN, 0], "bad"],
            directions: ["teleport"],
            alive: "yes",
            crashes: [{ seat: 8, at: [0, 0] }],
            tick: "forever",
          }}
        />,
      ),
    ).not.toThrow();

    expect(screen.getByLabelText("41 by 31 Light Cycles arena")).not.toBeNull();
  });
});
