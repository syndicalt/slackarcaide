"use client";

import { useEffect, useRef } from "react";

const DEFAULT_COLUMNS = 10;
const DEFAULT_ROWS = 20;
const MIN_COLUMNS = 6;
const MAX_COLUMNS = 16;
const MIN_ROWS = 12;
const MAX_ROWS = 40;
const PIECES = new Set(["I", "O", "T", "S", "Z", "J", "L"]);
const CELL_COLORS: Record<string, string> = {
  I: "#22ffd1",
  O: "#ffd452",
  T: "#a477ff",
  S: "#46e77d",
  Z: "#ff6078",
  J: "#5795ff",
  L: "#ff9c54",
  G: "#596275",
};
const PLAYER_COLORS = ["#ff6078", "#22ffd1"] as const;

const PREVIEW_SHAPES: Record<string, Array<[number, number]>> = {
  I: [
    [1, 0],
    [1, 1],
    [1, 2],
    [1, 3],
  ],
  O: [
    [0, 1],
    [0, 2],
    [1, 1],
    [1, 2],
  ],
  T: [
    [0, 0],
    [0, 1],
    [0, 2],
    [1, 1],
  ],
  S: [
    [0, 1],
    [0, 2],
    [1, 0],
    [1, 1],
  ],
  Z: [
    [0, 0],
    [0, 1],
    [1, 1],
    [1, 2],
  ],
  J: [
    [0, 0],
    [1, 0],
    [1, 1],
    [1, 2],
  ],
  L: [
    [0, 2],
    [1, 0],
    [1, 1],
    [1, 2],
  ],
};

type BoardFrame = {
  seat: 0 | 1;
  board: Array<Array<string | null>>;
  current: string | null;
  next: string[];
  score: number;
  lines: number;
  attacks: number;
  garbageReceived: number;
  pieces: number;
  topOut: boolean;
};

type TetrisRender = {
  columns?: unknown;
  rows?: unknown;
  boards?: unknown;
  tick?: unknown;
  max_ticks?: unknown;
  terminal?: unknown;
  winner?: unknown;
};

function boundedInteger(
  value: unknown,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  return Number.isInteger(value) &&
    (value as number) >= minimum &&
    (value as number) <= maximum
    ? (value as number)
    : fallback;
}

function safeCount(value: unknown): number {
  return Number.isInteger(value) && (value as number) >= 0
    ? Math.min(value as number, 1_000_000_000)
    : 0;
}

function piece(value: unknown): string | null {
  return typeof value === "string" && PIECES.has(value) ? value : null;
}

function boards(
  value: unknown,
  columns: number,
  rows: number,
): [BoardFrame, BoardFrame] {
  const source = Array.isArray(value) ? value.slice(0, 2) : [];
  return ([0, 1] as const).map((seat) => {
    const raw = source.find(
      (candidate) =>
        candidate !== null &&
        typeof candidate === "object" &&
        Reflect.get(candidate, "seat") === seat,
    );
    const rawBoard =
      raw !== undefined && Array.isArray(Reflect.get(raw, "board"))
        ? Reflect.get(raw, "board")
        : [];
    const board = Array.from({ length: rows }, (_, row) => {
      const rawRow = Array.isArray(rawBoard[row]) ? rawBoard[row] : [];
      return Array.from({ length: columns }, (_, column) => {
        const cell = rawRow[column];
        return typeof cell === "string" && (PIECES.has(cell) || cell === "G")
          ? cell
          : null;
      });
    });
    const nextValue = raw === undefined ? [] : Reflect.get(raw, "next");
    const next = Array.isArray(nextValue)
      ? nextValue
          .slice(0, 2)
          .map(piece)
          .filter((item): item is string => item !== null)
      : [];
    return {
      seat,
      board,
      current: piece(
        raw === undefined ? undefined : Reflect.get(raw, "current"),
      ),
      next,
      score: safeCount(
        raw === undefined ? undefined : Reflect.get(raw, "score"),
      ),
      lines: safeCount(
        raw === undefined ? undefined : Reflect.get(raw, "lines"),
      ),
      attacks: safeCount(
        raw === undefined ? undefined : Reflect.get(raw, "attacks"),
      ),
      garbageReceived: safeCount(
        raw === undefined ? undefined : Reflect.get(raw, "garbage_received"),
      ),
      pieces: safeCount(
        raw === undefined ? undefined : Reflect.get(raw, "pieces"),
      ),
      topOut: raw !== undefined && Reflect.get(raw, "top_out") === true,
    };
  }) as [BoardFrame, BoardFrame];
}

