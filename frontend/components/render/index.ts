import type { ComponentType } from "react";
import type { RenderData } from "@/lib/types";
import ConnectFour from "./ConnectFour";
import Pong from "./Pong";
import Snake from "./Snake";
import Breakout from "./Breakout";
import Tetris from "./Tetris";
import Asteroids from "./Asteroids";
import Chess from "./Chess";
import Checkers from "./Checkers";
import Go from "./Go";

// Each renderer demands its own concrete render shape. The map widens the prop
// to `never` (safe via contravariance) and EngineCanvas casts once at the
// call site — the single bridge from unknown render data to a typed renderer.
export const RENDERERS: Record<
  string,
  ComponentType<{ render: never }>
> = {
  connect_four: ConnectFour,
  pong: Pong,
  snake: Snake,
  breakout: Breakout,
  tetris: Tetris,
  asteroids: Asteroids,
  chess: Chess,
  checkers: Checkers,
  go: Go,
};

export function hasRenderer(game: string): boolean {
  return Object.prototype.hasOwnProperty.call(RENDERERS, game);
}
