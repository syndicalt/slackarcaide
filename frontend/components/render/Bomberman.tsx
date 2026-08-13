"use client";

import { useEffect, useRef } from "react";

const DEFAULT_WIDTH = 13;
const DEFAULT_HEIGHT = 11;
const MIN_DIMENSION = 9;
const MAX_DIMENSION = 25;
const PLAYER_COLORS = ["#ff5470", "#22ffd1"] as const;

type Point = [number, number];
type Player = {
  seat: 0 | 1;
  position: Point;
  alive: boolean;
  capacity: number;
  blastRange: number;
  activeBombs: number;
};
type Bomb = { position: Point; owner: 0 | 1; fuse: number };
type Flame = { position: Point; remaining: number };
type Powerup = { position: Point; kind: "capacity" | "range" };

type BombermanRender = {
  width?: unknown;
  height?: unknown;
  solid_walls?: unknown;
  crates?: unknown;
  players?: unknown;
  bombs?: unknown;
  flames?: unknown;
  powerups?: unknown;
  tick?: unknown;
  max_ticks?: unknown;
};

function dimension(value: unknown, fallback: number): number {
  return Number.isInteger(value) &&
    (value as number) >= MIN_DIMENSION &&
    (value as number) <= MAX_DIMENSION
    ? (value as number)
    : fallback;
}

function boundedInteger(
  value: unknown,
  minimum: number,
  maximum: number,
): number {
  return Number.isInteger(value) &&
    (value as number) >= minimum &&
    (value as number) <= maximum
    ? (value as number)
    : minimum;
}

function point(value: unknown, width: number, height: number): Point | null {
  if (!Array.isArray(value) || value.length < 2) return null;
  const [column, row] = value;
  if (
    !Number.isInteger(column) ||
    !Number.isInteger(row) ||
    column < 0 ||
    column >= width ||
    row < 0 ||
    row >= height
  ) {
    return null;
  }
  return [column, row];
}