function drawCell(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  size: number,
  cell: string,
) {
  const color = CELL_COLORS[cell] ?? CELL_COLORS.G;
  context.fillStyle = color;
  context.fillRect(x + 1, y + 1, size - 2, size - 2);
  context.fillStyle = "rgba(255,255,255,0.2)";
  context.fillRect(x + 2, y + 2, size - 4, Math.max(1, size * 0.12));
  if (cell === "G") {
    context.fillStyle = "rgba(8,11,18,0.45)";
    context.fillRect(x + size * 0.25, y + size * 0.25, size * 0.5, size * 0.5);
  }
}

function drawPreview(
  context: CanvasRenderingContext2D,
  pieceType: string | null,
  x: number,
  y: number,
  cellSize: number,
) {
  if (!pieceType) return;
  const previewCell = Math.max(4, Math.floor(cellSize * 0.55));
  for (const [row, column] of PREVIEW_SHAPES[pieceType]) {
    drawCell(
      context,
      x + column * previewCell,
      y + row * previewCell,
      previewCell,
      pieceType,
    );
  }
}

function drawPlayer(
  context: CanvasRenderingContext2D,
  frame: BoardFrame,
  originX: number,
  originY: number,
  columns: number,
  rows: number,
  cellSize: number,
) {
  const boardWidth = columns * cellSize;
  const boardHeight = rows * cellSize;
  context.fillStyle = "#060a12";
  context.fillRect(originX, originY, boardWidth, boardHeight);
  context.strokeStyle = PLAYER_COLORS[frame.seat];
  context.lineWidth = 2;
  context.strokeRect(originX - 1, originY - 1, boardWidth + 2, boardHeight + 2);

  context.strokeStyle = "rgba(102,120,151,0.18)";
  context.lineWidth = 1;
  for (let column = 1; column < columns; column += 1) {
    const x = originX + column * cellSize;
    context.beginPath();
    context.moveTo(x, originY);
    context.lineTo(x, originY + boardHeight);
    context.stroke();
  }
  for (let row = 1; row < rows; row += 1) {
    const y = originY + row * cellSize;
    context.beginPath();
    context.moveTo(originX, y);
    context.lineTo(originX + boardWidth, y);
    context.stroke();
  }

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const cell = frame.board[row][column];
      if (cell) {
        drawCell(
          context,
          originX + column * cellSize,
          originY + row * cellSize,
          cellSize,
          cell,
        );
      }
    }
  }

  if (frame.topOut) {
    context.fillStyle = "rgba(7,10,17,0.72)";
    context.fillRect(originX, originY, boardWidth, boardHeight);
    context.fillStyle = "#ff7088";
    context.font = `700 ${Math.max(15, cellSize * 1.05)}px ui-monospace, monospace`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(
      "TOP OUT",
      originX + boardWidth / 2,
      originY + boardHeight / 2,
    );
  }

  const hudX = originX + boardWidth + cellSize * 0.65;
  const fontSize = Math.max(9, cellSize * 0.6);
  context.textAlign = "left";
  context.textBaseline = "top";
  context.fillStyle = PLAYER_COLORS[frame.seat];
  context.font = `700 ${fontSize * 1.2}px ui-monospace, monospace`;
  context.fillText(`PLAYER ${frame.seat}`, hudX, originY);
  context.fillStyle = "#aeb7ca";
  context.font = `600 ${fontSize}px ui-monospace, monospace`;
  const metrics = [
    `SCORE  ${frame.score}`,
    `LINES  ${frame.lines}`,
    `ATTACK ${frame.attacks}`,
    `GARBAGE ${frame.garbageReceived}`,
    `PIECES ${frame.pieces}`,
  ];
  metrics.forEach((label, index) => {
    context.fillText(label, hudX, originY + fontSize * (2.2 + index * 1.45));
  });

  const previewY = originY + fontSize * 10.2;
  context.fillStyle = "#71809b";
  context.fillText("CURRENT", hudX, previewY);
  drawPreview(
    context,
    frame.current,
    hudX,
    previewY + fontSize * 1.4,
    cellSize,
  );
  context.fillStyle = "#71809b";
  context.fillText("NEXT", hudX, previewY + cellSize * 2.7);
  drawPreview(
    context,
    frame.next[0] ?? null,
    hudX,
    previewY + cellSize * 3.4,
    cellSize,
  );
}

