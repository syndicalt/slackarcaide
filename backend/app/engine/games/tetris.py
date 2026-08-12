"""Tetris — single-player realtime engine.

Standard guideline-ish Tetris: 7-bag piece selection via seeded ``self.rng``,
soft/hard drops, line clears with scoring, and lock-down. Terminal when a newly
spawned piece collides immediately with the stack. Deterministic given
``(config, seed, seats)``.
"""
from typing import Any

from app.engine.base import BaseGame

# Piece type -> rotation states, each a list of (row, col) cell offsets within
# the piece's bounding box. Rotation 0 is the spawn orientation.
SHAPES: dict[str, list[list[tuple[int, int]]]] = {
    "I": [
        [(0, 0), (0, 1), (0, 2), (0, 3)],
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(0, 0), (0, 1), (0, 2), (0, 3)],
        [(0, 1), (1, 1), (2, 1), (3, 1)],
    ],
    "O": [
        [(0, 0), (0, 1), (1, 0), (1, 1)],
        [(0, 0), (0, 1), (1, 0), (1, 1)],
        [(0, 0), (0, 1), (1, 0), (1, 1)],
        [(0, 0), (0, 1), (1, 0), (1, 1)],
    ],
    "T": [
        [(0, 1), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (1, 1), (1, 2), (2, 1)],
        [(0, 1), (1, 0), (1, 1), (2, 1)],
    ],
    "S": [
        [(0, 1), (0, 2), (1, 0), (1, 1)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (0, 2), (1, 0), (1, 1)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
    ],
    "Z": [
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 2), (1, 1), (1, 2), (2, 1)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
        [(0, 2), (1, 1), (1, 2), (2, 1)],
    ],
    "J": [
        [(0, 0), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (0, 2), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 0)],
    ],
    "L": [
        [(0, 2), (1, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (1, 2), (2, 0)],
        [(0, 0), (0, 1), (1, 1), (2, 1)],
    ],
}

PIECE_TYPES = list(SHAPES.keys())
# Color numbers stored in board cells; 0 = empty.
COLOR_NUM: dict[str, int] = {"I": 1, "O": 2, "T": 3, "S": 4, "Z": 5, "J": 6, "L": 7}
COLOR_NAME: dict[int, str] = {v: k for k, v in COLOR_NUM.items()}
# Standard line-clear scoring keyed by lines cleared in one go.
CLEAR_POINTS = {1: 100, 2: 300, 3: 500, 4: 800}


