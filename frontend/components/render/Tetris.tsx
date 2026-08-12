"use client";

import { useEffect, useRef } from "react";
import type { RenderTetris } from "@/lib/types";

const CELL = 24;
const TYPE_COLORS: Record<string, string> = {
  I: "#22ffd1",
  O: "#ffb547",
  T: "#7c7cff",
  S: "#37ff6a",
  Z: "#ff5470",
  J: "#4aa8ff",
  L: "#ff8b4a",
};

/** Tetris — stacked board + falling current piece; next-piece preview box. */
export default function TetrisRenderer({ render }: { render: RenderTetris }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = render.w || 10;
    const h = render.h || 20;
    const board = render.board ?? [];
    const current = render.current ?? { type: "T", coords: [] };

    const PREVIEW = 6; // columns reserved on the right for the next-piece box
    canvas.width = (w + PREVIEW) * CELL;
    canvas.height = h * CELL;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // grid lines
    ctx.strokeStyle = "rgba(37,44,64,0.4)";
    ctx.lineWidth = 1;
    for (let c = 0; c <= w; c++) {
      ctx.beginPath();
      ctx.moveTo(c * CELL, 0);
      ctx.lineTo(c * CELL, h * CELL);
      ctx.stroke();
    }
    for (let r = 0; r <= h; r++) {
      ctx.beginPath();
      ctx.moveTo(0, r * CELL);
      ctx.lineTo(w * CELL, r * CELL);
      ctx.stroke();
    }

    // stacked board
    for (let r = 0; r < board.length; r++) {
      for (let c = 0; c < (board[r]?.length ?? 0); c++) {
        const v = board[r][c];
        if (v === null || v === undefined || v === 0) continue;
        const color = TYPE_COLORS[String(v)] ?? "#7c7cff";
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 4;
        ctx.fillRect(c * CELL + 1, r * CELL + 1, CELL - 2, CELL - 2);
        ctx.shadowBlur = 0;
      }
    }

    // current piece
    const curColor = TYPE_COLORS[current.type] ?? "#7c7cff";
    for (const [r, c] of current.coords ?? []) {
      if (r < 0 || r >= h || c < 0 || c >= w) continue;
      ctx.fillStyle = curColor;
      ctx.shadowColor = curColor;
      ctx.shadowBlur = 10;
      ctx.fillRect(c * CELL + 1, r * CELL + 1, CELL - 2, CELL - 2);
      ctx.shadowBlur = 0;
    }

    // next-piece preview box
    const px = (w + 1) * CELL;
    ctx.fillStyle = "#141824";
    ctx.fillRect(px, 0, PREVIEW * CELL - CELL, CELL * 4.5);
    ctx.strokeStyle = "#252c40";
    ctx.strokeRect(px, 0, PREVIEW * CELL - CELL, CELL * 4.5);
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "12px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText("NEXT", px + 6, 16);
    if (render.next) {
      ctx.fillStyle = TYPE_COLORS[render.next] ?? "#7c7cff";
      ctx.fillRect(px + CELL * 0.5, CELL * 1.2, CELL - 2, CELL - 2);
    }

    // HUD
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "12px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText(`SCORE ${render.score ?? 0}`, px, (h - 4) * CELL + 10);
    ctx.fillText(`LINES ${render.lines ?? 0}`, px, (h - 2) * CELL + 10);
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
