"""Deterministic two-player Battle Tetris.

Each realtime tick gives both players one independent opportunity to lock their
current tetromino.  The agent action is atomic::

    {"rotation": 0, "column": 3, "drop": true}

``column`` is the preferred left edge of the rotated piece's normalized
bounding box.  The engine tries that column, then one cell left, then one cell
right when the spawn cells are obstructed.  This small, deterministic kick
table is intentionally not advertised as guideline SRS.  The piece then hard
drops and locks.  Missing, malformed, out-of-range, or currently obstructed
actions are safe no-ops; they never mutate the board or crash the match loop.

Both seats consume the same nth piece from a seeded seven-bag sequence.  Line
clears attack according to 0/0/1/2/4 garbage rows for 0/1/2/3/4 clears.
Simultaneous attacks cancel before any garbage is applied.  Garbage holes use
a separate seeded stream, and the nth received row has the same hole for both
seats.  Overflow or having no legal spawn for the next piece is a top-out.
"""

from __future__ import annotations

import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engine.base import BaseGame

Cell = str | None
Coordinates = tuple[tuple[int, int], ...]

PIECE_TYPES = ("I", "O", "T", "S", "Z", "J", "L")
GARBAGE_CELL = "G"
KICK_OFFSETS = (0, -1, 1)
CLEAR_POINTS = {0: 0, 1: 100, 2: 300, 3: 500, 4: 800}
ATTACK_ROWS = {0: 0, 1: 0, 2: 1, 3: 2, 4: 4}

_SPAWN_SHAPES: dict[str, Coordinates] = {
    "I": ((0, 0), (0, 1), (0, 2), (0, 3)),
    "O": ((0, 0), (0, 1), (1, 0), (1, 1)),
    "T": ((0, 0), (0, 1), (0, 2), (1, 1)),
    "S": ((0, 1), (0, 2), (1, 0), (1, 1)),
    "Z": ((0, 0), (0, 1), (1, 1), (1, 2)),
    "J": ((0, 0), (1, 0), (1, 1), (1, 2)),
    "L": ((0, 2), (1, 0), (1, 1), (1, 2)),
}


def _normalize(cells: Coordinates) -> Coordinates:
    """Move a rotated piece to a zero-based bounding box."""
    minimum_row = min(row for row, _ in cells)
    minimum_column = min(column for _, column in cells)
    return tuple(sorted((row - minimum_row, column - minimum_column) for row, column in cells))


def _clockwise(cells: Coordinates) -> Coordinates:
    return _normalize(tuple((column, -row) for row, column in cells))


def _all_rotations(spawn: Coordinates) -> tuple[Coordinates, ...]:
    rotations: list[Coordinates] = []
    current = _normalize(spawn)
    for _ in range(4):
        rotations.append(current)
        current = _clockwise(current)
    return tuple(rotations)


SHAPES: dict[str, tuple[Coordinates, ...]] = {
    piece: _all_rotations(cells) for piece, cells in _SPAWN_SHAPES.items()
}


