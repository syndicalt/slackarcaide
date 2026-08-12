"use client";

import { useEffect, useRef } from "react";

type CheckersPiece = {
  square?: unknown;
  seat?: unknown;
  king?: unknown;
  captured?: unknown;
};

type RenderCheckers = {
  pieces?: unknown;
  forced_from?: unknown;
  last_move?: unknown;
};

const CELL = 44;
const SIZE = 8;

function boardCoordinates(square: unknown) {
  if (typeof square !== "string" || !/^[a-h][1-8]$/.test(square)) {
    return null;
  }
  return {
    column: square.charCodeAt(0) - 97,
    row: SIZE - Number(square[1]),
  };
}

/** English draughts board from Black's view, with Black advancing upward. */
export default function CheckersRenderer({
  render,
}: {
  render: RenderCheckers;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.width = SIZE * CELL;
    canvas.height = SIZE * CELL;

    for (let row = 0; row < SIZE; row++) {
      for (let column = 0; column < SIZE; column++) {
        const dark = (row + column) % 2 === 1;
        ctx.fillStyle = dark ? "#0d1018" : "#1b2030";
        ctx.fillRect(column * CELL, row * CELL, CELL, CELL);
      }
    }

    const lastMove =
      render.last_move && typeof render.last_move === "object"
        ? (render.last_move as { from?: unknown; to?: unknown })
        : null;
    for (const square of [lastMove?.from, lastMove?.to, render.forced_from]) {
      const position = boardCoordinates(square);
      if (!position) continue;
      ctx.fillStyle = "rgba(124,124,255,0.28)";
      ctx.fillRect(position.column * CELL, position.row * CELL, CELL, CELL);
    }

    const pieces: CheckersPiece[] = Array.isArray(render.pieces)
      ? render.pieces
      : [];
    for (const piece of pieces) {
      const position = boardCoordinates(piece?.square);
      if (!position || (piece.seat !== 0 && piece.seat !== 1)) continue;

      const x = position.column * CELL + CELL / 2;
      const y = position.row * CELL + CELL / 2;
      const radius = CELL * 0.36;
      ctx.save();
      ctx.globalAlpha = piece.captured === true ? 0.28 : 1;
      ctx.shadowColor = piece.seat === 0 ? "#ff5470" : "#22ffd1";
      ctx.shadowBlur = 9;
      ctx.fillStyle = piece.seat === 0 ? "#c73553" : "#12bfa2";
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.strokeStyle = piece.seat === 0 ? "#ff8296" : "#74ffe4";
      ctx.lineWidth = 2;
      ctx.stroke();

      if (piece.king === true) {
        ctx.strokeStyle = "#f4d77d";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(x, y, radius * 0.56, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#f4d77d";
        ctx.font = `bold ${CELL * 0.32}px ui-monospace, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("K", x, y + 1);
      }
      ctx.restore();
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge"
    />
  );
}
