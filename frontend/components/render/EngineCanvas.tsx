"use client";

import type { RenderData } from "@/lib/types";
import { hasRenderer, RENDERERS } from "./index";
import GenericRenderer from "./GenericRenderer";

/**
 * Draw the authoritative canvas for a match — reads the observation's `render`
 * keys. Unknown games fall back to a generic JSON listing so any game remains
 * observable. The match page renders <ActionPanel> alongside for control.
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

  return <GenericRenderer render={render} />;
}
