"""Server-authoritative 9x9 Go with positional superko and area scoring.

Seat 0 is Black and moves first; seat 1 is White and receives the configured
komi (7.5 by default). A score is the number of living stones plus empty
regions bordered exclusively by that color. Captures are reported for
spectators but are not added to an area score. There is deliberately no
dead-stone negotiation: agents must capture stones they consider dead before
both players pass.

Legal actions are exactly one of::

    {"row": 0, "column": 0}
    {"pass": true}
    {"resign": true}

Rows and columns are zero-based. Suicide is forbidden, except that a placement
which first captures adjacent enemy stones is legal when the resulting group
has a liberty. Positional superko rejects any placement which recreates a board
position seen earlier in the match. Passes do not create a new board position.
Two consecutive passes end the game; ``max_moves`` is a deterministic safety
cap and uses the same area score.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engine.base import BaseGame, IllegalMove

BOARD_SIZE = 9
EMPTY = 0
BLACK = 1
WHITE = 2
_COLOR_NAMES = {BLACK: "black", WHITE: "white"}
Point = tuple[int, int]
Position = tuple[int, ...]


class GoTimeControl(BaseModel):
    """Admin-controlled, bounded Fischer clock settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=600, ge=1, le=86_400)
    increment_sec: int = Field(default=5, ge=0, le=3_600)
    enabled: bool = True


