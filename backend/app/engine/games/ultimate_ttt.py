"""Canonical two-player Ultimate Tic-Tac-Toe.

The 9x9 board is divided into nine 3x3 local boards. Seat 0 moves first. A
placement at global cell ``(row, column)`` sends the opponent to local board
``(row % 3, column % 3)``. If that destination board is already won or full,
the opponent may play in any unfinished local board.

Won and drawn local boards are closed to further play. Only won local boards
count toward the global three-in-a-row; a drawn local board blocks that line.
If all nine local boards finish without a global winner, the match is a draw.
Consequently a non-resigned match contains at most 81 placements.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

SIZE = 9
LOCAL_SIZE = 3
MAX_PLACEMENTS = SIZE * SIZE
_LINES = (
    ((0, 0), (0, 1), (0, 2)),
    ((1, 0), (1, 1), (1, 2)),
    ((2, 0), (2, 1), (2, 2)),
    ((0, 0), (1, 0), (2, 0)),
    ((0, 1), (1, 1), (2, 1)),
    ((0, 2), (1, 2), (2, 2)),
    ((0, 0), (1, 1), (2, 2)),
    ((0, 2), (1, 1), (2, 0)),
)

type LocalResult = int | Literal["draw"] | None
type LocalBoard = tuple[int, int]


class UltimateTicTacToeTimeControl(BaseModel):
    """Bounded Fischer clock settings for one match."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=300, ge=1, le=86_400)
    increment_sec: int = Field(default=2, ge=0, le=3_600)
    enabled: bool = True


