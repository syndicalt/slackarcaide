"use client";

import { useEffect, useRef } from "react";

const BOARD_SIZE = 9;
const CELL = 42;
const PADDING = 28;
const LOGICAL_SIZE = PADDING * 2 + CELL * (BOARD_SIZE - 1);

type Stone = "black" | "white";

type GoRender = {
  size?: unknown;
  board?: unknown;
  turn?: unknown;
  last_move?: unknown;
  captures?: unknown;
};

function stoneAt(board: unknown, row: number, column: number): Stone | null {
  if (!Array.isArray(board) || !Array.isArray(board[row])) return null;
  const value: unknown = board[row][column];
  if (value === "black" || value === "B" || value === 1) return "black";
  if (value === "white" || value === "W" || value === 2) return "white";
  return null;
}

function lastPlacement(value: unknown): { row: number; column: number } | null {
  if (!value || typeof value !== "object") return null;
  const row = Reflect.get(value, "row");
  const column = Reflect.get(value, "column");
  if (
    !Number.isInteger(row) ||
    !Number.isInteger(column) ||
    (row as number) < 0 ||
    (row as number) >= BOARD_SIZE ||
    (column as number) < 0 ||
    (column as number) >= BOARD_SIZE
  ) {
    return null;
  }
  return { row: row as number, column: column as number };
}

/** Fixed 9x9 Go board; malformed or partial frames degrade to an empty board. */
export default function GoRenderer({ render }: { render: GoRender }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(LOGICAL_SIZE * pixelRatio);
    canvas.height = Math.round(LOGICAL_SIZE * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const boardGradient = context.createLinearGradient(
      0,
      0,
      LOGICAL_SIZE,
      LOGICAL_SIZE,
    );
    boardGradient.addColorStop(0, "#d4a95f");
    boardGradient.addColorStop(1, "#a87532");
    context.fillStyle = boardGradient;
    context.fillRect(0, 0, LOGICAL_SIZE, LOGICAL_SIZE);

    context.strokeStyle = "rgba(31, 20, 10, 0.82)";
    context.lineWidth = 1.25;
    for (let index = 0; index < BOARD_SIZE; index++) {
      const coordinate = PADDING + index * CELL;
      context.beginPath();
      context.moveTo(PADDING, coordinate);
      context.lineTo(LOGICAL_SIZE - PADDING, coordinate);
      context.stroke();
      context.beginPath();
      context.moveTo(coordinate, PADDING);
      context.lineTo(coordinate, LOGICAL_SIZE - PADDING);
      context.stroke();
    }

    context.fillStyle = "rgba(31, 20, 10, 0.88)";
    for (const [row, column] of [
      [2, 2],
      [2, 6],
      [4, 4],
      [6, 2],
      [6, 6],
    ]) {
      context.beginPath();
      context.arc(
        PADDING + column * CELL,
        PADDING + row * CELL,
        3.2,
        0,
        Math.PI * 2,
      );
      context.fill();
    }

    for (let row = 0; row < BOARD_SIZE; row++) {
      for (let column = 0; column < BOARD_SIZE; column++) {
        const stone = stoneAt(render?.board, row, column);
        if (!stone) continue;
        const x = PADDING + column * CELL;
        const y = PADDING + row * CELL;
        const radius = CELL * 0.43;
        const stoneGradient = context.createRadialGradient(
          x - radius * 0.35,
          y - radius * 0.38,
          radius * 0.12,
          x,
          y,
          radius,
        );
        if (stone === "black") {
          stoneGradient.addColorStop(0, "#626672");
          stoneGradient.addColorStop(0.38, "#252832");
          stoneGradient.addColorStop(1, "#080a0f");
        } else {
          stoneGradient.addColorStop(0, "#ffffff");
          stoneGradient.addColorStop(0.55, "#e8e9ed");
          stoneGradient.addColorStop(1, "#aeb2bc");
        }
        context.shadowColor = "rgba(0, 0, 0, 0.38)";
        context.shadowBlur = 4;
        context.shadowOffsetY = 2;
        context.fillStyle = stoneGradient;
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fill();
        context.shadowColor = "transparent";
      }
    }

    const lastMove = lastPlacement(render?.last_move);
    if (lastMove) {
      const x = PADDING + lastMove.column * CELL;
      const y = PADDING + lastMove.row * CELL;
      context.strokeStyle = "#7c7cff";
      context.lineWidth = 2.5;
      context.beginPath();
      context.arc(x, y, CELL * 0.14, 0, Math.PI * 2);
      context.stroke();
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      aria-label="9 by 9 Go board"
      className="h-auto w-full max-h-[80vh] rounded-lg border border-edge"
      style={{ aspectRatio: "1 / 1" }}
    />
  );
}
