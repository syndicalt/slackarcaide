"use client";

import { useEffect, useRef } from "react";

const DEFAULT_WIDTH = 41;
const DEFAULT_HEIGHT = 31;
const MIN_DIMENSION = 9;
const MAX_DIMENSION = 101;
const RIDER_COLORS = ["#ff5470", "#22ffd1"] as const;

type Point = [number, number];
type Direction = "north" | "east" | "south" | "west";

type TronRender = {
  width?: unknown;
  height?: unknown;
  trails?: unknown;
  heads?: unknown;
  directions?: unknown;
  alive?: unknown;
  crashes?: unknown;
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

function trail(value: unknown, width: number, height: number): Point[] {
  if (!Array.isArray(value)) return [];
  const cells: Point[] = [];
  for (const candidate of value.slice(0, width * height)) {
    const parsed = point(candidate, width, height);
    if (parsed) cells.push(parsed);
  }
  return cells;
}

function direction(value: unknown): Direction | null {
  return value === "north" ||
    value === "east" ||
    value === "south" ||
    value === "west"
    ? value
    : null;
}

function crashPoint(
  value: unknown,
  width: number,
  height: number,
): Point | null {
  if (!value || typeof value !== "object") return null;
  const attempted = Reflect.get(value, "at");
  if (!Array.isArray(attempted) || attempted.length < 2) return null;
  const [column, row] = attempted;
  if (!Number.isInteger(column) || !Number.isInteger(row)) return null;
  return [
    Math.max(0, Math.min(width - 1, column)),
    Math.max(0, Math.min(height - 1, row)),
  ];
}

function drawTrail(
  context: CanvasRenderingContext2D,
  cells: Point[],
  cellSize: number,
  color: string,
) {
  if (cells.length === 0) return;
  const center = ([column, row]: Point): Point => [
    (column + 0.5) * cellSize,
    (row + 0.5) * cellSize,
  ];
  const [startX, startY] = center(cells[0]);

  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = color;
  context.shadowColor = color;
  context.shadowBlur = cellSize * 0.75;
  context.lineWidth = cellSize * 0.7;
  context.beginPath();
  context.moveTo(startX, startY);
  for (const cell of cells.slice(1)) {
    const [x, y] = center(cell);
    context.lineTo(x, y);
  }
  if (cells.length === 1) {
    context.lineTo(startX + 0.01, startY);
  }
  context.stroke();

  context.shadowBlur = 0;
  context.globalAlpha = 0.8;
  context.strokeStyle = "#ffffff";
  context.lineWidth = Math.max(1, cellSize * 0.12);
  context.stroke();
  context.restore();
}

function drawHead(
  context: CanvasRenderingContext2D,
  head: Point,
  heading: Direction | null,
  cellSize: number,
  color: string,
  alive: boolean,
) {
  const x = (head[0] + 0.5) * cellSize;
  const y = (head[1] + 0.5) * cellSize;
  const radius = cellSize * 0.43;

  context.save();
  context.fillStyle = alive ? "#f8fbff" : "#596071";
  context.strokeStyle = color;
  context.lineWidth = Math.max(2, cellSize * 0.13);
  context.shadowColor = color;
  context.shadowBlur = cellSize;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.fill();
  context.stroke();

  const vector: Record<Direction, Point> = {
    north: [0, -1],
    east: [1, 0],
    south: [0, 1],
    west: [-1, 0],
  };
  if (heading) {
    const [dx, dy] = vector[heading];
    context.shadowBlur = 0;
    context.strokeStyle = "#070a11";
    context.lineWidth = Math.max(2, cellSize * 0.14);
    context.lineCap = "round";
    context.beginPath();
    context.moveTo(x - dx * radius * 0.35, y - dy * radius * 0.35);
    context.lineTo(x + dx * radius * 0.55, y + dy * radius * 0.55);
    context.stroke();
  }
  context.restore();
}

function drawCrash(
  context: CanvasRenderingContext2D,
  at: Point,
  cellSize: number,
  color: string,
) {
  const x = (at[0] + 0.5) * cellSize;
  const y = (at[1] + 0.5) * cellSize;
  context.save();
  context.translate(x, y);
  context.strokeStyle = "#fff4ca";
  context.shadowColor = color;
  context.shadowBlur = cellSize * 1.25;
  context.lineWidth = Math.max(2, cellSize * 0.13);
  for (let ray = 0; ray < 8; ray++) {
    const angle = (ray * Math.PI) / 4;
    context.beginPath();
    context.moveTo(
      Math.cos(angle) * cellSize * 0.18,
      Math.sin(angle) * cellSize * 0.18,
    );
    context.lineTo(
      Math.cos(angle) * cellSize * 0.72,
      Math.sin(angle) * cellSize * 0.72,
    );
    context.stroke();
  }
  context.restore();
}

/** Server-authoritative Light Cycles grid with defensive replay-frame parsing. */
export default function TronRenderer({ render }: { render: TronRender }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const width = dimension(render?.width, DEFAULT_WIDTH);
  const height = dimension(render?.height, DEFAULT_HEIGHT);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const cellSize = Math.max(8, Math.min(24, 900 / Math.max(width, height)));
    const logicalWidth = width * cellSize;
    const logicalHeight = height * cellSize;
    const pixelRatio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    canvas.width = Math.round(logicalWidth * pixelRatio);
    canvas.height = Math.round(logicalHeight * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    const background = context.createRadialGradient(
      logicalWidth / 2,
      logicalHeight / 2,
      0,
      logicalWidth / 2,
      logicalHeight / 2,
      Math.max(logicalWidth, logicalHeight) * 0.7,
    );
    background.addColorStop(0, "#10192a");
    background.addColorStop(1, "#03060c");
    context.fillStyle = background;
    context.fillRect(0, 0, logicalWidth, logicalHeight);

    context.strokeStyle = "rgba(92, 121, 167, 0.16)";
    context.lineWidth = 1;
    for (let column = 0; column <= width; column++) {
      const x = column * cellSize;
      context.beginPath();
      context.moveTo(x, 0);
      context.lineTo(x, logicalHeight);
      context.stroke();
    }
    for (let row = 0; row <= height; row++) {
      const y = row * cellSize;
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(logicalWidth, y);
      context.stroke();
    }

    const rawTrails = Array.isArray(render?.trails) ? render.trails : [];
    const rawHeads = Array.isArray(render?.heads) ? render.heads : [];
    const rawDirections = Array.isArray(render?.directions)
      ? render.directions
      : [];
    const rawAlive = Array.isArray(render?.alive) ? render.alive : [];

    for (const seat of [0, 1] as const) {
      const cells = trail(rawTrails[seat], width, height);
      drawTrail(context, cells, cellSize, RIDER_COLORS[seat]);
    }
    for (const seat of [0, 1] as const) {
      const head = point(rawHeads[seat], width, height);
      if (!head) continue;
      drawHead(
        context,
        head,
        direction(rawDirections[seat]),
        cellSize,
        RIDER_COLORS[seat],
        rawAlive[seat] !== false,
      );
    }

    if (Array.isArray(render?.crashes)) {
      for (const value of render.crashes.slice(0, 2)) {
        if (!value || typeof value !== "object") continue;
        const seat = Reflect.get(value, "seat");
        const at = crashPoint(value, width, height);
        if ((seat === 0 || seat === 1) && at) {
          drawCrash(context, at, cellSize, RIDER_COLORS[seat]);
        }
      }
    }

    const tick = Number.isInteger(render?.tick) ? (render.tick as number) : 0;
    const maxTicks = Number.isInteger(render?.max_ticks)
      ? (render.max_ticks as number)
      : null;
    context.fillStyle = "rgba(231, 233, 238, 0.74)";
    context.font = `600 ${Math.max(10, cellSize * 0.65)}px ui-monospace, monospace`;
    context.textAlign = "left";
    context.textBaseline = "top";
    context.fillText(
      maxTicks ? `TICK ${tick} / ${maxTicks}` : `TICK ${tick}`,
      cellSize * 0.45,
      cellSize * 0.35,
    );
  }, [height, render, width]);

  return (
    <canvas
      ref={ref}
      aria-label={`${width} by ${height} Light Cycles arena`}
      className="h-auto w-full max-h-[80vh] rounded-lg border border-edge bg-[#03060c] object-contain"
      style={{ aspectRatio: `${width} / ${height}` }}
    />
  );
}
