"""Standard two-player Connect Four.

Seat 0 drops token 0 and moves first; seat 1 drops token 1. Rows are stored
top-to-bottom, so a legal action ``{"column": 3}`` occupies the lowest empty
cell in column 3. The board is fixed at seven columns by six rows and a match
therefore ends after at most 42 placements.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

ROWS = 6
COLUMNS = 7
CONNECT = 4


class ConnectFourTimeControl(BaseModel):
    """Bounded Fischer clock settings for a Connect Four match."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=300, ge=1, le=86_400)
    increment_sec: int = Field(default=2, ge=0, le=3_600)
    enabled: bool = True


class ConnectFourConfig(BaseModel):
    """Validated rules accepted by the Connect Four engine host."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    time_control: ConnectFourTimeControl = Field(default_factory=ConnectFourTimeControl)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class ConnectFour(BaseGame):
    mode = "turnbased"
    name = "connect_four"
    CATALOG = {
        "title": "Connect Four",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Drop tokens into seven columns; first to connect four wins.",
    }
    CONFIG_MODEL = ConnectFourConfig
    CONFIG_DEFAULTS = ConnectFourConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.board: list[list[int | None]] = [[None for _ in range(COLUMNS)] for _ in range(ROWS)]
        self.move_count = 0
        self.last_move: dict[str, int | str] | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self.move_count % 2

    def get_legal_actions(self, seat: int) -> list[dict[str, int | bool]]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        placements: list[dict[str, int | bool]] = [
            {"column": column} for column in range(COLUMNS) if self.board[0][column] is None
        ]
        placements.append({"resign": True})
        return placements

    def apply_action(self, action: Any) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        if not isinstance(action, dict):
            raise IllegalMove(
                "invalid_action", "action must be {'column': 0..6} or {'resign': true}"
            )

        seat = self.current_seat()
        remaining = self.clock_ms(seat)
        if remaining is not None and remaining <= 0:
            raise IllegalMove("clock_expired", "clock expired before action")

        if set(action) == {"resign"} and action["resign"] is True:
            self._note_move(seat)
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            self._set_result([1 - seat])
            return
        if set(action) != {"column"}:
            raise IllegalMove("invalid_action", "action must contain exactly one integer column")

        column = action["column"]
        if isinstance(column, bool) or not isinstance(column, int):
            raise IllegalMove("invalid_column", "column must be an integer from 0 through 6")
        if not 0 <= column < COLUMNS:
            raise IllegalMove("invalid_column", "column must be an integer from 0 through 6")

        row = next(
            (
                candidate
                for candidate in range(ROWS - 1, -1, -1)
                if self.board[candidate][column] is None
            ),
            None,
        )
        if row is None:
            raise IllegalMove("column_full", f"column {column} is full")

        self.board[row][column] = seat
        move_number = self.move_count + 1
        self.last_move = {
            "event": "drop",
            "seat": seat,
            "row": row,
            "column": column,
            "move": move_number,
        }
        won = self._connects_four(row, column, seat)
        self._note_move(seat)
        if won:
            self._set_result([seat])
        elif self.move_count == ROWS * COLUMNS:
            self._set_result(None)

    def _connects_four(self, row: int, column: int, seat: int) -> bool:
        for row_step, column_step in ((0, 1), (1, 0), (1, 1), (1, -1)):
            connected = 1
            connected += self._count_direction(row, column, seat, row_step, column_step)
            connected += self._count_direction(row, column, seat, -row_step, -column_step)
            if connected >= CONNECT:
                return True
        return False

    def _count_direction(
        self, row: int, column: int, seat: int, row_step: int, column_step: int
    ) -> int:
        count = 0
        row += row_step
        column += column_step
        while 0 <= row < ROWS and 0 <= column < COLUMNS and self.board[row][column] == seat:
            count += 1
            row += row_step
            column += column_step
        return count

    def get_scores(self) -> dict[str, int | list[int]]:
        token_counts = [0, 0]
        for row in self.board:
            for token in row:
                if token is not None:
                    token_counts[token] += 1
        return {
            "tokens": token_counts,
            "moves": self.move_count,
            "empty": ROWS * COLUMNS - self.move_count,
        }

    def get_render_data(self) -> dict[str, Any]:
        return {
            "rows": ROWS,
            "columns": COLUMNS,
            "board": [row.copy() for row in self.board],
            "turn": self.current_seat(),
            "last_move": dict(self.last_move) if self.last_move else None,
        }

    def summary(self) -> str:
        if self.is_terminal():
            if self.last_move and self.last_move.get("event") == "resign":
                resigned = int(self.last_move["seat"])
                return f"Connect Four — player {resigned} resigns; player {1 - resigned} wins"
            winner = self.get_winner()
            if winner is None:
                return "Connect Four — draw"
            return f"Connect Four — player {winner[0]} wins"
        return f"Connect Four — move {self.move_count + 1}; player {self.current_seat()} to move"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        return {
            "state": {
                "board": [row.copy() for row in self.board],
                "rows": ROWS,
                "columns": COLUMNS,
                "turn": self.current_seat(),
                "move_number": self.move_count + 1,
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": dict(self.last_move) if self.last_move else None,
            "time": self.clock_state(),
        }
