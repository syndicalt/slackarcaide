"use client";

import { useEffect, useRef } from "react";
import type { RenderCheckers } from "@/lib/types";

const CELL = 52;

/** Checkers — board already rendered from Black's view (rank 8 on top). */
export default function CheckersRenderer({ render }: { render: RenderCheckers }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const board = render.board ?? [];
    const SIZE = 8;
    canvas.width = SIZE * CELL;
    canvas.height = SIZE * CELL;

    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        const light = (r + c) % 2 === 0;
        ctx.fillStyle = light ? "#1b2030" : "#0d1018";
        ctx.fillRect(c * CELL, r * CELL, CELL, CELL);
      }
    }

    const isBlack = (ch: string) => ch === "b" || ch === "B";
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        const cell = board[r]?.[c] ?? "";
        if (!cell) continue;
        const cx = c * CELL + CELL / 2;
        const cy = r * CELL + CELL / 2;
        const dark = isBlack(cell);
        ctx.fillStyle = dark ? "#0b0e14" : "#e7e9ee";
        ctx.strokeStyle = dark ? "#9aa4bd" : "#9aa4bd";
        ctx.lineWidth = 2;
        ctx.shadowColor = dark ? "#ff5470" : "#7c7cff";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(cx, cy, CELL * 0.34, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.shadowBlur = 0;
        // king crown
        if (cell === "B" || cell === "W") {
          ctx.fillStyle = "#ffb547";
          ctx.beginPath();
          ctx.arc(cx, cy, CELL * 0.14, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge"
    />
  );
}
