"use client";

import { useEffect, useRef } from "react";

const ROWS = 6;
const COLUMNS = 7;
const CELL = 60;

type ConnectFourRender = {
  board?: unknown;
  last_move?: unknown;
};

function boardFrom(value: unknown): (0 | 1 | null)[][] {
  if (!Array.isArray(value)) {
    return Array.from({ length: ROWS }, () =>
      Array<0 | 1 | null>(COLUMNS).fill(null),
    );
  }
  return Array.from({ length: ROWS }, (_, row) => {
    const source = Array.isArray(value[row]) ? value[row] : [];
    return Array.from({ length: COLUMNS }, (_, column) => {
      const token = source[column];
      return token === 0 || token === 1 ? token : null;
    });
  });
}

function lastPosition(value: unknown): { row: number; column: number } | null {
  if (typeof value !== "object" || value === null) return null;
  const move = value as Record<string, unknown>;
  const row = move.row;
  const column = move.column;
  if (
    typeof row !== "number" ||
    !Number.isInteger(row) ||
    row < 0 ||
    row >= ROWS ||
    typeof column !== "number" ||
    !Number.isInteger(column) ||
    column < 0 ||
    column >= COLUMNS
  ) {
    return null;
  }
  return { row, column };
}

/** Fixed-size Connect Four board; malformed spectator cells render empty. */
export default function ConnectFourRenderer({
  render,
}: {
  render: ConnectFourRender;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const board = boardFrom(render.board);
    const last = lastPosition(render.last_move);
    canvas.width = COLUMNS * CELL;
    canvas.height = ROWS * CELL;

    ctx.fillStyle = "#10182b";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    for (let row = 0; row < ROWS; row++) {
      for (let column = 0; column < COLUMNS; column++) {
        const x = column * CELL + CELL / 2;
        const y = row * CELL + CELL / 2;
        ctx.beginPath();
        ctx.arc(x, y, CELL * 0.38, 0, Math.PI * 2);
        const token = board[row][column];
        ctx.fillStyle =
          token === 0 ? "#ff5470" : token === 1 ? "#22ffd1" : "#06080d";
        ctx.shadowColor =
          token === 0 ? "#ff5470" : token === 1 ? "#22ffd1" : "transparent";
        ctx.shadowBlur = token === null ? 0 : 10;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = "#252c40";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    if (last) {
      ctx.beginPath();
      ctx.arc(
        last.column * CELL + CELL / 2,
        last.row * CELL + CELL / 2,
        CELL * 0.43,
        0,
        Math.PI * 2,
      );
      ctx.strokeStyle = "#e7c46b";
      ctx.lineWidth = 4;
      ctx.stroke();
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
