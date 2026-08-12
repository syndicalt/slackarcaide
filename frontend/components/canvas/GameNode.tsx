"use client";

import { useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import type { GameInfo, Match } from "@/lib/types";
import { useView, NODE_WIDTH, type Pos } from "./view";

/**
 * One neon accent per game, so each cabinet reads distinctly against the
 * arcade backdrop (palette mirrors the background art: cyan/magenta/yellow,
 * green/orange/red, violet/teal/gold).
 */
const ARCADE_ACCENT: Record<string, string> = {
  pong: "#00e5ff",
  connect_four: "#ffe600",
  snake: "#45ff6b",
  breakout: "#ff3b53",
  tetris: "#ff2ec4",
  asteroids: "#9b6bff",
  chess: "#ffd23f",
  checkers: "#ff9a2e",
  go: "#22ffd1",
};

type Props = {
  game: GameInfo;
  matches: Match[];
  /** world position passed in from the page so drags have a live starting point */
  pos: Pos;
  /** inferred — non-focus game: cabinet stays visible but is dimmed/inert */
  disabled?: boolean;
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
  disabled = false,
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
    if (disabled) return;
    e.stopPropagation();
    setDragging(true);
    dragRef.current = { sx: e.clientX, sy: e.clientY, start: { x: pos.x, y: pos.y } };
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
      className={`canvas-node${selected ? " selected" : ""}${disabled ? " disabled" : ""}`}
      style={
        {
          left: pos.x,
          top: pos.y,
          width: NODE_WIDTH,
          "--na": ARCADE_ACCENT[game.game] ?? "var(--arcade-cyan)",
        } as CSSProperties
      }
      onPointerDown={(e) => {
        if (disabled) return;
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
        players {game.players.min}–{game.players.max} ·{" "}
        {game.elo_ranked ? "ranked" : "casual"}
      </div>

      <div className="canvas-tables">
        {disabled ? (
          <div className="small muted">disabled</div>
        ) : filtered ? (
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
                      players {m.players.length} · mode {m.mode} · {m.id.slice(0, 8)}
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