function object(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function points(value: unknown, width: number, height: number): Point[] {
  if (!Array.isArray(value)) return [];
  const parsed: Point[] = [];
  for (const candidate of value.slice(0, width * height)) {
    const cell = point(candidate, width, height);
    if (cell) parsed.push(cell);
  }
  return parsed;
}

function players(value: unknown, width: number, height: number): Player[] {
  if (!Array.isArray(value)) return [];
  const parsed: Player[] = [];
  for (const candidate of value.slice(0, 2)) {
    const record = object(candidate);
    const position = point(record?.position, width, height);
    const seat = record?.seat;
    if (!position || (seat !== 0 && seat !== 1)) continue;
    parsed.push({
      seat,
      position,
      alive: record?.alive !== false,
      capacity: boundedInteger(record?.capacity, 0, 12),
      blastRange: boundedInteger(record?.blast_range, 0, 12),
      activeBombs: boundedInteger(record?.active_bombs, 0, 12),
    });
  }
  return parsed;
}

function bombs(value: unknown, width: number, height: number): Bomb[] {
  if (!Array.isArray(value)) return [];
  const parsed: Bomb[] = [];
  for (const candidate of value.slice(0, 24)) {
    const record = object(candidate);
    const position = point(record?.position, width, height);
    const owner = record?.owner;
    if (!position || (owner !== 0 && owner !== 1)) continue;
    parsed.push({
      position,
      owner,
      fuse: boundedInteger(record?.fuse, 0, 120),
    });
  }
  return parsed;
}

function flames(value: unknown, width: number, height: number): Flame[] {
  if (!Array.isArray(value)) return [];
  const parsed: Flame[] = [];
  for (const candidate of value.slice(0, width * height)) {
    const record = object(candidate);
    const position = point(record?.position, width, height);
    if (!position) continue;
    parsed.push({
      position,
      remaining: boundedInteger(record?.remaining, 1, 30),
    });
  }
  return parsed;
}

function powerups(value: unknown, width: number, height: number): Powerup[] {
  if (!Array.isArray(value)) return [];
  const parsed: Powerup[] = [];
  for (const candidate of value.slice(0, width * height)) {
    const record = object(candidate);
    const position = point(record?.position, width, height);
    const kind = record?.kind;
    if (!position || (kind !== "capacity" && kind !== "range")) continue;
    parsed.push({ position, kind });
  }
  return parsed;
}

function drawCell(
  context: CanvasRenderingContext2D,
  position: Point,
  cellSize: number,
  inset = 0,
) {
  context.fillRect(
    position[0] * cellSize + inset,
    position[1] * cellSize + inset,
    cellSize - inset * 2,
    cellSize - inset * 2,
  );
}

/** Responsive spectator arena with strict defensive parsing of replay frames. */
export default function BombermanRenderer({
  render,
}: {
  render: BombermanRender;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const width = dimension(render?.width, DEFAULT_WIDTH);
  const height = dimension(render?.height, DEFAULT_HEIGHT);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const cellSize = Math.max(20, Math.min(48, 900 / width, 680 / height));
    const hudHeight = Math.max(42, cellSize * 1.35);
    const boardWidth = width * cellSize;
    const boardHeight = height * cellSize;
    const logicalHeight = hudHeight + boardHeight;
    const pixelRatio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    canvas.width = Math.round(boardWidth * pixelRatio);
    canvas.height = Math.round(logicalHeight * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    context.fillStyle = "#05070c";
    context.fillRect(0, 0, boardWidth, logicalHeight);
    context.save();
    context.translate(0, hudHeight);

    context.fillStyle = "#0b1220";
    context.fillRect(0, 0, boardWidth, boardHeight);
    context.strokeStyle = "rgba(97, 120, 156, 0.16)";
    context.lineWidth = 1;
    for (let column = 0; column <= width; column++) {
      context.beginPath();
      context.moveTo(column * cellSize, 0);
      context.lineTo(column * cellSize, boardHeight);
      context.stroke();
    }
    for (let row = 0; row <= height; row++) {
      context.beginPath();
      context.moveTo(0, row * cellSize);
      context.lineTo(boardWidth, row * cellSize);
      context.stroke();
    }

    for (const wall of points(render?.solid_walls, width, height)) {
      context.fillStyle = "#27354c";
      drawCell(context, wall, cellSize, 1);
      context.fillStyle = "#3f5675";
      drawCell(context, wall, cellSize, cellSize * 0.14);
    }

    for (const crate of points(render?.crates, width, height)) {
      context.fillStyle = "#6d4028";
      drawCell(context, crate, cellSize, cellSize * 0.08);
      context.strokeStyle = "#d58b48";
      context.lineWidth = Math.max(1.5, cellSize * 0.06);
      const x = crate[0] * cellSize;
      const y = crate[1] * cellSize;
      context.beginPath();
      context.moveTo(x + cellSize * 0.2, y + cellSize * 0.2);
      context.lineTo(x + cellSize * 0.8, y + cellSize * 0.8);
      context.moveTo(x + cellSize * 0.8, y + cellSize * 0.2);
      context.lineTo(x + cellSize * 0.2, y + cellSize * 0.8);
      context.stroke();
    }

    for (const upgrade of powerups(render?.powerups, width, height)) {
      const x = (upgrade.position[0] + 0.5) * cellSize;
      const y = (upgrade.position[1] + 0.5) * cellSize;
      context.fillStyle = upgrade.kind === "capacity" ? "#a989ff" : "#5ee7ff";
      context.shadowColor = context.fillStyle;
      context.shadowBlur = cellSize * 0.6;
      context.beginPath();
      context.arc(x, y, cellSize * 0.28, 0, Math.PI * 2);
      context.fill();
      context.shadowBlur = 0;
      context.fillStyle = "#071019";
      context.font = `bold ${cellSize * 0.35}px ui-monospace, monospace`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(upgrade.kind === "capacity" ? "+B" : "+R", x, y);
    }

    for (const flame of flames(render?.flames, width, height)) {
      context.fillStyle = flame.remaining % 2 === 0 ? "#ff6b35" : "#ffd166";
      context.shadowColor = "#ff5a1f";
      context.shadowBlur = cellSize * 0.75;
      drawCell(context, flame.position, cellSize, cellSize * 0.09);
      context.shadowBlur = 0;
      context.fillStyle = "rgba(255,255,220,0.72)";
      drawCell(context, flame.position, cellSize, cellSize * 0.31);
    }

    for (const bomb of bombs(render?.bombs, width, height)) {
      const x = (bomb.position[0] + 0.5) * cellSize;
      const y = (bomb.position[1] + 0.54) * cellSize;
      context.fillStyle = "#070a10";
      context.strokeStyle = PLAYER_COLORS[bomb.owner];
      context.lineWidth = Math.max(2, cellSize * 0.07);
      context.shadowColor = PLAYER_COLORS[bomb.owner];
      context.shadowBlur = cellSize * 0.4;
      context.beginPath();
      context.arc(x, y, cellSize * 0.31, 0, Math.PI * 2);
      context.fill();
      context.stroke();
      context.shadowBlur = 0;
      context.fillStyle = "#f3d67b";
      context.font = `bold ${cellSize * 0.3}px ui-monospace, monospace`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(String(bomb.fuse), x, y);
    }

    const parsedPlayers = players(render?.players, width, height);
    for (const player of parsedPlayers) {
      const x = (player.position[0] + 0.5) * cellSize;
      const y = (player.position[1] + 0.5) * cellSize;
      const color = PLAYER_COLORS[player.seat];
      context.fillStyle = player.alive ? color : "#4d5260";
      context.strokeStyle = player.alive ? "#f8fbff" : "#9ba0ac";
      context.lineWidth = Math.max(2, cellSize * 0.08);
      context.shadowColor = color;
      context.shadowBlur = player.alive ? cellSize * 0.65 : 0;
      context.beginPath();
      context.arc(x, y, cellSize * 0.34, 0, Math.PI * 2);
      context.fill();
      context.stroke();
      context.shadowBlur = 0;
      context.fillStyle = "#071019";
      context.font = `bold ${cellSize * 0.38}px ui-monospace, monospace`;
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(String(player.seat + 1), x, y);
    }
    context.restore();

    const tick = boundedInteger(render?.tick, 0, 10_000);
    const maxTicks = boundedInteger(render?.max_ticks, 0, 10_000);
    context.font = `600 ${Math.max(11, cellSize * 0.34)}px ui-monospace, monospace`;
    context.textBaseline = "middle";
    for (const seat of [0, 1] as const) {
      const player = parsedPlayers.find((candidate) => candidate.seat === seat);
      const label = player
        ? `P${seat + 1}  B ${player.activeBombs}/${player.capacity}  R ${player.blastRange}${player.alive ? "" : "  OUT"}`
        : `P${seat + 1}`;
      context.fillStyle =
        player?.alive === false ? "#676f80" : PLAYER_COLORS[seat];
      context.textAlign = seat === 0 ? "left" : "right";
      context.fillText(label, seat === 0 ? 12 : boardWidth - 12, hudHeight / 2);
    }
    context.fillStyle = "#aab4c8";
    context.textAlign = "center";
    context.fillText(
      maxTicks > 0 ? `${tick}/${maxTicks}` : String(tick),
      boardWidth / 2,
      hudHeight / 2,
    );
  }, [height, render, width]);

  const parsedPlayers = players(render?.players, width, height);
  const alive = parsedPlayers.filter((player) => player.alive).length;
  const tick = boundedInteger(render?.tick, 0, 10_000);
  const playerLabel = alive === 1 ? "player" : "players";
  return (
    <canvas
      ref={ref}
      role="img"
      aria-label={`${width} by ${height} Bomberman arena at tick ${tick}, ${alive} ${playerLabel} alive`}
      className="h-auto w-full max-h-[80vh] rounded-lg border border-edge bg-[#05070c] object-contain"
      style={{ aspectRatio: `${width} / ${height + 1.35}` }}
    />
  );
}