class GoConfig(BaseModel):
    """Validated configuration for SlackArcade's fixed-size Go rules."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    board_size: Literal[9] = 9
    komi: float = Field(default=7.5, ge=0.0, le=50.0)
    max_moves: int = Field(default=512, ge=2, le=512)
    time_control: GoTimeControl = Field(default_factory=GoTimeControl)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    @field_validator("komi", mode="before")
    @classmethod
    def require_float_komi(cls, value: object) -> object:
        if type(value) is not float:
            raise ValueError("komi must be a float")
        return value

    @field_validator("max_moves")
    @classmethod
    def require_equal_turn_cap(cls, value: int) -> int:
        if value % 2:
            raise ValueError("max_moves must be even so both seats receive equal turns")
        return value


class Go(BaseGame):
    """Auditable 9x9 Go implementation with no external rules dependency."""

    mode = "turnbased"
    name = "go"
    CATALOG = {
        "title": "Go (9x9)",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "9x9 Go with area scoring, positional superko, and 7.5 komi.",
    }
    CONFIG_MODEL = GoConfig
    CONFIG_DEFAULTS = GoConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.board = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.move_count = 0
        self.consecutive_passes = 0
        self.captures = {0: 0, 1: 0}
        self.last_move: dict[str, Any] | None = None
        self._position_history: set[Position] = {self._position(self.board)}
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self.move_count % 2

    @staticmethod
    def _neighbors(row: int, column: int) -> Iterable[Point]:
        if row > 0:
            yield row - 1, column
        if row + 1 < BOARD_SIZE:
            yield row + 1, column
        if column > 0:
            yield row, column - 1
        if column + 1 < BOARD_SIZE:
            yield row, column + 1

    @staticmethod
    def _position(board: list[list[int]]) -> Position:
        return tuple(stone for row in board for stone in row)

    @classmethod
    def _group_and_liberties(
        cls, board: list[list[int]], start: Point
    ) -> tuple[set[Point], set[Point]]:
        color = board[start[0]][start[1]]
        group: set[Point] = set()
        liberties: set[Point] = set()
        pending = [start]
        while pending:
            point = pending.pop()
            if point in group:
                continue
            group.add(point)
            for neighbor in cls._neighbors(*point):
                value = board[neighbor[0]][neighbor[1]]
                if value == EMPTY:
                    liberties.add(neighbor)
                elif value == color and neighbor not in group:
                    pending.append(neighbor)
        return group, liberties

    def _simulate_placement(
        self, row: int, column: int, color: int
    ) -> tuple[list[list[int]], int, Position]:
        if self.board[row][column] != EMPTY:
            raise IllegalMove("occupied", "intersection is already occupied")

        candidate = [board_row.copy() for board_row in self.board]
        candidate[row][column] = color
        opponent = WHITE if color == BLACK else BLACK
        captured: set[Point] = set()
        checked: set[Point] = set()
        for neighbor in self._neighbors(row, column):
            if candidate[neighbor[0]][neighbor[1]] != opponent or neighbor in checked:
                continue
            group, liberties = self._group_and_liberties(candidate, neighbor)
            checked.update(group)
            if not liberties:
                captured.update(group)
        for captured_row, captured_column in captured:
            candidate[captured_row][captured_column] = EMPTY

        _, own_liberties = self._group_and_liberties(candidate, (row, column))
        if not own_liberties:
            raise IllegalMove(
                "suicide", "move would leave the played stone's group without liberties"
            )

        position = self._position(candidate)
        if position in self._position_history:
            raise IllegalMove("superko", "move would repeat an earlier board position")
        return candidate, len(captured), position

    @staticmethod
    def _placement_coordinates(action: dict[str, Any]) -> tuple[int, int]:
        if set(action) != {"row", "column"}:
            raise IllegalMove(
                "invalid_action",
                "action must be exactly {'row','column'}, {'pass': true}, or {'resign': true}",
            )
        row, column = action["row"], action["column"]
        if (
            isinstance(row, bool)
            or not isinstance(row, int)
            or isinstance(column, bool)
            or not isinstance(column, int)
        ):
            raise IllegalMove("invalid_coordinate", "row and column must be integers")
        if not (0 <= row < BOARD_SIZE and 0 <= column < BOARD_SIZE):
            raise IllegalMove("out_of_bounds", "row and column must each be between 0 and 8")
        return row, column

    def _require_action(self, action: Any) -> dict[str, Any]:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be an object")
        if set(action) == {"pass"} and action["pass"] is True:
            return action
        if set(action) == {"resign"} and action["resign"] is True:
            return action
        # Explicitly reject false flags and mixed/unknown keys rather than
        # silently interpreting them as a placement.
        self._placement_coordinates(action)
        return action

    def apply_action(self, action: Any) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        parsed = self._require_action(action)
        seat = self.current_seat()
        remaining = self.clock_ms(seat)
        if remaining is not None and remaining <= 0:
            raise IllegalMove("clock_expired", "clock expired before action")

        if "resign" in parsed:
            self._note_move(seat)
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            self._set_result([1 - seat])
            return

        if "pass" in parsed:
            self.consecutive_passes += 1
            self._note_move(seat)
            self.last_move = {"event": "pass", "seat": seat, "move": self.move_count}
        else:
            row, column = self._placement_coordinates(parsed)
            color = BLACK if seat == 0 else WHITE
            candidate, captured, position = self._simulate_placement(row, column, color)
            self.board = candidate
            self._position_history.add(position)
            self.captures[seat] += captured
            self.consecutive_passes = 0
            self._note_move(seat)
            self.last_move = {
                "row": row,
                "column": column,
                "color": _COLOR_NAMES[color],
                "captured": captured,
                "seat": seat,
                "move": self.move_count,
            }

        if self.consecutive_passes >= 2 or self.move_count >= self.config["max_moves"]:
            self._adjudicate_area_score()

    def _territory(self) -> dict[int, int]:
        territory = {BLACK: 0, WHITE: 0}
        visited: set[Point] = set()
        for row in range(BOARD_SIZE):
            for column in range(BOARD_SIZE):
                start = (row, column)
                if self.board[row][column] != EMPTY or start in visited:
                    continue
                region: set[Point] = set()
                borders: set[int] = set()
                pending = [start]
                while pending:
                    point = pending.pop()
                    if point in region:
                        continue
                    region.add(point)
                    for neighbor in self._neighbors(*point):
                        value = self.board[neighbor[0]][neighbor[1]]
                        if value == EMPTY and neighbor not in region:
                            pending.append(neighbor)
                        elif value != EMPTY:
                            borders.add(value)
                visited.update(region)
                if len(borders) == 1:
                    territory[borders.pop()] += len(region)
        return territory

    def get_scores(self) -> dict[str, dict[str, int | float]]:
        stones = {
            BLACK: sum(stone == BLACK for row in self.board for stone in row),
            WHITE: sum(stone == WHITE for row in self.board for stone in row),
        }
        territory = self._territory()
        komi = float(self.config["komi"])
        return {
            "black": {
                "stones": stones[BLACK],
                "territory": territory[BLACK],
                "komi": 0.0,
                "total": float(stones[BLACK] + territory[BLACK]),
                "captures": self.captures[0],
            },
            "white": {
                "stones": stones[WHITE],
                "territory": territory[WHITE],
                "komi": komi,
                "total": float(stones[WHITE] + territory[WHITE]) + komi,
                "captures": self.captures[1],
            },
        }

    def _adjudicate_area_score(self) -> None:
        scores = self.get_scores()
        black_total = scores["black"]["total"]
        white_total = scores["white"]["total"]
        if black_total > white_total:
            self._set_result([0])
        elif white_total > black_total:
            self._set_result([1])
        else:
            self._set_result(None)

    def _is_legal_placement(self, row: int, column: int, color: int) -> bool:
        if self.board[row][column] != EMPTY:
            return False
        try:
            self._simulate_placement(row, column, color)
        except IllegalMove:
            return False
        return True

    def get_legal_actions(self, seat: int) -> list[dict[str, int | bool]]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        color = BLACK if seat == 0 else WHITE
        placements = [
            {"row": row, "column": column}
            for row in range(BOARD_SIZE)
            for column in range(BOARD_SIZE)
            if self._is_legal_placement(row, column, color)
        ]
        return [*placements, {"pass": True}, {"resign": True}]

    def get_render_data(self) -> dict[str, Any]:
        names = {EMPTY: None, BLACK: "black", WHITE: "white"}
        return {
            "size": BOARD_SIZE,
            "board": [[names[stone] for stone in row] for row in self.board],
            "turn": self.current_seat(),
            "last_move": dict(self.last_move) if self.last_move is not None else None,
            "captures": {
                "black": self.captures[0],
                "white": self.captures[1],
            },
        }

    def summary(self) -> str:
        if self.last_move and self.last_move.get("event") == "resign":
            resigned = self.last_move["seat"]
            return f"Go (9x9) — player {resigned} resigns; player {1 - resigned} wins"
        if self.is_terminal():
            scores = self.get_scores()
            black = scores["black"]["total"]
            white = scores["white"]["total"]
            if self.get_winner() is None:
                return f"Go (9x9) — draw, {black:g}-{white:g}"
            winner = "Black" if self.get_winner() == [0] else "White"
            return f"Go (9x9) — {winner} wins, {black:g}-{white:g}"
        color = "Black" if self.current_seat() == 0 else "White"
        return f"Go (9x9) — move {self.move_count + 1}; {color} to move"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        return {
            "state": {
                "board_size": BOARD_SIZE,
                "board": [row.copy() for row in self.board],
                "turn": self.current_seat(),
                "consecutive_passes": self.consecutive_passes,
                "position_count": len(self._position_history),
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": dict(self.last_move) if self.last_move is not None else None,
            "time": self.clock_state(),
        }
