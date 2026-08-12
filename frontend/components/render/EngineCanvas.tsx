"use client";

import type { RenderData } from "@/lib/types";
import { hasRenderer, RENDERERS } from "./index";

/**
 * Draw the authoritative canvas for a match — reads the observation's `render`
 * keys. The browser UI is intentionally spectator-only.
 */
export default function EngineCanvas({
  game,
  render,
}: {
  game: string;
  render: RenderData | null;
}) {
  if (!render || Object.keys(render).length === 0) {
    return <div className="muted small p-2">Waiting for board state…</div>;
  }

  if (hasRenderer(game)) {
    const C = RENDERERS[game];
    return <C render={render as never} />;
  }

  return <div className="error small p-2">Unsupported game renderer.</div>;
}
