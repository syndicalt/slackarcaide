"use client";

import { useEffect, useRef } from "react";
import type { RenderChess } from "@/lib/types";

const CELL = 44;
const GLYPHS: Record<string, string> = {
  K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
  k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟",
};

function fenRows(fen: string): string[][] {
  const placement = fen.split(" ")[0] || "";
  const rows: string[][] = [];
  for (const rank of placement.split("/")) {
    const row: string[] = [];
    for (const ch of rank) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < Number(ch); i++) row.push(".");
      } else {
        row.push(ch);
      }
    }
    rows.push(row);
  }
  return rows; // index 0 = rank 8 (top)
}

/** Chess — FEN board drawn from White's view (rank 8 at top). */
export default function ChessRenderer({ render }: { render: RenderChess }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rows = fenRows(render.fen || "8/8/8/8/8/8/8/8 w - - 0 1");
    const SIZE = 8;
    canvas.width = SIZE * CELL;
    canvas.height = SIZE * CELL;

    // squares
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        const light = (r + c) % 2 === 0;
        ctx.fillStyle = light ? "#1b2030" : "#0d1018";
        ctx.fillRect(c * CELL, r * CELL, CELL, CELL);
      }
    }

    // pieces
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let r = 0; r < SIZE; r++) {
      for (let c = 0; c < SIZE; c++) {
        const ch = rows[r]?.[c];
        if (!ch || ch === ".") continue;
        const glyph = GLYPHS[ch];
        if (!glyph) continue;
        // lower-case = black
        const isBlack = ch === ch.toLowerCase() && ch >= "a" && ch <= "z";
        ctx.font = `${CELL * 0.72}px "Segoe UI Symbol", "Noto Sans Symbols 2", sans-serif`;
        ctx.fillStyle = isBlack ? "#0b0e14" : "#e7e9ee";
        if (isBlack) {
          // subtle black stroke so dark glyph reads on dark squares
          ctx.strokeStyle = "rgba(231,233,238,0.25)";
          ctx.lineWidth = 1.5;
          ctx.strokeText(glyph, c * CELL + CELL / 2, r * CELL + CELL / 2 + 2);
        } else {
          ctx.strokeStyle = "rgba(0,0,0,0.3)";
          ctx.lineWidth = 1;
        }
        ctx.fillText(glyph, c * CELL + CELL / 2, r * CELL + CELL / 2 + 2);
      }
    }

    // last-move highlight (from/to if present)
    const lm = render.last_move as { from?: string; to?: string } | null | undefined;
    const toRect = (sq: string) => {
      if (!sq || sq.length < 2) return null;
      const file = sq.charCodeAt(0) - 97;
      const rank = 8 - Number(sq[1]);
      return { r: rank, c: file };
    };
    for (const sq of [lm?.from, lm?.to]) {
      const rc = toRect(sq || "");
      if (!rc || rc.r < 0 || rc.r >= SIZE || rc.c < 0 || rc.c >= SIZE) continue;
      ctx.fillStyle = "rgba(124,124,255,0.28)";
      ctx.fillRect(rc.c * CELL, rc.r * CELL, CELL, CELL);
    }
  }, [render]);

  return (
    <canvas
      ref={ref}
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge"
    />
  );
}
