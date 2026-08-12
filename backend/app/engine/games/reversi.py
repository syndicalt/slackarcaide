"""Standard 8x8 Reversi (Othello) for two players.

Seat 0 owns black disks and moves first; seat 1 owns white disks. A placement
must bracket at least one opposing disk along a row, column, or diagonal. When
the opponent has no placement after a move, their turn is passed automatically.
The game ends when neither player can move or all 60 possible placements have
been made.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

SIZE = 8
MAX_PLACEMENTS = SIZE * SIZE - 4
_DIRECTIONS = tuple(
    (row_step, column_step)
    for row_step in (-1, 0, 1)
    for column_step in (-1, 0, 1)
    if (row_step, column_step) != (0, 0)
)


class ReversiTimeControl(BaseModel):
    """Bounded Fischer clock settings for a Reversi match."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=600, ge=1, le=86_400)
    increment_sec: int = Field(default=2, ge=0, le=3_600)
    enabled: bool = True


class ReversiConfig(BaseModel):
    """Validated rules accepted by the Reversi engine host."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    time_control: ReversiTimeControl = Field(default_factory=ReversiTimeControl)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class Reversi(BaseGame):
    mode = "turnbased"
    name = "reversi"
    CATALOG = {
        "title": "Reversi",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Bracket and flip opposing disks on a standard 8x8 board.",
    }
    CONFIG_MODEL = ReversiConfig
    CONFIG_DEFAULTS = ReversiConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.board: list[list[int | None]] = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        self.board[3][3] = 1
        self.board[3][4] = 0
        self.board[4][3] = 0
        self.board[4][4] = 1
        self._current_seat = 0
        self.move_count = 0
        self.last_move: dict[str, Any] | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self._current_seat

    def get_legal_actions(self, seat: int) -> list[dict[str, int | bool]]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        actions: list[dict[str, int | bool]] = [
            {"row": row, "column": column} for row, column in self._legal_placements(seat)
        ]
        actions.append({"resign": True})
        return actions

    def _legal_placements(self, seat: int) -> list[tuple[int, int]]:
        return [
            (row, column)
            for row in range(SIZE)
            for column in range(SIZE)
            if self.board[row][column] is None and self._captured_disks(row, column, seat)
        ]

    def _captured_disks(self, row: int, column: int, seat: int) -> list[tuple[int, int]]:
        if self.board[row][column] is not None:
            return []
        opponent = 1 - seat
        captured: list[tuple[int, int]] = []
        for row_step, column_step in _DIRECTIONS:
            line: list[tuple[int, int]] = []
            next_row = row + row_step
            next_column = column + column_step
            while (
                0 <= next_row < SIZE
                and 0 <= next_column < SIZE
                and self.board[next_row][next_column] == opponent
            ):
                line.append((next_row, next_column))
                next_row += row_step
                next_column += column_step
            if (
                line
                and 0 <= next_row < SIZE
                and 0 <= next_column < SIZE
                and self.board[next_row][next_column] == seat
            ):
                captured.extend(line)
        return captured

    def apply_action(self, action: Any) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        if not isinstance(action, dict):
            raise IllegalMove(
                "invalid_action",
                "action must be {'row': 0..7, 'column': 0..7} or {'resign': true}",
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
        if set(action) != {"row", "column"}:
            raise IllegalMove(
                "invalid_action", "action must contain exactly integer row and column fields"
            )

        row = action["row"]
        column = action["column"]
        if (
            isinstance(row, bool)
            or not isinstance(row, int)
            or isinstance(column, bool)
            or not isinstance(column, int)
        ):
            raise IllegalMove(
                "invalid_position", "row and column must be integers from 0 through 7"
            )
        if not (0 <= row < SIZE and 0 <= column < SIZE):
            raise IllegalMove(
                "invalid_position", "row and column must be integers from 0 through 7"
            )
        if self.board[row][column] is not None:
            raise IllegalMove("occupied_position", "position is already occupied")

        captured = self._captured_disks(row, column, seat)
        if not captured:
            raise IllegalMove("no_capture", "placement must capture at least one opposing disk")

        self.board[row][column] = seat
        for captured_row, captured_column in captured:
            self.board[captured_row][captured_column] = seat

        opponent = 1 - seat
        opponent_moves = self._legal_placements(opponent)
        passed_seat: int | None = None
        terminal = False
        if opponent_moves:
            self._current_seat = opponent
        else:
            own_moves = self._legal_placements(seat)
            if own_moves:
                self._current_seat = seat
                passed_seat = opponent
            else:
                self._current_seat = opponent
                terminal = True

        self.last_move = {
            "event": "place",
            "seat": seat,
            "row": row,
            "column": column,
            "flipped": len(captured),
            "flipped_positions": [list(position) for position in captured],
            "passed_seat": passed_seat,
            "move": self.move_count + 1,
        }
        self._note_move(seat)
        if terminal or self.move_count >= MAX_PLACEMENTS:
            self._finish_by_disk_count()

    def _finish_by_disk_count(self) -> None:
        counts = self._disk_counts()
        if counts[0] == counts[1]:
            self._set_result(None)
        else:
            self._set_result([0 if counts[0] > counts[1] else 1])

    def _disk_counts(self) -> list[int]:
        counts = [0, 0]
        for row in self.board:
            for disk in row:
                if disk is not None:
                    counts[disk] += 1
        return counts

    def get_scores(self) -> dict[str, int | list[int]]:
        disks = self._disk_counts()
        return {
            "disks": disks,
            "empty": SIZE * SIZE - sum(disks),
            "moves": self.move_count,
        }

    def _last_move_copy(self) -> dict[str, Any] | None:
        if self.last_move is None:
            return None
        copied = dict(self.last_move)
        flipped_positions = copied.get("flipped_positions")
        if isinstance(flipped_positions, list):
            copied["flipped_positions"] = [list(position) for position in flipped_positions]
        return copied

    def get_render_data(self) -> dict[str, Any]:
        return {
            "size": SIZE,
            "board": [row.copy() for row in self.board],
            "turn": self.current_seat(),
            "last_move": self._last_move_copy(),
        }

    def summary(self) -> str:
        if self.is_terminal():
            if self.last_move and self.last_move.get("event") == "resign":
                resigned = int(self.last_move["seat"])
                return f"Reversi — player {resigned} resigns; player {1 - resigned} wins"
            disks = self._disk_counts()
            winner = self.get_winner()
            if winner is None:
                return f"Reversi — draw, {disks[0]}-{disks[1]}"
            return f"Reversi — player {winner[0]} wins, {disks[0]}-{disks[1]}"

        passed = self.last_move.get("passed_seat") if self.last_move else None
        pass_note = f"; player {passed} passed" if passed is not None else ""
        return (
            f"Reversi — move {self.move_count + 1}; player {self.current_seat()} to move{pass_note}"
        )

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        passed = self.last_move.get("passed_seat") if self.last_move else None
        return {
            "state": {
                "board": [row.copy() for row in self.board],
                "size": SIZE,
                "turn": self.current_seat(),
                "move_number": self.move_count + 1,
                "passed_seat": passed,
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": self._last_move_copy(),
            "time": self.clock_state(),
        }
