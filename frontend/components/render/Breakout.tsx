"use client";

import { useEffect, useRef } from "react";
import type { RenderBreakout } from "@/lib/types";

const CELL = 18;

/** Breakout — bricks [r,c,color], paddle, ball, lives/score overlay. */
export default function BreakoutRenderer({ render }: { render: RenderBreakout }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = render.w || 20;
    const h = render.h || 20;
    const bricks = render.bricks ?? [];
    const paddle = render.paddle ?? { x: 0, w: 3 };
    const ball = render.ball ?? { x: 0, y: 0, dx: 0, dy: 0 };
    const brickW = CELL;
    const brickH = CELL * 0.6;

    canvas.width = w * CELL;
    canvas.height = h * CELL;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // bricks
    for (const [r, c, color] of bricks) {
      ctx.fillStyle = color || "#7c7cff";
      ctx.shadowColor = color || "#7c7cff";
      ctx.shadowBlur = 6;
      const x = c * CELL + 1;
      const y = r * brickH + 1;
      ctx.fillRect(x, y, brickW - 2, brickH - 2);
      ctx.shadowBlur = 0;
    }

    // paddle
    ctx.fillStyle = "#22ffd1";
    ctx.shadowColor = "#22ffd1";
    ctx.shadowBlur = 10;
    ctx.fillRect(paddle.x * CELL, (h - 2) * CELL, Math.max(2, paddle.w * CELL), CELL * 0.7);
    ctx.shadowBlur = 0;

    // ball
    ctx.fillStyle = "#e7e9ee";
    ctx.shadowColor = "#ffffff";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(ball.x * CELL, ball.y * CELL, CELL * 0.35, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // HUD
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "12px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText(`SCORE ${render.score ?? 0}`, 6, 12);
    ctx.textAlign = "right";
    ctx.fillText(`LIVES ${render.lives ?? 0}`, canvas.width - 6, 12);
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
