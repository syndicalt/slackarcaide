import type { ComponentType } from "react";
import Pong from "./Pong";
import Chess from "./Chess";

// Each renderer demands its own concrete render shape. The map widens the prop
// to `never` (safe via contravariance) and EngineCanvas casts once at the
// call site — the single bridge from unknown render data to a typed renderer.
export const RENDERERS: Record<string, ComponentType<{ render: never }>> = {
  pong: Pong,
  chess: Chess,
};

export function hasRenderer(game: string): boolean {
  return Object.prototype.hasOwnProperty.call(RENDERERS, game);
}