class Tetris(BaseGame):
    mode = "realtime"
    name = "tetris"
    CATALOG = {
        "title": "Tetris",
        "min_players": 1,
        "max_players": 1,
        "players_before_start": 1,
        "elo_ranked": False,
        "blurb": "Stack falling tetrominoes and clear lines alone.",
    }
    CONFIG_DEFAULTS = {
        "players": 1,
        "players_before_start": 1,
        "cols": 10,
        "rows": 20,
        "level_lines": 10,
    }

    def reset(self) -> None:
        self.tick = 0
        self.score = 0
        self.lines = 0
        self.level = 1
        self.board = [[0] * self.config["cols"] for _ in range(self.config["rows"])]
        self._bag: list[str] = []
        self.current_type: str = "I"
        self.current_rot = 0
        self.piece_row = 0
        self.piece_col = 0
        self._game_over = False
        self.last_move: dict | None = None
        self._spawn_piece()

    # ---- piece helpers ----------------------------------------------------
    def _refill_bag(self) -> None:
        if not self._bag:
            self._bag = list(PIECE_TYPES)
            self.rng.shuffle(self._bag)

    def _spawn_piece(self) -> None:
        self._refill_bag()
        self.current_type = self._bag.pop(0)
        self._refill_bag()  # guarantee a 'next' preview remains
        self.current_rot = 0
        width = max(c for _, c in SHAPES[self.current_type][0]) + 1
        self.piece_col = (self.config["cols"] - width) // 2
        self.piece_row = 0
        if self._collides(self.current_type, self.piece_row, self.piece_col, 0):
            self._game_over = True
            self.last_move = {"event": "game_over", "score": self.score}

    def _collides(self, ptype: str, row: int, col: int, rot: int) -> bool:
        cols = self.config["cols"]
        rows = self.config["rows"]
        for dr, dc in SHAPES[ptype][rot]:
            r, c = row + dr, col + dc
            if c < 0 or c >= cols or r >= rows:
                return True
            if r >= 0 and self.board[r][c]:
                return True
        return False

    def _merge(self) -> None:
        color = COLOR_NUM[self.current_type]
        for dr, dc in SHAPES[self.current_type][self.current_rot]:
            r = self.piece_row + dr
            c = self.piece_col + dc
            if 0 <= r < self.config["rows"]:
                self.board[r][c] = color

    def _clear_lines(self) -> int:
        kept = [row for row in self.board if not all(row)]
        cleared = self.config["rows"] - len(kept)
        while len(kept) < self.config["rows"]:
            kept.insert(0, [0] * self.config["cols"])
        self.board = kept
        return cleared

    def _lock_piece(self) -> None:
        self._merge()
        cleared = self._clear_lines()
        if cleared:
            self.score += CLEAR_POINTS.get(cleared, 0) * self.level
            self.lines += cleared
            self.level = self.lines // self.config["level_lines"] + 1
            self.last_move = {"event": "clear", "n": cleared, "score": self.score}
        self._spawn_piece()

    def _hard_drop(self) -> None:
        while not self._collides(self.current_type, self.piece_row + 1,
                                 self.piece_col, self.current_rot):
            self.piece_row += 1
        self._lock_piece()

    # ---- realtime ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        self._refill_bag()
        if not self._game_over:
            mv = moves.get(0)
            action = mv.get("move") if isinstance(mv, dict) else None
            handled = self._apply_action(action)
            # Gravity: slide down one row; lock when it can't descend.
            if not handled and not self._collides(self.current_type,
                                                  self.piece_row + 1,
                                                  self.piece_col,
                                                  self.current_rot):
                self.piece_row += 1
            elif not handled:
                self._lock_piece()
        self.tick += 1

    def _apply_action(self, action: str | None) -> bool:
        """Handle one action; return True if the piece was locked (skip gravity)."""
        ptype = self.current_type
        if action == "left":
            if not self._collides(ptype, self.piece_row, self.piece_col - 1, self.current_rot):
                self.piece_col -= 1
        elif action == "right":
            if not self._collides(ptype, self.piece_row, self.piece_col + 1, self.current_rot):
                self.piece_col += 1
        elif action == "down":
            if not self._collides(ptype, self.piece_row + 1, self.piece_col, self.current_rot):
                self.piece_row += 1
        elif action == "rotate":
            nrot = (self.current_rot + 1) % len(SHAPES[ptype])
            if not self._collides(ptype, self.piece_row, self.piece_col, nrot):
                self.current_rot = nrot
        elif action == "drop":
            self._hard_drop()
            return True
        return False

    def is_terminal(self) -> bool:
        return self._game_over

    def get_winner(self) -> list[int] | None:
        if not self.is_terminal():
            return None
        return []  # single player, plays for score

    def get_scores(self) -> dict:
        return {"0": self.score}

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [{"move": m} for m in ("left", "right", "down", "rotate", "drop", "")]

    def get_render_data(self) -> dict:
        return {
            "w": self.config["cols"],
            "h": self.config["rows"],
            "board": self.board,
            "current": {
                "type": self.current_type,
                "coords": [[self.piece_row + dr, self.piece_col + dc]
                           for dr, dc in SHAPES[self.current_type][self.current_rot]],
            },
            "score": self.score,
            "lines": self.lines,
            "next": self._bag[0],
        }

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "board": self.board,
                "current": {"type": self.current_type, "rot": self.current_rot,
                            "row": self.piece_row, "col": self.piece_col},
                "next": self._bag[0],
                "score": self.score,
                "lines": self.lines,
                "level": self.level,
                "w": self.config["cols"],
                "h": self.config["rows"],
            },
            "legal_actions": [
                [{"move": m} for m in ("left", "right", "down", "rotate", "drop", "")]
            ],
            "scores": {"0": self.score},
            "summary": f"Tetris score {self.score} lines {self.lines}"
                       + (" — topped out" if self._game_over else ""),
            "last_move": self.last_move,
            "time": None,
        }

    def summary(self) -> str:
        return f"Tetris score {self.score} lines {self.lines}"


CATALOG = {
    "game": "tetris",
    "mode": "realtime",
    "name": "Tetris",
    "players": {"min": 1, "max": 1},
    "players_before_start": 1,
    "elo_ranked": False,
    "blurb": "Stack, clear lines, don't top out.",
}