class TetrisConfig(BaseModel):
    """Server-controlled battle rules with hard time and memory bounds."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    columns: int = Field(default=10, ge=6, le=16)
    rows: int = Field(default=20, ge=12, le=40)
    tick_rate: int = Field(default=2, ge=1, le=20)
    max_duration_seconds: int = Field(default=600, ge=30, le=3_600)
    max_pieces_per_player: int = Field(default=500, ge=1, le=2_000)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def validate_tick_budget(self) -> TetrisConfig:
        if self.tick_rate * self.max_duration_seconds > 20_000:
            raise ValueError("tick_rate * max_duration_seconds must not exceed 20000")
        return self


class Tetris(BaseGame):
    mode = "realtime"
    name = "tetris"
    CATALOG = {
        "title": "Battle Tetris",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": (
            "Place matching seven-bag pieces, clear lines, and send garbage to top out your rival."
        ),
    }
    CONFIG_MODEL = TetrisConfig
    CONFIG_DEFAULTS = TetrisConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.rng.seed(self.seed)
        self.tick = 0
        self.move_count = 0

        # Piece and garbage randomness must be independent: an attack cannot
        # perturb later piece order.  These are deterministic simulation RNGs.
        self._piece_rng = random.Random(self.seed ^ 0x5454524953)  # noqa: S311
        self._garbage_rng = random.Random(self.seed ^ 0x47415242414745)  # noqa: S311
        self._piece_sequence: list[str] = []
        self._garbage_holes: list[int] = []
        self._garbage_cursor = [0, 0]

        columns = int(self.config["columns"])
        rows = int(self.config["rows"])
        self.boards: list[list[list[Cell]]] = [
            [[None for _ in range(columns)] for _ in range(rows)] for _ in range(2)
        ]
        self.piece_indices = [0, 0]
        self.scores = [0, 0]
        self.lines = [0, 0]
        self.attacks = [0, 0]
        self.garbage_received = [0, 0]
        self.top_out = [False, False]
        self.last_move: dict[str, Any] | None = None
        self._ensure_piece(1)

    # ---- deterministic sequences -----------------------------------------
    def _ensure_piece(self, index: int) -> None:
        while len(self._piece_sequence) <= index:
            bag = list(PIECE_TYPES)
            self._piece_rng.shuffle(bag)
            self._piece_sequence.extend(bag)

    def _piece(self, seat: int, offset: int = 0) -> str:
        index = self.piece_indices[seat] + offset
        self._ensure_piece(index)
        return self._piece_sequence[index]

    def _next_garbage_hole(self, seat: int) -> int:
        index = self._garbage_cursor[seat]
        while len(self._garbage_holes) <= index:
            self._garbage_holes.append(self._garbage_rng.randrange(int(self.config["columns"])))
        self._garbage_cursor[seat] += 1
        return self._garbage_holes[index]

    # ---- placement and collision -----------------------------------------
    @staticmethod
    def _parse_action(action: Any) -> tuple[int, int] | None:
        if not isinstance(action, dict) or set(action) != {"rotation", "column", "drop"}:
            return None
        rotation = action.get("rotation")
        column = action.get("column")
        if (
            isinstance(rotation, bool)
            or not isinstance(rotation, int)
            or not 0 <= rotation <= 3
            or isinstance(column, bool)
            or not isinstance(column, int)
            or action.get("drop") is not True
        ):
            return None
        return rotation, column

    def _collides(
        self,
        seat: int,
        cells: Coordinates,
        origin_row: int,
        origin_column: int,
    ) -> bool:
        board = self.boards[seat]
        rows = int(self.config["rows"])
        columns = int(self.config["columns"])
        for row_offset, column_offset in cells:
            row = origin_row + row_offset
            column = origin_column + column_offset
            if row < 0 or row >= rows or column < 0 or column >= columns:
                return True
            if board[row][column] is not None:
                return True
        return False

    def _resolve_spawn_column(
        self, seat: int, cells: Coordinates, preferred_column: int
    ) -> int | None:
        for offset in KICK_OFFSETS:
            candidate = preferred_column + offset
            if not self._collides(seat, cells, 0, candidate):
                return candidate
        return None

    def _legal_placements(self, seat: int) -> list[dict[str, int | bool]]:
        if self.is_terminal() or seat not in (0, 1) or self.top_out[seat]:
            return []
        piece = self._piece(seat)
        columns = int(self.config["columns"])
        legal: list[dict[str, int | bool]] = []
        for rotation, cells in enumerate(SHAPES[piece]):
            width = max(column for _, column in cells) + 1
            legal.extend(
                {
                    "rotation": rotation,
                    "column": preferred_column,
                    "drop": True,
                }
                for preferred_column in range(columns - width + 1)
                if self._resolve_spawn_column(seat, cells, preferred_column) is not None
            )
        return legal

    def _clear_lines(self, seat: int) -> int:
        board = self.boards[seat]
        kept = [row for row in board if any(cell is None for cell in row)]
        cleared = len(board) - len(kept)
        columns = int(self.config["columns"])
        self.boards[seat] = [[None] * columns for _ in range(cleared)] + kept
        return cleared

    def _place_piece(self, seat: int, action: Any) -> dict[str, Any] | None:
        parsed = self._parse_action(action)
        if parsed is None:
            return None
        rotation, preferred_column = parsed
        piece = self._piece(seat)
        cells = SHAPES[piece][rotation]
        width = max(column for _, column in cells) + 1
        columns = int(self.config["columns"])
        if not 0 <= preferred_column <= columns - width:
            return None
        column = self._resolve_spawn_column(seat, cells, preferred_column)
        if column is None:
            return None

        row = 0
        while not self._collides(seat, cells, row + 1, column):
            row += 1
        for row_offset, column_offset in cells:
            self.boards[seat][row + row_offset][column + column_offset] = piece

        cleared = self._clear_lines(seat)
        # A valid game position cannot clear more than four lines with one
        # tetromino.  The clamp keeps private helpers bounded under test/debug
        # mutation without inflating score or garbage beyond the public rules.
        rewarded_clears = min(4, cleared)
        self.scores[seat] += CLEAR_POINTS[rewarded_clears]
        self.lines[seat] += cleared
        self.piece_indices[seat] += 1
        self._ensure_piece(self.piece_indices[seat] + 1)
        return {
            "piece": piece,
            "rotation": rotation,
            "requested_column": preferred_column,
            "column": column,
            "row": row,
            "cleared": cleared,
            "attack": ATTACK_ROWS[rewarded_clears],
        }

    # ---- garbage and terminal resolution ---------------------------------
    def _add_garbage(self, seat: int, count: int) -> bool:
        """Append garbage and return whether occupied cells overflowed."""
        overflow = False
        columns = int(self.config["columns"])
        for _ in range(count):
            removed = self.boards[seat].pop(0)
            overflow = overflow or any(cell is not None for cell in removed)
            hole = self._next_garbage_hole(seat)
            self.boards[seat].append(
                [None if column == hole else GARBAGE_CELL for column in range(columns)]
            )
        self.garbage_received[seat] += count
        return overflow

    def _has_legal_spawn(self, seat: int) -> bool:
        return bool(self._legal_placements(seat))

    def _finish_by_score(self) -> None:
        if self.scores[0] > self.scores[1]:
            self._set_result([0])
        elif self.scores[1] > self.scores[0]:
            self._set_result([1])
        else:
            self._set_result(None)

    def step(self, moves: dict[int, Any]) -> None:
        if self.is_terminal():
            return
        submitted = moves if isinstance(moves, dict) else {}

        # Detect an already blocked next piece even when its agent sends
        # nothing.  Packet loss cannot postpone an inevitable top-out.
        blocked_before = [not self._has_legal_spawn(seat) for seat in (0, 1)]
        if any(blocked_before):
            self.top_out = blocked_before
            self.tick += 1
            self.move_count = self.tick
            self.last_move = {
                "tick": self.tick,
                "placements": [None, None],
                "cancelled": 0,
                "garbage": [0, 0],
                "top_out": self.top_out.copy(),
            }
            if all(blocked_before):
                self._set_result(None)
            else:
                self._set_result([1 if blocked_before[0] else 0])
            return

        placements = [self._place_piece(seat, submitted.get(seat)) for seat in (0, 1)]
        generated = [
            int(placement["attack"]) if placement is not None else 0 for placement in placements
        ]
        cancelled = min(generated)
        delivered = [generated[0] - cancelled, generated[1] - cancelled]

        # delivered[0] is seat 0's outgoing attack and therefore lands on 1.
        overflow = [
            self._add_garbage(0, delivered[1]),
            self._add_garbage(1, delivered[0]),
        ]
        self.attacks[0] += delivered[0]
        self.attacks[1] += delivered[1]

        blocked_after = [not self._has_legal_spawn(seat) for seat in (0, 1)]
        self.top_out = [overflow[seat] or blocked_after[seat] for seat in (0, 1)]
        self.tick += 1
        self.move_count = self.tick
        self.last_move = {
            "tick": self.tick,
            "placements": [
                dict(placement) if placement is not None else None for placement in placements
            ],
            "cancelled": cancelled,
            "garbage": [delivered[1], delivered[0]],
            "top_out": self.top_out.copy(),
        }

        if self.top_out[0] and self.top_out[1]:
            self._set_result(None)
        elif self.top_out[0]:
            self._set_result([1])
        elif self.top_out[1]:
            self._set_result([0])
        else:
            max_ticks = int(self.config["tick_rate"]) * int(self.config["max_duration_seconds"])
            piece_cap = int(self.config["max_pieces_per_player"])
            # Both seats received an action opportunity on this tick.  Ending
            # as soon as either reaches the cap prevents an extra-piece turn.
            if self.tick >= max_ticks or max(self.piece_indices) >= piece_cap:
                self._finish_by_score()

    # ---- public state -----------------------------------------------------
    def get_legal_actions(self, seat: int) -> list[dict[str, int | bool]]:
        return [action.copy() for action in self._legal_placements(seat)]

    def _board_state(self, seat: int) -> dict[str, Any]:
        return {
            "seat": seat,
            "board": [row.copy() for row in self.boards[seat]],
            "current": self._piece(seat),
            "next": [self._piece(seat, 1), self._piece(seat, 2)],
            "score": self.scores[seat],
            "lines": self.lines[seat],
            "attacks": self.attacks[seat],
            "garbage_received": self.garbage_received[seat],
            "pieces": self.piece_indices[seat],
            "top_out": self.top_out[seat],
        }

    def get_scores(self) -> dict[str, Any]:
        return {
            "players": [
                {
                    "seat": seat,
                    "score": self.scores[seat],
                    "lines": self.lines[seat],
                    "attacks": self.attacks[seat],
                    "garbage_received": self.garbage_received[seat],
                    "pieces": self.piece_indices[seat],
                }
                for seat in (0, 1)
            ]
        }

    def get_render_data(self) -> dict[str, Any]:
        max_ticks = int(self.config["tick_rate"]) * int(self.config["max_duration_seconds"])
        return {
            "columns": int(self.config["columns"]),
            "rows": int(self.config["rows"]),
            "boards": [self._board_state(seat) for seat in (0, 1)],
            "tick": self.tick,
            "max_ticks": max_ticks,
            "terminal": self.is_terminal(),
            "winner": self.get_winner().copy() if self.get_winner() is not None else None,
        }

    def summary(self) -> str:
        score = f"{self.scores[0]}-{self.scores[1]}"
        if not self.is_terminal():
            return f"Battle Tetris — score {score}, tick {self.tick}"
        winner = self.get_winner()
        if winner is None:
            return f"Battle Tetris — draw, score {score}"
        loser = 1 - winner[0]
        reason = "top-out" if self.top_out[loser] else "score limit"
        return f"Battle Tetris — player {winner[0]} wins by {reason}, score {score}"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        last_move = None
        if self.last_move is not None:
            last_move = {
                "tick": self.last_move["tick"],
                "placements": [
                    dict(placement) if placement is not None else None
                    for placement in self.last_move["placements"]
                ],
                "cancelled": self.last_move["cancelled"],
                "garbage": self.last_move["garbage"].copy(),
                "top_out": self.last_move["top_out"].copy(),
            }
        return {
            "state": {
                "columns": int(self.config["columns"]),
                "rows": int(self.config["rows"]),
                "boards": [self._board_state(seat) for seat in (0, 1)],
                "tick": self.tick,
                "max_ticks": int(self.config["tick_rate"])
                * int(self.config["max_duration_seconds"]),
            },
            "legal_actions": [self.get_legal_actions(seat) for seat in (0, 1)],
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": last_move,
            "time": None,
        }
