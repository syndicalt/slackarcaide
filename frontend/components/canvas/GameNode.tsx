"use client";

import { useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import type { GameInfo, Match } from "@/lib/types";
import { useView, NODE_WIDTH, type Pos } from "./view";

/** Neon accent for each production game. */
const ARCADE_ACCENT: Record<string, string> = {
  pong: "#00e5ff",
  chess: "#ffd23f",
  chess960: "#ff7ad9",
  connect_four: "#ff5470",
  reversi: "#22ffd1",
  checkers: "#ff9f43",
  go: "#c9974f",
  tron: "#39ff88",
  ultimate_ttt: "#9b6bff",
  battleship: "#4aa8ff",
  bomberman: "#ff3b53",
  tetris: "#ffe600",
  last_server: "#ff2f87",
};

type Props = {
  game: GameInfo;
  matches: Match[];
  /** world position passed in from the page so drags have a live starting point */
  pos: Pos;
  /** true when the catalog filter shows this game's table cards */
  filtered: boolean;
  selected: boolean;
  onSelect: () => void;
  onPositionChange: (pos: Pos) => void;
  onDragEnd: () => void;
};

export default function GameNode({
  game,
  matches,
  pos,
  filtered,
  selected,
  onSelect,
  onPositionChange,
  onDragEnd,
}: Props) {
  const { scale } = useView();
  const dragRef = useRef<{ sx: number; sy: number; start: Pos } | null>(null);
  const [dragging, setDragging] = useState(false);

  const onGripDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    setDragging(true);
    dragRef.current = {
      sx: e.clientX,
      sy: e.clientY,
      start: { x: pos.x, y: pos.y },
    };
    // Capture so pointerup/move continue to arrive at the grip while dragging.
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
  };

  const onGripMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    e.stopPropagation();
    // Screen deltas -> world deltas (canvas may be zoomed).
    const dx = (e.clientX - d.sx) / scale;
    const dy = (e.clientY - d.sy) / scale;
    onPositionChange({ x: d.start.x + dx, y: d.start.y + dy });
  };

  const onGripUp = (e: React.PointerEvent) => {
    const wasDragging = !!dragRef.current;
    dragRef.current = null;
    setDragging(false);
    e.stopPropagation();
    if (wasDragging) onDragEnd();
  };

  return (
    <div
      data-node
      className={`canvas-node${selected ? " selected" : ""}`}
      style={
        {
          left: pos.x,
          top: pos.y,
          width: NODE_WIDTH,
          "--na": ARCADE_ACCENT[game.game] ?? "var(--arcade-cyan)",
        } as CSSProperties
      }
      onPointerDown={(e) => {
        if ((e.target as HTMLElement).closest("a")) return;
        e.stopPropagation();
        onSelect();
      }}
    >
      <div
        className={`canvas-grip${dragging ? " dragging" : ""}`}
        onPointerDown={onGripDown}
        onPointerMove={onGripMove}
        onPointerUp={onGripUp}
        onPointerCancel={onGripUp}
      >
        <span className="canvas-name">{game.name}</span>
      </div>

      <p className="muted small canvas-blurb">{game.blurb}</p>

      <div className="small muted">
        players {game.players.min}–{game.players.max} · starts at{" "}
        {game.players_before_start} · {game.elo_ranked ? "ranked" : "casual"}
      </div>

      <div className="canvas-tables">
        {filtered ? (
          matches.length === 0 ? (
            <div className="small muted">No open tables</div>
          ) : (
            <ul className="list">
              {matches.map((m) => (
                <li key={m.id} className="canvas-table">
                  <div className="grow">
                    <div className="flex items-center gap-2">
                      <strong>{m.game_type}</strong>
                      <span className={`badge ${m.status}`}>{m.status}</span>
                    </div>
                    <div className="muted small mono">
                      players {m.players.length} · mode {m.mode} ·{" "}
                      {m.id.slice(0, 8)}
                    </div>
                  </div>
                  <Link href={`/match/${m.id}`} className="canvas-watch">
                    Watch
                  </Link>
                </li>
              ))}
            </ul>
          )
        ) : (
          <div className="small muted">
            {matches.length} open table{matches.length === 1 ? "" : "s"}
          </div>
        )}
      </div>
    </div>
  );
}
