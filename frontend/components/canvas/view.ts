import { createContext, useContext } from "react";

/**
 * Shared constants + persistence for the Excalidraw-like canvas lobby.
 * Positions are "world" coordinates inside the transformed .canvas-layer.
 */

export type Pos = { x: number; y: number };
export type CanvasView = { x: number; y: number; scale: number };

export const NODE_WIDTH = 360;
export const NODE_GAP_X = 410; // horizontal pitch between node origins
export const NODE_GAP_Y = 400; // vertical pitch
export const GRID_COLS = 3;
export const MIN_SCALE = 0.3;
export const MAX_SCALE = 3;

const STORAGE_KEY = "slackarcade.canvas.layout.v1";

/**
 * Deterministic 3x3 grid for an ordered list of game keys. Deterministic so the
 * server render and first client render agree (hydration-safe) — persisted
 * positions are layered on top only after mount.
 */
export function layoutGames(keys: string[]): Record<string, Pos> {
  const out: Record<string, Pos> = {};
  keys.forEach((k, i) => {
    const col = i % GRID_COLS;
    const row = Math.floor(i / GRID_COLS);
    out[k] = { x: 60 + col * NODE_GAP_X, y: 120 + row * NODE_GAP_Y };
  });
  return out;
}

const CANONICAL_KEYS = [
  "pong",
  "chess",
  "chess960",
  "connect_four",
  "reversi",
  "checkers",
  "go",
  "tron",
  "ultimate_ttt",
  "battleship",
  "bomberman",
  "tetris",
  "last_server",
];

export const DEFAULT_LAYOUT: Record<string, Pos> = layoutGames(CANONICAL_KEYS);

/** Extent of the default grid (world px) — used to pick the start camera. */
export const LAYOUT_MIN_X = Math.min(
  ...Object.values(DEFAULT_LAYOUT).map((p) => p.x),
);
export const LAYOUT_MIN_Y = Math.min(
  ...Object.values(DEFAULT_LAYOUT).map((p) => p.y),
);
export const LAYOUT_CENTER_Y = (() => {
  const ys = Object.values(DEFAULT_LAYOUT).map((p) => p.y);
  return (Math.min(...ys) + Math.max(...ys)) / 2;
})();

/**
 * Nudge the start camera far enough right that the first grid column clears the
 * left-hand catalog menu (panel ~244px wide) instead of sitting underneath it.
 */
export const VIEW_LEFT_GAP = 340;

export function loadLayout(): Record<string, Pos> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, Pos] =>
          entry[1] !== null &&
          typeof entry[1] === "object" &&
          "x" in entry[1] &&
          "y" in entry[1] &&
          typeof entry[1].x === "number" &&
          Number.isFinite(entry[1].x) &&
          typeof entry[1].y === "number" &&
          Number.isFinite(entry[1].y),
      ),
    );
  } catch {
    return {};
  }
}

export function saveLayout(layout: Record<string, Pos>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    /* storage unavailable — ignore */
  }
}

export function clampScale(n: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, n));
}

/**
 * Canvas camera state, provided by CanvasStage. Consumers read `scale` to
 * convert pointer deltas (screen px) into world px during node drag.
 */
export const ViewContext = createContext<{ scale: number }>({ scale: 1 });

export function useView(): { scale: number } {
  return useContext(ViewContext);
}
