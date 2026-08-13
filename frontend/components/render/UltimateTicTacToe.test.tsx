import {
  cleanup,
  render as renderComponent,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UltimateTicTacToeRenderer from "./UltimateTicTacToe";

const context = {
  setTransform: vi.fn(),
  fillRect: vi.fn(),
  strokeRect: vi.fn(),
  beginPath: vi.fn(),
  moveTo: vi.fn(),
  lineTo: vi.fn(),
  stroke: vi.fn(),
  arc: vi.fn(),
  save: vi.fn(),
  fillText: vi.fn(),
  restore: vi.fn(),
  fillStyle: "",
  strokeStyle: "",
  lineWidth: 0,
  lineCap: "butt",
  shadowColor: "",
  shadowBlur: 0,
  globalAlpha: 1,
  font: "",
  textAlign: "start",
  textBaseline: "alphabetic",
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("UltimateTicTacToeRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      context as unknown as CanvasRenderingContext2D,
    );
  });

  it("announces the forced local board and highlights the last placement", async () => {
    renderComponent(
      <UltimateTicTacToeRenderer
        render={{
          board: Array.from({ length: 9 }, (_, row) =>
            Array.from({ length: 9 }, (_, column) =>
              row === 4 && column === 4 ? 0 : null,
            ),
          ),
          local_results: Array.from({ length: 3 }, () => [null, null, null]),
          active_board: [1, 1],
          turn: 1,
          last_move: { row: 4, column: 4 },
          result: { terminal: false, winner: null },
        }}
      />,
    );

    expect(
      screen.getByText("Player 2 to move · Local board 2, 2"),
    ).not.toBeNull();
    expect(
      screen.getByLabelText(
        "Ultimate Tic-Tac-Toe board. Player 2 to move · Local board 2, 2",
      ),
    ).not.toBeNull();
    await waitFor(() => expect(context.strokeRect).toHaveBeenCalled());
  });

  it("makes local winners, local draws, and the global result explicit", async () => {
    renderComponent(
      <UltimateTicTacToeRenderer
        render={{
          board: [],
          local_results: [
            [0, 1, "draw"],
            [null, null, null],
            [null, null, null],
          ],
          result: { terminal: true, winner: [1], reason: "global line" },
        }}
      />,
    );

    expect(screen.getByText("Game over · Player 2 wins")).not.toBeNull();
    await waitFor(() => {
      expect(context.fillText).toHaveBeenCalledWith(
        "X",
        expect.any(Number),
        expect.any(Number),
      );
      expect(context.fillText).toHaveBeenCalledWith(
        "O",
        expect.any(Number),
        expect.any(Number),
      );
      expect(context.fillText).toHaveBeenCalledWith(
        "—",
        expect.any(Number),
        expect.any(Number),
      );
    });
  });

  it("degrades malformed and partial spectator payloads without inventing a winner", async () => {
    renderComponent(
      <UltimateTicTacToeRenderer
        render={{
          board: ["bad", [0, 1, {}, null]],
          local_results: { unexpected: true },
          active_board: [99, false],
          turn: "zero",
          last_move: { row: Number.NaN, column: 2 },
          result: { terminal: true, winner: [99] },
        }}
      />,
    );

    expect(screen.getByText("Game over")).not.toBeNull();
    expect(
      screen.getByLabelText("Ultimate Tic-Tac-Toe board. Game over"),
    ).not.toBeNull();
    await waitFor(() => expect(context.setTransform).toHaveBeenCalled());
  });
});
