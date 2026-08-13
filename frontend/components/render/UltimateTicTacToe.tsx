"use client";

import { useEffect, useRef } from "react";

const SIZE = 9;
const LOCAL_SIZE = 3;
const CELL = 54;
const LOGICAL_SIZE = SIZE * CELL;

type LocalResult = 0 | 1 | "draw" | null;

type UltimateTicTacToeRender = {
  board?: unknown;
  local_results?: unknown;
  active_board?: unknown;
  turn?: unknown;
  last_move?: unknown;
  result?: unknown;
};

function boardFrom(value: unknown): (0 | 1 | null)[][] {
  return Array.from({ length: SIZE }, (_, row) => {
    const source =
      Array.isArray(value) && Array.isArray(value[row]) ? value[row] : [];
    return Array.from({ length: SIZE }, (_, column) => {
      const cell = source[column];
      return cell === 0 || cell === 1 ? cell : null;
    });
  });
}

function localResultsFrom(value: unknown): LocalResult[][] {
  return Array.from({ length: LOCAL_SIZE }, (_, row) => {
    const source =
      Array.isArray(value) && Array.isArray(value[row]) ? value[row] : [];
    return Array.from({ length: LOCAL_SIZE }, (_, column) => {
      const result = source[column];
      return result === 0 || result === 1 || result === "draw" ? result : null;
    });
  });
}

function boundedPair(
  value: unknown,
  upperBound: number,
): [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [row, column] = value;
  if (
    !Number.isInteger(row) ||
    !Number.isInteger(column) ||
    (row as number) < 0 ||
    (row as number) >= upperBound ||
    (column as number) < 0 ||
    (column as number) >= upperBound
  ) {
    return null;
  }
  return [row as number, column as number];
}

function lastPlacement(value: unknown): [number, number] | null {
  if (!value || typeof value !== "object") return null;
  return boundedPair(
    [Reflect.get(value, "row"), Reflect.get(value, "column")],
    SIZE,
  );
}

function winnerFrom(value: unknown): 0 | 1 | null {
  if (!value || typeof value !== "object") return null;
  const winner = Reflect.get(value, "winner");
  return Array.isArray(winner) &&
    winner.length === 1 &&
    (winner[0] === 0 || winner[0] === 1)
    ? winner[0]
    : null;
}

function statusText(render: UltimateTicTacToeRender): string {
  const result =
    render.result && typeof render.result === "object" ? render.result : null;
  if (result && Reflect.get(result, "terminal") === true) {
    const winner = winnerFrom(result);
    if (winner !== null) return `Game over · Player ${winner + 1} wins`;
    return Reflect.get(result, "winner") === null
      ? "Game over · Draw"
      : "Game over";
  }

  const turn = render.turn === 0 || render.turn === 1 ? render.turn : null;
  if (turn === null) return "Ultimate Tic-Tac-Toe";
  const activeBoard = boundedPair(render.active_board, LOCAL_SIZE);
  return activeBoard
    ? `Player ${turn + 1} to move · Local board ${activeBoard[0] + 1}, ${activeBoard[1] + 1}`
    : `Player ${turn + 1} to move · Any unfinished local board`;
}

/**
 * Defensive 9x9 renderer with explicit forced-board, local-result, last-move,
 * and terminal-result cues. Malformed spectator frames degrade to empty cells.
 */
