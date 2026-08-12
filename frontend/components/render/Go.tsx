"use client";

import { useEffect, useRef } from "react";
import type { RenderGo } from "@/lib/types";

const CELL = 34;
const PAD = 24;

/** Go — 19×19 board rendered from the engine's row-major grid. */
export default function GoRenderer({ render }: { render: RenderGo }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const board = render.board ?? [];
    const size = render.size || 19;
    const n = Math.max(board.length, size);
    canvas.width = PAD * 2 + (n - 1) * CELL;
    canvas.height = PAD * 2 + (n - 1) * CELL;

    const panel = { x0: PAD - CELL, y0: PAD - CELL, x1: canvas.width - PAD + CELL, y1: canvas.height - PAD + CELL };

    // wood board
    ctx.fillStyle = "#2a2118";
    ctx.fillRect(panel.x0, panel.y0, panel.x1 - panel.x0, panel.y1 - panel.y0);
    ctx.strokeStyle = "#c9a26b";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(panel.x0, panel.y0, panel.x1 - panel.x0, panel.y1 - panel.y0);

    // grid lines
    ctx.strokeStyle = "#b78d55";
    ctx.lineWidth = 1;
    for (let i = 0; i < n; i++) {
      const x = PAD + i * CELL;
      const y = PAD + i * CELL;
      ctx.beginPath();
      ctx.moveTo(PAD, y);
      ctx.lineTo(canvas.width - PAD, y);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x, PAD);
      ctx.lineTo(x, canvas.height - PAD);
      ctx.stroke();
    }

    // star points (hoshi) on 19x19: 3-3, 3-9, 3-15, 9-3, 9-9, 9-15, 15-3, 15-9, 15-15
    if (n === 19 || n === 13) {
      const pts = n === 19 ? [3, 9, 15] : [3, 9];
      ctx.fillStyle = "#b78d55";
      for (const py of pts) {
        for (const px of pts) {
          ctx.beginPath();
          ctx.arc(PAD + px * CELL, PAD + py * CELL, 4, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    const stone = (col: number, row: number, val: number) => {
      const x = PAD + col * CELL;
      const y = PAD + row * CELL;
      const black = val === 1;
      const grad = ctx.createRadialGradient(x - 5, y - 5, 2, x, y, CELL * 0.44);
      if (black) {
        grad.addColorStop(0, "#6b7078");
        grad.addColorStop(1, "#07090d");
      } else {
        grad.addColorStop(0, "#ffffff");
        grad.addColorStop(1, "#c3c9d4");
      }
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(x, y, CELL * 0.42, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = black ? "#000" : "#8f97a5";
      ctx.lineWidth = 1;
      ctx.stroke();
    };

    for (let r = 0; r < board.length; r++) {
      for (let c = 0; c < (board[r]?.length ?? 0); c++) {
        const v = board[r][c];
        if (v === 1 || v === 2) stone(c, r, v);
      }
    }

    // mark last move
    const last = render.last_move;
    if (last && typeof last === "object" && Number.isInteger(last.x)) {
      const x = PAD + last.x * CELL;
      const y = PAD + last.y * CELL;
      const black = render.turn === 1; // opponent just played
      ctx.fillStyle = black ? "#e8ecf3" : "#1a1c22";
      ctx.font = `${CELL * 0.28}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("×", x, y + 1);
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge"
    />
  );
}
