"""Connect Four — 2-player turn-based engine (spec §8.2).

Reference implementation for the turn-based loop. Actions are column indices
0..6. Standard 6x7 grid, four-in-a-row to win, draw on full board. Deterministic
given seed (seeding only matters for older engines; C4 needs none).
"""
from typing import Any

from app.engine.base import BaseGame, IllegalMove

ROWS, COLS = 6, 7
PLAYERS = [0, 1]  # seats, alternating


class ConnectFour(BaseGame):
    mode = "turnbased"
    name = "connect_four"
    CATALOG = {
        "title": "Connect Four",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Drop discs, get four in a row.",
    }
    CONFIG_DEFAULTS = {
        "max_players": 2,
        "time_control": {"base_sec": 60, "increment_sec": 2, "enabled": False},
        "side_assignment": "drop",  # drop: first two to join get seat order
    }

    def reset(self) -> None:
        self.board = [[None for _ in range(COLS)] for _ in range(ROWS)]
        self.turn = 0
        self.move_count = 0
        self.last_move = None
        self.winner: list[int] | None = None
        # deterministic pseudo-side assignment by seed for parity/rendering
        self.sides = {0: self.rng.choice([0, 1]), 1: 1 - self.rng.choice([0, 1])}

    # ---- turn-based -------------------------------------------------------
    def current_seat(self) -> int:
        return self.turn % 2

    def get_legal_actions(self, seat: int) -> list[dict]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        return [{"column": c} for c in range(COLS) if self.board[0][c] is None]

    def apply_action(self, action: Any) -> None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be {'column': int}")
        col = action.get("column")
        if not isinstance(col, int) or not (0 <= col < COLS):
            raise IllegalMove("invalid_column", f"column must be 0..{COLS - 1}")
        if self.is_terminal():
            raise IllegalMove("game_over", "match has already ended")
        seat = self.current_seat()
        if self.board[0][col] is not None:
            raise IllegalMove("column_full", f"column {col} is full")

        row = self._drop_row(col)
        self.board[row][col] = self.sides[seat]
        self.move_count += 1
        self.last_move = {"seat": seat, "column": col, "row": row, "move": self.move_count}
        if self._check_win(row, col):
            self.winner = [seat]
        self.turn += 1

    def _drop_row(self, col: int) -> int:
        for r in range(ROWS - 1, -1, -1):
            if self.board[r][col] is None:
                return r
        raise IllegalMove("column_full", f"column {col} is full")

    def _check_win(self, row: int, col: int) -> bool:
        color = self.board[row][col]
        dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in dirs:
            count = 1
            for sign in (1, -1):
                r, c = row, col
                while True:
                    r += sign * dr
                    c += sign * dc
                    if not (0 <= r < ROWS and 0 <= c < COLS) or self.board[r][c] != color:
                        break
                    count += 1
            if count >= 4:
                return True
        return False

    # ---- shared -----------------------------------------------------------
    def is_terminal(self) -> bool:
        if self.winner is not None:
            return True
        return all(self.board[0][c] is not None for c in range(COLS))  # board full -> draw

    def get_winner(self) -> list[int] | None:
        return self.winner

    def get_scores(self) -> dict:
        return {"moves": self.move_count}

    def get_render_data(self) -> dict:
        return {"board": [[str(v) if v is not None else "" for v in row] for row in self.board]}

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "board": [[str(v) if v is not None else "" for v in row] for row in self.board],
                "rows": ROWS,
                "cols": COLS,
                "turn": self.current_seat(),
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": {"moves": self.move_count},
            "summary": (f"Connect Four — move {self.move_count}; "
                        f"{'game over' if self.is_terminal() else f'player {self.current_seat()} to move'}"),
            "last_move": self.last_move,
            "time": None,
        }
