"use client";

import { useEffect, useRef } from "react";
import type { RenderConnectFour } from "@/lib/types";

const COLS = 7;
const ROWS = 6;
const CELL = 64;
const RADIUS = CELL * 0.38;
const PAD = 12;

/** Connect Four board — renders the 6x7 grid of "" | "0" | "1". */
export default function ConnectFourRenderer({ render }: { render: RenderConnectFour }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = COLS * CELL + PAD * 2;
    const H = ROWS * CELL + PAD * 2;
    canvas.width = W;
    canvas.height = H;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, W, H);

    // board frame
    ctx.fillStyle = "#1b2030";
    ctx.fillRect(PAD - 6, PAD - 6, COLS * CELL + 12, ROWS * CELL + 12);

    for (let r = 0; r < ROWS; r++) {
      for (let c = 0; c < COLS; c++) {
        const x = PAD + c * CELL + CELL / 2;
        const y = PAD + r * CELL + CELL / 2;
        const cell = render.board?.[r]?.[c] ?? "";
        if (cell === "0") {
          ctx.fillStyle = "#ff5470";
          ctx.shadowColor = "#ff5470";
        } else if (cell === "1") {
          ctx.fillStyle = "#ffb547";
          ctx.shadowColor = "#ffb547";
        } else {
          ctx.fillStyle = "#141824";
          ctx.shadowColor = "transparent";
        }
        ctx.shadowBlur = cell ? 14 : 0;
        ctx.beginPath();
        ctx.arc(x, y, RADIUS, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.strokeStyle = "#252c40";
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    // column labels
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "12px ui-monospace, monospace";
    ctx.textAlign = "center";
    for (let c = 0; c < COLS; c++) {
      ctx.fillText(String(c), PAD + c * CELL + CELL / 2, H - 4);
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
