"use client";

import { useEffect, useRef } from "react";
import type { RenderPong } from "@/lib/types";

/**
 * Pong — logical field w x h, paddles, ball, centre line, scores.
 *
 * Geometry contract with backend/app/engine/games/pong.py:
 *  - paddles[i] is the paddle's TOP-EDGE y (not its center);
 *  - paddle rects sit at x=0 (seat 0) and x=w-paddle_w (seat 1);
 *  - ball.x/ball.y is the ball CENTER with radius ball.r.
 * Draw exactly those rects or ball/paddle contact won't line up visually.
 */
export default function PongRenderer({ render }: { render: RenderPong }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = render.w || 800;
    const H = render.h || 500;
    const PW = render.paddle_w ?? 14;
    const PH = render.paddle_h ?? 90;
    const paddles = render.paddles ?? [(H - PH) / 2, (H - PH) / 2];
    const ball = render.ball ?? { x: W / 2, y: H / 2, r: 6 };
    const scores = render.scores ?? [0, 0];
    const serveIn = render.serve_in ?? 0;

    canvas.width = W;
    canvas.height = H;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, W, H);

    // centre dashed line
    ctx.strokeStyle = "#252c40";
    ctx.lineWidth = 2;
    ctx.setLineDash([10, 12]);
    ctx.beginPath();
    ctx.moveTo(W / 2, 0);
    ctx.lineTo(W / 2, H);
    ctx.stroke();
    ctx.setLineDash([]);

    // paddles — backend rects: seat 0 at x=0, seat 1 at x=W-PW, y = top edge
    for (let i = 0; i < 2; i++) {
      const px = i === 0 ? 0 : W - PW;
      const py = paddles[i];
      ctx.fillStyle = i === 0 ? "#ff5470" : "#22ffd1";
      ctx.shadowColor = i === 0 ? "#ff5470" : "#22ffd1";
      ctx.shadowBlur = 12;
      ctx.fillRect(px, py, PW, PH);
      ctx.shadowBlur = 0;
    }

    // ball
    ctx.fillStyle = "#e7e9ee";
    ctx.shadowColor = "#ffffff";
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.arc(ball.x, ball.y, ball.r ?? 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;

    // scores
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "bold 44px ui-monospace, monospace";
    ctx.textAlign = "center";
    ctx.fillText(String(scores[0]), W * 0.25, 60);
    ctx.fillText(String(scores[1]), W * 0.75, 60);

    // serve countdown overlay (ball is parked at center while serve_in > 0)
    if (serveIn > 0) {
      ctx.fillStyle = "#e7c46b";
      ctx.font = "bold 28px ui-monospace, monospace";
      ctx.fillText(String(Math.ceil(serveIn / 30)), W / 2, H / 2 - 30);
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