export default function UltimateTicTacToeRenderer({
  render,
}: {
  render: UltimateTicTacToeRender;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const status = statusText(render ?? {});

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const board = boardFrom(render?.board);
    const localResults = localResultsFrom(render?.local_results);
    const resultIsTerminal =
      render?.result &&
      typeof render.result === "object" &&
      Reflect.get(render.result, "terminal") === true;
    const activeBoard = resultIsTerminal
      ? null
      : boundedPair(render?.active_board, LOCAL_SIZE);
    const lastMove = lastPlacement(render?.last_move);
    const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
    canvas.width = Math.round(LOGICAL_SIZE * pixelRatio);
    canvas.height = Math.round(LOGICAL_SIZE * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    context.fillStyle = "#080b13";
    context.fillRect(0, 0, LOGICAL_SIZE, LOGICAL_SIZE);

    for (let localRow = 0; localRow < LOCAL_SIZE; localRow++) {
      for (let localColumn = 0; localColumn < LOCAL_SIZE; localColumn++) {
        const x = localColumn * LOCAL_SIZE * CELL;
        const y = localRow * LOCAL_SIZE * CELL;
        const localResult = localResults[localRow][localColumn];
        const isActive =
          activeBoard?.[0] === localRow && activeBoard?.[1] === localColumn;

        context.fillStyle = isActive
          ? "rgba(124, 124, 255, 0.18)"
          : localResult === 0
            ? "rgba(255, 84, 112, 0.10)"
            : localResult === 1
              ? "rgba(34, 255, 209, 0.09)"
              : localResult === "draw"
                ? "rgba(231, 196, 107, 0.06)"
                : "rgba(255, 255, 255, 0.015)";
        context.fillRect(
          x + 3,
          y + 3,
          LOCAL_SIZE * CELL - 6,
          LOCAL_SIZE * CELL - 6,
        );

        if (isActive) {
          context.strokeStyle = "#7c7cff";
          context.lineWidth = 4;
          context.strokeRect(
            x + 4,
            y + 4,
            LOCAL_SIZE * CELL - 8,
            LOCAL_SIZE * CELL - 8,
          );
        }
      }
    }

    for (let line = 0; line <= SIZE; line++) {
      const coordinate = line * CELL;
      const localBoundary = line % LOCAL_SIZE === 0;
      context.strokeStyle = localBoundary ? "#5d6680" : "#252c40";
      context.lineWidth = localBoundary ? 4 : 1.25;
      context.beginPath();
      context.moveTo(coordinate, 0);
      context.lineTo(coordinate, LOGICAL_SIZE);
      context.stroke();
      context.beginPath();
      context.moveTo(0, coordinate);
      context.lineTo(LOGICAL_SIZE, coordinate);
      context.stroke();
    }

    for (let row = 0; row < SIZE; row++) {
      for (let column = 0; column < SIZE; column++) {
        const cell = board[row][column];
        if (cell === null) continue;
        const centerX = column * CELL + CELL / 2;
        const centerY = row * CELL + CELL / 2;
        const radius = CELL * 0.27;
        context.strokeStyle = cell === 0 ? "#ff5470" : "#22ffd1";
        context.lineWidth = 5;
        context.lineCap = "round";
        context.shadowColor = context.strokeStyle;
        context.shadowBlur = 7;
        context.beginPath();
        if (cell === 0) {
          context.moveTo(centerX - radius, centerY - radius);
          context.lineTo(centerX + radius, centerY + radius);
          context.moveTo(centerX + radius, centerY - radius);
          context.lineTo(centerX - radius, centerY + radius);
        } else {
          context.arc(centerX, centerY, radius, 0, Math.PI * 2);
        }
        context.stroke();
        context.shadowBlur = 0;
      }
    }

    if (lastMove) {
      context.strokeStyle = "#f4d77d";
      context.lineWidth = 4;
      context.strokeRect(
        lastMove[1] * CELL + 5,
        lastMove[0] * CELL + 5,
        CELL - 10,
        CELL - 10,
      );
    }

    for (let localRow = 0; localRow < LOCAL_SIZE; localRow++) {
      for (let localColumn = 0; localColumn < LOCAL_SIZE; localColumn++) {
        const localResult = localResults[localRow][localColumn];
        if (localResult === null) continue;
        const centerX = (localColumn * LOCAL_SIZE + 1.5) * CELL;
        const centerY = (localRow * LOCAL_SIZE + 1.5) * CELL;
        context.save();
        context.globalAlpha = 0.26;
        context.fillStyle =
          localResult === 0
            ? "#ff5470"
            : localResult === 1
              ? "#22ffd1"
              : "#e7c46b";
        context.font = `900 ${CELL * 2.15}px ui-monospace, monospace`;
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(
          localResult === 0 ? "X" : localResult === 1 ? "O" : "—",
          centerX,
          centerY + CELL * 0.08,
        );
        context.restore();
      }
    }
  }, [render]);

  const terminal =
    render?.result &&
    typeof render.result === "object" &&
    Reflect.get(render.result, "terminal") === true;

  return (
    <div className="flex w-full flex-col gap-2">
      <div
        aria-live="polite"
        className={`rounded-md border px-3 py-2 text-center font-mono text-sm ${
          terminal
            ? "border-accent/60 bg-accent/10 text-accent"
            : "border-edge bg-panel/70 text-muted"
        }`}
      >
        {status}
      </div>
      <canvas
        ref={ref}
        aria-label={`Ultimate Tic-Tac-Toe board. ${status}`}
        className="h-auto w-full max-h-[80vh] rounded-lg border border-edge bg-[#080b13]"
        style={{ aspectRatio: "1 / 1" }}
      />
    </div>
  );
}
