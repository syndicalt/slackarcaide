"use client";

import { useEffect, useRef } from "react";
import type { RenderAsteroids } from "@/lib/types";

const SCALE = 0.8;

/** Asteroids — ship, bullets, asteroids in the logical w x h playfield. */
export default function AsteroidsRenderer({ render }: { render: RenderAsteroids }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = (render.w || 800) * SCALE;
    const H = (render.h || 600) * SCALE;
    const s = (v: number) => v * SCALE;

    canvas.width = W;
    canvas.height = H;

    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, W, H);

    // asteroids
    for (const a of render.asteroids ?? []) {
      ctx.strokeStyle = "#9aa4bd";
      ctx.lineWidth = 2;
      ctx.shadowColor = "#9aa4bd";
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.arc(s(a.x), s(a.y), s(a.r), 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = "#141824";
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    // bullets
    ctx.fillStyle = "#ffb547";
    ctx.shadowColor = "#ffb547";
    ctx.shadowBlur = 8;
    for (const b of render.bullets ?? []) {
      ctx.beginPath();
      ctx.arc(s(b.x), s(b.y), 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    // ship (drawn as a triangle at heading angle)
    const ship = render.ship ?? { x: 0, y: 0, angle: 0, invuln: false };
    const sx = s(ship.x);
    const sy = s(ship.y);
    const ang = ship.angle || 0;
    if (ship.invuln) {
      ctx.globalAlpha = 0.45 + 0.3 * Math.sin(Date.now() / 80);
    }
    ctx.fillStyle = "#22ffd1";
    ctx.shadowColor = "#22ffd1";
    ctx.shadowBlur = 12;
    ctx.translate(sx, sy);
    ctx.rotate(ang);
    ctx.beginPath();
    ctx.moveTo(10, 0);
    ctx.lineTo(-8, -7);
    ctx.lineTo(-8, 7);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    // HUD
    ctx.fillStyle = "#9aa4bd";
    ctx.font = "13px ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.fillText(`SCORE ${render.score ?? 0}`, 8, 16);
    ctx.textAlign = "right";
    ctx.fillText(`LIVES ${render.lives ?? 0}`, W - 8, 16);
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