class UltimateTicTacToeConfig(BaseModel):
    """Validated, server-controlled Ultimate Tic-Tac-Toe rules."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    time_control: UltimateTicTacToeTimeControl = Field(
        default_factory=UltimateTicTacToeTimeControl
    )
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class UltimateTicTacToe(BaseGame):
    mode = "turnbased"
    name = "ultimate_ttt"
    CATALOG = {
        "title": "Ultimate Tic-Tac-Toe",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Win local boards while each move dictates where your opponent plays.",
    }
    CONFIG_MODEL = UltimateTicTacToeConfig
    CONFIG_DEFAULTS = UltimateTicTacToeConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.board: list[list[int | None]] = [
            [None for _ in range(SIZE)] for _ in range(SIZE)
        ]
        self.local_results: list[list[LocalResult]] = [
            [None for _ in range(LOCAL_SIZE)] for _ in range(LOCAL_SIZE)
        ]
        self.active_board: LocalBoard | None = None
        self.move_count = 0
        self.last_move: dict[str, Any] | None = None
        self._end_reason: str | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self.move_count % 2

    def get_legal_actions(self, seat: int) -> list[dict[str, int | bool]]:
        if (
            self.is_terminal()
            or isinstance(seat, bool)
            or not isinstance(seat, int)
            or seat != self.current_seat()
        ):
            return []

        actions: list[dict[str, int | bool]] = [
            {"row": row, "column": column}
            for row in range(SIZE)
            for column in range(SIZE)
            if self.board[row][column] is None
            and self.local_results[row // LOCAL_SIZE][column // LOCAL_SIZE] is None
            and (
                self.active_board is None
                or (row // LOCAL_SIZE, column // LOCAL_SIZE) == self.active_board
            )
        ]
        actions.append({"resign": True})
        return actions

    @staticmethod
    def _validate_action(action: Any) -> tuple[int, int] | None:
        if not isinstance(action, dict):
            raise IllegalMove(
                "invalid_action",
                "action must be {'row': 0..8, 'column': 0..8} or {'resign': true}",
            )
        if set(action) == {"resign"}:
            if action["resign"] is True:
                return None
            raise IllegalMove("invalid_action", "resign must be true")
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
            or not 0 <= row < SIZE
            or not 0 <= column < SIZE
        ):
            raise IllegalMove(
                "invalid_position", "row and column must be integers from 0 through 8"
            )
        return row, column

    def apply_action(self, action: Any) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        placement = self._validate_action(action)

        seat = self.current_seat()
        remaining = self.clock_ms(seat)
        if remaining is not None and remaining <= 0:
            raise IllegalMove("clock_expired", "clock expired before action")

        if placement is None:
            self._note_move(seat)
            self.active_board = None
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            self._end_reason = "resignation"
            self._set_result([1 - seat])
            return

        row, column = placement
        local_board = (row // LOCAL_SIZE, column // LOCAL_SIZE)
        local_row, local_column = local_board
        if self.local_results[local_row][local_column] is not None:
            raise IllegalMove("local_board_complete", "that local board is already complete")
        if self.active_board is not None and local_board != self.active_board:
            required_row, required_column = self.active_board
            raise IllegalMove(
                "wrong_local_board",
                f"move must be in local board ({required_row}, {required_column})",
            )
        if self.board[row][column] is not None:
            raise IllegalMove("occupied_position", "position is already occupied")

        self.board[row][column] = seat
        local_result = self._local_result(local_row, local_column)
        if local_result is not None:
            self.local_results[local_row][local_column] = local_result

        destination = (row % LOCAL_SIZE, column % LOCAL_SIZE)
        destination_open = self.local_results[destination[0]][destination[1]] is None
        self.active_board = destination if destination_open else None
        self.last_move = {
            "event": "place",
            "seat": seat,
            "row": row,
            "column": column,
            "local_board": [local_row, local_column],
            "local_result": local_result,
            "next_board": list(self.active_board) if self.active_board is not None else None,
            "move": self.move_count + 1,
        }

        global_winner = self._line_winner(self.local_results)
        all_local_boards_complete = all(
            result is not None for results_row in self.local_results for result in results_row
        )
        if global_winner is not None or all_local_boards_complete:
            self.active_board = None
            self.last_move["next_board"] = None
        self._note_move(seat)
        if global_winner is not None:
            self._end_reason = "global line"
            self._set_result([global_winner])
        elif all_local_boards_complete:
            self._end_reason = "all local boards complete"
            self._set_result(None)

    @staticmethod
    def _line_winner(cells: list[list[LocalResult]]) -> int | None:
        for line in _LINES:
            first = cells[line[0][0]][line[0][1]]
            if first in (0, 1) and all(cells[row][column] == first for row, column in line[1:]):
                return first
        return None

    def _local_result(self, local_row: int, local_column: int) -> LocalResult:
        row_start = local_row * LOCAL_SIZE
        column_start = local_column * LOCAL_SIZE
        cells: list[list[LocalResult]] = [
            [
                self.board[row][column]
                for column in range(column_start, column_start + LOCAL_SIZE)
            ]
            for row in range(row_start, row_start + LOCAL_SIZE)
        ]
        winner = self._line_winner(cells)
        if winner is not None:
            return winner
        if all(cell is not None for row in cells for cell in row):
            return "draw"
        return None

    def _last_move_copy(self) -> dict[str, Any] | None:
        if self.last_move is None:
            return None
        copied = dict(self.last_move)
        for field in ("local_board", "next_board"):
            value = copied.get(field)
            if isinstance(value, list):
                copied[field] = value.copy()
        return copied

    def get_scores(self) -> dict[str, Any]:
        local_wins = [0, 0]
        local_draws = 0
        placements = [0, 0]
        for row in self.board:
            for cell in row:
                if cell is not None:
                    placements[cell] += 1
        for results_row in self.local_results:
            for result in results_row:
                if result == "draw":
                    local_draws += 1
                elif result in (0, 1):
                    local_wins[result] += 1
        return {
            "local_wins": local_wins,
            "local_draws": local_draws,
            "placements": placements,
            "moves": self.move_count,
            "empty": MAX_PLACEMENTS - sum(placements),
        }

    def get_render_data(self) -> dict[str, Any]:
        return {
            "size": SIZE,
            "board": [row.copy() for row in self.board],
            "local_results": [row.copy() for row in self.local_results],
            "active_board": list(self.active_board) if self.active_board is not None else None,
            "turn": self.current_seat(),
            "last_move": self._last_move_copy(),
            "result": {
                "terminal": self.is_terminal(),
                "winner": self.get_winner().copy() if self.get_winner() is not None else None,
                "reason": self._end_reason,
            },
        }

    def summary(self) -> str:
        if self.is_terminal():
            if self._end_reason == "resignation" and self.last_move is not None:
                resigned = int(self.last_move["seat"])
                return (
                    f"Ultimate Tic-Tac-Toe — player {resigned} resigns; "
                    f"player {1 - resigned} wins"
                )
            winner = self.get_winner()
            if winner is None:
                return "Ultimate Tic-Tac-Toe — draw"
            return f"Ultimate Tic-Tac-Toe — player {winner[0]} wins"

        if self.active_board is None:
            destination = "any unfinished local board"
        else:
            destination = f"local board ({self.active_board[0]}, {self.active_board[1]})"
        return (
            f"Ultimate Tic-Tac-Toe — move {self.move_count + 1}; "
            f"player {self.current_seat()} to move in {destination}"
        )

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        return {
            "state": {
                "board": [row.copy() for row in self.board],
                "local_results": [row.copy() for row in self.local_results],
                "active_board": (
                    list(self.active_board) if self.active_board is not None else None
                ),
                "turn": self.current_seat(),
                "move_number": self.move_count + 1,
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": self._last_move_copy(),
            "time": self.clock_state(),
        }
