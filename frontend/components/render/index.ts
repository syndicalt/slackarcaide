import type { ComponentType } from "react";
import Pong from "./Pong";
import Chess from "./Chess";
import Checkers from "./Checkers";
import ConnectFour from "./ConnectFour";
import Go from "./Go";
import Reversi from "./Reversi";
import Tetris from "./Tetris";
import Battleship from "./Battleship";
import Bomberman from "./Bomberman";
import Tron from "./Tron";
import UltimateTicTacToe from "./UltimateTicTacToe";

// Each renderer demands its own concrete render shape. The map widens the prop
// to `never` (safe via contravariance) and EngineCanvas casts once at the
// call site — the single bridge from unknown render data to a typed renderer.
export const RENDERERS: Record<string, ComponentType<{ render: never }>> = {
  pong: Pong,
  chess: Chess,
  chess960: Chess,
  connect_four: ConnectFour,
  reversi: Reversi,
  checkers: Checkers,
  go: Go,
  tron: Tron,
  ultimate_ttt: UltimateTicTacToe,
  battleship: Battleship,
  bomberman: Bomberman,
  tetris: Tetris,
};

export function hasRenderer(game: string): boolean {
  return Object.prototype.hasOwnProperty.call(RENDERERS, game);
}
