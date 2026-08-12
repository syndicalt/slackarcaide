"use client";

import { useEffect, useRef } from "react";

const SIZE = 8;
const CELL = 52;

type ReversiRender = {
  board?: unknown;
  last_move?: unknown;
};

function boardFrom(value: unknown): (0 | 1 | null)[][] {
  if (!Array.isArray(value)) {
    return Array.from({ length: SIZE }, () =>
      Array<0 | 1 | null>(SIZE).fill(null),
    );
  }
  return Array.from({ length: SIZE }, (_, row) => {
    const source = Array.isArray(value[row]) ? value[row] : [];
    return Array.from({ length: SIZE }, (_, column) => {
      const disk = source[column];
      return disk === 0 || disk === 1 ? disk : null;
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
    row >= SIZE ||
    typeof column !== "number" ||
    !Number.isInteger(column) ||
    column < 0 ||
    column >= SIZE
  ) {
    return null;
  }
  return { row, column };
}

/** Standard Reversi board; partial or malformed spectator rows remain safe. */
export default function ReversiRenderer({ render }: { render: ReversiRender }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const board = boardFrom(render.board);
    const last = lastPosition(render.last_move);
    canvas.width = SIZE * CELL;
    canvas.height = SIZE * CELL;

    for (let row = 0; row < SIZE; row++) {
      for (let column = 0; column < SIZE; column++) {
        ctx.fillStyle = (row + column) % 2 === 0 ? "#12322e" : "#163b35";
        ctx.fillRect(column * CELL, row * CELL, CELL, CELL);
        ctx.strokeStyle = "#28544c";
        ctx.lineWidth = 1;
        ctx.strokeRect(column * CELL, row * CELL, CELL, CELL);

        const disk = board[row][column];
        if (disk === null) continue;
        ctx.beginPath();
        ctx.arc(
          column * CELL + CELL / 2,
          row * CELL + CELL / 2,
          CELL * 0.36,
          0,
          Math.PI * 2,
        );
        ctx.fillStyle = disk === 0 ? "#090c12" : "#e7e9ee";
        ctx.shadowColor =
          disk === 0 ? "rgba(0,0,0,0.8)" : "rgba(255,255,255,0.35)";
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = disk === 0 ? "#455064" : "#ffffff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }

    if (last) {
      ctx.beginPath();
      ctx.arc(
        last.column * CELL + CELL / 2,
        last.row * CELL + CELL / 2,
        CELL * 0.42,
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