/** Responsive, defensive spectator view for server-authoritative Battle Tetris. */
export default function TetrisRenderer({ render }: { render: TetrisRender }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const columns = boundedInteger(
    render?.columns,
    DEFAULT_COLUMNS,
    MIN_COLUMNS,
    MAX_COLUMNS,
  );
  const rows = boundedInteger(render?.rows, DEFAULT_ROWS, MIN_ROWS, MAX_ROWS);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const frames = boards(render?.boards, columns, rows);
    const cellSize = Math.max(11, Math.min(24, Math.floor(480 / rows)));
    const hudWidth = Math.max(96, cellSize * 5.4);
    const gap = Math.max(20, cellSize * 1.4);
    const playerWidth = columns * cellSize + hudWidth;
    const margin = Math.max(12, cellSize);
    const header = Math.max(34, cellSize * 2.1);
    const logicalWidth = margin * 2 + playerWidth * 2 + gap;
    const logicalHeight = margin + header + rows * cellSize + margin;
    const pixelRatio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    canvas.width = Math.round(logicalWidth * pixelRatio);
    canvas.height = Math.round(logicalHeight * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    context.fillStyle = "#03060c";
    context.fillRect(0, 0, logicalWidth, logicalHeight);
    const tick = safeCount(render?.tick);
    const maxTicks = safeCount(render?.max_ticks);
    const terminal = render?.terminal === true;
    const rawWinner = Array.isArray(render?.winner) ? render.winner : null;
    const winner =
      rawWinner?.length === 1 && (rawWinner[0] === 0 || rawWinner[0] === 1)
        ? rawWinner[0]
        : null;
    const matchStatus = terminal
      ? winner === null
        ? "DRAW"
        : `PLAYER ${winner} WINS`
      : maxTicks > 0
        ? `TICK ${tick} / ${maxTicks}`
        : `TICK ${tick}`;
    context.fillStyle = "#dce3ef";
    context.font = `700 ${Math.max(13, cellSize * 0.75)}px ui-monospace, monospace`;
    context.textAlign = "left";
    context.textBaseline = "middle";
    context.fillText(
      `BATTLE TETRIS  ·  ${matchStatus}`,
      margin,
      margin + header / 2,
    );

    drawPlayer(
      context,
      frames[0],
      margin,
      margin + header,
      columns,
      rows,
      cellSize,
    );
    drawPlayer(
      context,
      frames[1],
      margin + playerWidth + gap,
      margin + header,
      columns,
      rows,
      cellSize,
    );
  }, [columns, render, rows]);

  const terminal = render?.terminal === true;
  const rawWinner = Array.isArray(render?.winner) ? render.winner : null;
  const winner =
    rawWinner?.length === 1 && (rawWinner[0] === 0 || rawWinner[0] === 1)
      ? rawWinner[0]
      : null;
  const status = terminal
    ? winner === null
      ? "Battle Tetris finished in a draw"
      : `Battle Tetris finished; player ${winner} wins`
    : "Battle Tetris in progress";

  return (
    <figure className="m-0 w-full" aria-label={status}>
      <canvas
        ref={ref}
        role="img"
        aria-label={`${columns} by ${rows} ${status}`}
        className="h-auto w-full max-h-[80vh] rounded-lg border border-edge bg-[#03060c] object-contain"
      />
      <figcaption className="sr-only">{status}</figcaption>
    </figure>
  );
}
