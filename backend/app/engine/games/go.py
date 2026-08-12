"""Go — 2-player turn-based engine (area scoring, basic ko).

Actions are dicts: ``{"pass": true}`` to pass, or ``{"x": int, "y": int}`` to play
a stone at a 0-indexed intersection. Coordinates/documentation per spec §8.2.

Rules implemented:
  * Board sizes 9x9 / 13x13 / 19x19 via ``board_size`` config (default 19).
  * Legal moves exclude occupied points, single-point ko (a move that recreates
    the previous board position), and suicide (a play must leave its own group
    with at least one liberty).
  * Captured groups (zero liberties) are removed immediately and counted.
  * Two consecutive passes end the game under **area scoring**:
    score = territory (empty intersections enclosed by exactly one color)
    + captured stones. Higher score wins; equal score is a draw.

Board rendering uses the spec's numeric cell convention: ``0`` = empty, ``1`` =
seat 0's stone, ``2`` = seat 1's stone. Fully deterministic given (config, seed,
seats).
"""
from typing import Any

from app.engine.base import BaseGame, IllegalMove


class Go(BaseGame):
    mode = "turnbased"
    name = "go"
    CATALOG = {
        "title": "Go",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Territory game on a 19x19 grid. Pass to end.",
    }
    CONFIG_DEFAULTS = {
        "players": 2,
        "players_before_start": 2,
        "board_size": 19,
        "time_control": {"base_sec": 600, "increment_sec": 0, "enabled": True},
    }

    def reset(self) -> None:
        self.size = int(self.config.get("board_size", 19))
        # cell: 0 = empty, 1 = seat 0, 2 = seat 1
        self.board = [[0 for _ in range(self.size)] for _ in range(self.size)]
        self.turn = 0
        self.move_count = 0
        self.last_move = None  # {"x","y"} or "pass"
        self.captures = {0: 0, 1: 0}
        self._ko_cmp = None  # board snapshot a move may not recreate
        self._passes = 0  # consecutive passes

    # ---- turn-based -------------------------------------------------------
    def current_seat(self) -> int:
        return self.turn % 2

    def get_legal_actions(self, seat: int) -> list[dict]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        color = self._color(seat)
        actions = []
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] == 0:
                    legal, _ = self._try_move(r, c, color)
                    if legal:
                        actions.append({"x": r, "y": c})
        actions.append({"pass": True})
        return actions

    def apply_action(self, action: Any) -> None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be {'x','y'} or {'pass': true}")
        if self.is_terminal():
            raise IllegalMove("game_over", "match has already ended")
        seat = self.current_seat()
        color = self._color(seat)
        snap_before = self._snap(self.board)

        if action.get("pass"):
            self.last_move = "pass"
            self._passes += 1
        else:
            x, y = action.get("x"), action.get("y")
            if (not isinstance(x, int) or not isinstance(y, int)
                    or not (0 <= x < self.size) or not (0 <= y < self.size)):
                raise IllegalMove("invalid_point", f"point must be within 0..{self.size - 1}")
            legal, _captured = self._try_move(x, y, color)
            if not legal:
                raise IllegalMove("illegal_move", f"illegal Go move at ({x}, {y})")

            # Apply the move to the real board.
            self.board[x][y] = color
            opp = 3 - color
            for nr, nc in self._neighbors(x, y):
                if self.board[nr][nc] == opp:
                    group = self._group(self.board, nr, nc)
                    if not self._group_liberties(self.board, group):
                        for gr, gc in group:
                            self.board[gr][gc] = 0
                        self.captures[seat] += len(group)
            self.last_move = {"x": x, "y": y}
            self._passes = 0

        self._ko_cmp = snap_before
        self.turn += 1
        self._note_move(seat)

        # Two consecutive passes -> end under area scoring.
        if self._passes >= 2:
            scores = self._scores()
            if scores[0] == scores[1]:
                self._set_result(None)
            else:
                self._set_result([0 if scores[0] > scores[1] else 1])

    # ---- rules helpers ----------------------------------------------------
    def _color(self, seat: int) -> int:
        return seat + 1

    def _neighbors(self, r: int, c: int):
        for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if 0 <= nr < self.size and 0 <= nc < self.size:
                yield nr, nc

    def _snap(self, board: list[list[int]]) -> tuple:
        return tuple(tuple(row) for row in board)

    def _group(self, board: list[list[int]], r: int, c: int) -> set:
        color = board[r][c]
        if color == 0:
            return set()
        group, stack = set(), [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if (cr, cc) in group:
                continue
            group.add((cr, cc))
            for nr, nc in self._neighbors(cr, cc):
                if board[nr][nc] == color and (nr, nc) not in group:
                    stack.append((nr, nc))
        return group

    def _group_liberties(self, board: list[list[int]], group: set) -> set:
        libs = set()
        for r, c in group:
            for nr, nc in self._neighbors(r, c):
                if board[nr][nc] == 0:
                    libs.add((nr, nc))
        return libs

    def _try_move(self, r: int, c: int, color: int) -> tuple[bool, int]:
        """Simulate a play; return (is_legal, opponent_stones_captured)."""
        if self.board[r][c] != 0:
            return False, 0
        b = [row[:] for row in self.board]
        b[r][c] = color
        opp = 3 - color
        captured = 0
        for nr, nc in self._neighbors(r, c):
            if b[nr][nc] == opp:
                group = self._group(b, nr, nc)
                if not self._group_liberties(b, group):
                    for gr, gc in group:
                        b[gr][gc] = 0
                    captured += len(group)
        # Single-point ko: recreating the previous board position is illegal.
        if self._ko_cmp is not None and self._snap(b) == self._ko_cmp:
            return False, 0
        # Suicide: the played group must keep a liberty.
        if not self._group_liberties(b, self._group(b, r, c)):
            return False, 0
        return True, captured

    def _territory(self) -> dict:
        """Empty intersections enclosed by exactly one color, per seat."""
        terr = {0: 0, 1: 0}
        seen = [[False for _ in range(self.size)] for _ in range(self.size)]
        for r in range(self.size):
            for c in range(self.size):
                if self.board[r][c] != 0 or seen[r][c]:
                    continue
                region, borders, stack = set(), set(), [(r, c)]
                seen[r][c] = True
                while stack:
                    cr, cc = stack.pop()
                    if (cr, cc) in region:
                        continue
                    region.add((cr, cc))
                    for nr, nc in self._neighbors(cr, cc):
                        v = self.board[nr][nc]
                        if v == 0:
                            if not seen[nr][nc]:
                                seen[nr][nc] = True
                                stack.append((nr, nc))
                        else:
                            borders.add(v)
                if len(borders) == 1:
                    terr[next(iter(borders)) - 1] += len(region)
        return terr

    def _scores(self) -> dict:
        terr = self._territory()
        return {0: terr[0] + self.captures[0], 1: terr[1] + self.captures[1]}

    # ---- shared -----------------------------------------------------------
    def get_scores(self) -> dict:
        terr = self._territory()
        result = {}
        for seat in (0, 1):
            stones = sum(1 for row in self.board for cell in row if cell == seat + 1)
            result[str(seat)] = {
                "stones": stones,
                "territory": terr[seat],
                "captures": self.captures[seat],
                "score": terr[seat] + self.captures[seat],
            }
        result["moves"] = self.move_count
        return result

    def get_render_data(self) -> dict:
        return {
            "board": [[cell for cell in row] for row in self.board],
            "size": self.size,
            "captures": {"0": self.captures[0], "1": self.captures[1]},
            "turn": self.current_seat(),
            "last_move": self.last_move,
        }

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": self.get_render_data(),
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }

    def summary(self) -> str:
        if not self.is_terminal():
            return f"Go in progress — player {self.current_seat()} to move"
        w = self.get_winner()
        if w is None:
            return "Go drawn"
        return f"Go won by player {w[0]}"


CATALOG = {
    "game": "go",
    "mode": "turnbased",
    "name": "Go",
    "players": {"min": 2, "max": 2},
    "players_before_start": 2,
    "elo_ranked": True,
    "blurb": "Territory, capture, and ko.",
}
