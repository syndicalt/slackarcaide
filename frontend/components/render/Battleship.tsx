"use client";

import { useEffect, useRef } from "react";

const SIZE = 10;
const CELL = 30;
const LABEL = 24;
const GAP = 28;
const BOARD_PIXELS = SIZE * CELL;

type Coordinate = { row: number; column: number };
type VisibleCell = Coordinate & { shot: "hit" | "miss" };
type VisibleShip = { cells: Array<Coordinate & { hit: boolean }> };
type VisibleBoard = {
  seat: 0 | 1;
  cells: VisibleCell[];
  ships: VisibleShip[];
};

type BattleshipRender = {
  boards?: unknown;
  phase?: unknown;
  turn?: unknown;
};

function coordinate(value: unknown): Coordinate | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.row !== "number" ||
    !Number.isInteger(candidate.row) ||
    candidate.row < 0 ||
    candidate.row >= SIZE ||
    typeof candidate.column !== "number" ||
    !Number.isInteger(candidate.column) ||
    candidate.column < 0 ||
    candidate.column >= SIZE
  ) {
    return null;
  }
  return { row: candidate.row, column: candidate.column };
}

function visibleBoards(value: unknown): VisibleBoard[] {
  const source = Array.isArray(value) ? value : [];
  return ([0, 1] as const).map((seat) => {
    const raw = source.find(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        (item as Record<string, unknown>).seat === seat,
    ) as Record<string, unknown> | undefined;

    const cells: VisibleCell[] = [];
    for (const cell of Array.isArray(raw?.cells) ? raw.cells : []) {
      const position = coordinate(cell);
      if (!position || typeof cell !== "object" || cell === null) continue;
      const shot = (cell as Record<string, unknown>).shot;
      if (shot === "hit" || shot === "miss") cells.push({ ...position, shot });
    }

    const ships: VisibleShip[] = [];
    for (const ship of Array.isArray(raw?.ships) ? raw.ships : []) {
      if (typeof ship !== "object" || ship === null) continue;
      const shipCells: Array<Coordinate & { hit: boolean }> = [];
      const rawCells = (ship as Record<string, unknown>).cells;
      for (const cell of Array.isArray(rawCells) ? rawCells : []) {
        const position = coordinate(cell);
        if (!position) continue;
        shipCells.push({
          ...position,
          hit:
            typeof cell === "object" &&
            cell !== null &&
            (cell as Record<string, unknown>).hit === true,
        });
      }
      if (shipCells.length > 0) ships.push({ cells: shipCells });
    }
    return { seat, cells, ships };
  });
}

function drawBoard(
  ctx: CanvasRenderingContext2D,
  board: VisibleBoard,
  originX: number,
) {
  const originY = LABEL;
  ctx.fillStyle = "#9aa4bc";
  ctx.font = "bold 13px ui-monospace, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(`PLAYER ${board.seat}`, originX, LABEL / 2);

  ctx.fillStyle = "#081321";
  ctx.fillRect(originX, originY, BOARD_PIXELS, BOARD_PIXELS);
  ctx.strokeStyle = "#1c344c";
  ctx.lineWidth = 1;
  for (let index = 0; index <= SIZE; index++) {
    const offset = index * CELL;
    ctx.beginPath();
    ctx.moveTo(originX + offset, originY);
    ctx.lineTo(originX + offset, originY + BOARD_PIXELS);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(originX, originY + offset);
    ctx.lineTo(originX + BOARD_PIXELS, originY + offset);
    ctx.stroke();
  }

  // `ships` is optional by design. Public live observations omit it; a seat
  // view may include only its own fleet, and terminal frames include both.
  for (const ship of board.ships) {
    for (const cell of ship.cells) {
      const x = originX + cell.column * CELL;
      const y = originY + cell.row * CELL;
      ctx.fillStyle = cell.hit
        ? "rgba(255,84,112,0.34)"
        : "rgba(154,164,188,0.34)";
      ctx.fillRect(x + 3, y + 3, CELL - 6, CELL - 6);
      ctx.strokeStyle = cell.hit ? "#ff5470" : "#8090ab";
      ctx.strokeRect(x + 3.5, y + 3.5, CELL - 7, CELL - 7);
    }
  }

  for (const cell of board.cells) {
    const x = originX + cell.column * CELL + CELL / 2;
    const y = originY + cell.row * CELL + CELL / 2;
    if (cell.shot === "miss") {
      ctx.fillStyle = "#77a7ce";
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
      continue;
    }
    ctx.strokeStyle = "#ff5470";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x - 7, y - 7);
    ctx.lineTo(x + 7, y + 7);
    ctx.moveTo(x + 7, y - 7);
    ctx.lineTo(x - 7, y + 7);
    ctx.stroke();
  }
}

/** Draws public, seat-private, and terminal Battleship frames without secrets assumptions. */
export default function BattleshipRenderer({
  render,
}: {
  render: BattleshipRender;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const boards = visibleBoards(render.boards);
    canvas.width = LABEL + BOARD_PIXELS * 2 + GAP;
    canvas.height = LABEL + BOARD_PIXELS;
    ctx.fillStyle = "#06080d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawBoard(ctx, boards[0], 0);
    drawBoard(ctx, boards[1], BOARD_PIXELS + GAP);
  }, [render]);

  const phase = render.phase === "placement" ? "placement" : "battle";
  const turn = render.turn === 0 || render.turn === 1 ? render.turn : null;
  const label = `Battleship ${phase}${turn === null ? "" : `, player ${turn} to act`}`;

  return (
    <canvas
      ref={ref}
      aria-label={label}
      role="img"
      className="w-full h-auto max-h-[80vh] rounded-lg border border-edge bg-[#06080d]"
    />
  );
}
