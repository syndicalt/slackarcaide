"use client";

import { useEffect, useRef } from "react";
import type { RenderSnake } from "@/lib/types";

const PALETTE = ["#ff5470", "#22ffd1", "#7c7cff", "#ffb547"];
const CELL = 18;

/** Snake — grid of snakes (segments) + food. */
export default function SnakeRenderer({ render }: { render: RenderSnake }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = render.w || 32;
    const h = render.h || 32;
    const snakes = render.snakes ?? [];
    const food = render.food ?? null;

    canvas.width = w * CELL;
    canvas.height = h * CELL;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // faint grid
    ctx.strokeStyle = "rgba(37,44,64,0.5)";
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

    // food
    if (food) {
      const [fr, fc] = food;
      ctx.fillStyle = "#ffb547";
      ctx.shadowColor = "#ffb547";
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc((fc + 0.5) * CELL, (fr + 0.5) * CELL, CELL * 0.3, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    // snakes
    for (const snake of snakes) {
      const color = PALETTE[snake.seat % PALETTE.length];
      for (let i = 0; i < snake.segments.length; i++) {
        const [sr, sc] = snake.segments[i];
        const x = sc * CELL;
        const y = sr * CELL;
        if (!snake.alive && i > 0) {
          ctx.fillStyle = "#2a2e3d";
          ctx.shadowBlur = 0;
        } else {
          ctx.fillStyle = color;
          ctx.shadowColor = color;
          ctx.shadowBlur = i === 0 ? 14 : 6;
        }
        const pad = i === 0 ? 1 : 2.5;
        ctx.fillRect(x + pad, y + pad, CELL - pad * 2, CELL - pad * 2);
        ctx.shadowBlur = 0;
      }
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
