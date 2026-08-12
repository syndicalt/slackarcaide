"""Checkers (American) — 2-player turn-based engine.

Board is 8x8 with the 32 dark squares playable. Algebraic coordinates a1..h8;
the board is rendered from Black's perspective (Black at the bottom of the draw).
Seat 0 is Black and moves first; seat 1 is White. Pieces are 'b'/'w' (men) and
'B'/'W' (kings). Men move one square diagonally forward; kings move diagonally
any distance (flying kings). Captures are mandatory and multi-jumps form a single
full-chain action. A side wins when the opponent has no pieces or no legal move.

Deterministic given (config, seed, seats).
"""
from typing import Any

from app.engine.base import BaseGame, IllegalMove

SIZE = 8
DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
BLACK, WHITE = 0, 1


def _color_of(piece: Any) -> str | None:
    """Side ('b'|'w') of a board cell, or None for an empty square."""
    if piece is None:
        return None
    return "b" if piece in ("b", "B") else "w"


def _is_king(piece: Any) -> bool:
    return piece in ("B", "W")


class Checkers(BaseGame):
    mode = "turnbased"
    name = "checkers"
    CATALOG = {
        "title": "Checkers",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Jump-and-capture draughts on an 8x8 board.",
    }
    CONFIG_DEFAULTS = {
        "players": 2,
        "players_before_start": 2,
        "time_control": {"base_sec": 600, "increment_sec": 0, "enabled": True},
        "side_assignment": "fixed",  # seat 0 = Black, seat 1 = White
    }

    # ---- setup ------------------------------------------------------------
    def reset(self) -> None:
        self.board = [[None for _ in range(SIZE)] for _ in range(SIZE)]
        self.sides = {BLACK: "b", WHITE: "w"}
        self.turn = 0
        self.move_count = 0
        self.last_move = None
        # Black occupies ranks 1-3 (rows 0..2), White ranks 6-8 (rows 5..7),
        # on the dark squares (r+c) even (a1 is a dark square).
        for r, side in ((0, "b"), (1, "b"), (2, "b"), (5, "w"), (6, "w"), (7, "w")):
            for c in range(SIZE):
                if (r + c) % 2 == 0:
                    self.board[r][c] = side

    # ---- coordinates ------------------------------------------------------
    def _sq(self, r: int, c: int) -> str:
        return f"{chr(ord('a') + c)}{r + 1}"

    def _rc(self, sq: str) -> tuple[int, int]:
        try:
            sq = sq.lower().strip()
            if len(sq) != 2:
                raise ValueError
            r = int(sq[1]) - 1
            c = ord(sq[0]) - ord("a")
        except (ValueError, IndexError):
            raise ValueError(f"bad square {sq!r}")
        if not (0 <= r < SIZE and 0 <= c < SIZE):
            raise ValueError(f"bad square {sq!r}")
        return (r, c)

    def _on_board(self, r: int, c: int) -> bool:
        return 0 <= r < SIZE and 0 <= c < SIZE

    def _forward(self, side: str) -> int:
        """Men advance toward the far rank: Black +1, White -1."""
        return 1 if side == "b" else -1

    # ---- move generation --------------------------------------------------
    def _simple_moves(self, side: str, board: list) -> list[tuple[tuple[int, int], tuple[int, int]]]:
        """All non-capturing moves (from, to) for `side`."""
        moves: list[tuple[tuple[int, int], tuple[int, int]]] = []
        fwd = self._forward(side)
        for r in range(SIZE):
            for c in range(SIZE):
                p = board[r][c]
                if _color_of(p) != side:
                    continue
                if _is_king(p):
                    dirs = DIRS
                else:
                    dirs = ((fwd, 1), (fwd, -1))
                for dr, dc in dirs:
                    k = 1
                    while True:
                        r2, c2 = r + dr * k, c + dc * k
                        if not self._on_board(r2, c2):
                            break
                        if board[r2][c2] is not None:
                            break  # man steps once; king flies until blocked
                        moves.append(((r, c), (r2, c2)))
                        if not _is_king(p):
                            break
                        k += 1
        return moves

    def _capture_chains(self, side: str, board: list) -> list[list[tuple[int, int]]]:
        """All complete capture chains for `side`.

        Each chain is an ordered list of landing squares starting at the piece's
        origin, with every segment capturing an opponent piece. Landing squares
        beyond the first are reachable by continuing to capture (multi-jump).
        """
        enemy = "w" if side == "b" else "b"
        chains: list[list[tuple[int, int]]] = []

        def rec(r: int, c: int, piece: Any, path: list, bd: list) -> None:
            extended = False
            for dr, dc in DIRS:
                # First occupied square strictly outward along this diagonal.
                blocker_dist = blocker = None
                for k in range(1, SIZE):
                    r2, c2 = r + dr * k, c + dc * k
                    if not self._on_board(r2, c2):
                        break
                    if bd[r2][c2] is not None:
                        blocker_dist, blocker = k, (r2, c2)
                        break
                if blocker_dist is None or _color_of(bd[blocker[0]][blocker[1]]) != enemy:
                    continue
                # Determine legal landing squares beyond the jumped piece.
                if not _is_king(piece):
                    if blocker_dist != 1:
                        continue
                    lr, lc = r + dr * 2, c + dc * 2
                    if not self._on_board(lr, lc) or bd[lr][lc] is not None:
                        continue
                    landings = [(lr, lc)]
                else:
                    landings = []
                    k = blocker_dist + 1
                    while True:
                        lr, lc = r + dr * k, c + dc * k
                        if not self._on_board(lr, lc) or bd[lr][lc] is not None:
                            break
                        landings.append((lr, lc))
                        k += 1
                    if not landings:
                        continue
                for land in landings:
                    nb = [row[:] for row in bd]
                    nb[blocker[0]][blocker[1]] = None
                    nb[r][c] = None
                    nb[land[0]][land[1]] = piece
                    rec(land[0], land[1], piece, path + [land], nb)
                    extended = True
            if not extended and len(path) >= 2:
                chains.append(path)

        for r in range(SIZE):
            for c in range(SIZE):
                p = board[r][c]
                if _color_of(p) == side:
                    rec(r, c, p, [(r, c)], [row[:] for row in board])
        return chains

    def _player_has_move(self, side: str, board: list) -> bool:
        if self._capture_chains(side, board):
            return True
        return bool(self._simple_moves(side, board))

    # ---- turn-based -------------------------------------------------------
    def current_seat(self) -> int:
        return self.turn % 2

    def _action_from_chain(self, chain: list) -> dict:
        from_sq = self._sq(*chain[0])
        to_sq = self._sq(*chain[1])
        moves = [{"to": self._sq(*node)} for node in chain[2:]] if len(chain) > 2 else None
        return {"from": from_sq, "to": to_sq, "moves": moves}

    def get_legal_actions(self, seat: int) -> list[dict]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        side = self.sides[seat]
        chains = self._capture_chains(side, self.board)
        if chains:
            # Captures are mandatory: only full capture chains are legal.
            return [self._action_from_chain(ch) for ch in chains]
        simple = self._simple_moves(side, self.board)
        if not simple:
            # No pieces or no moves: opponent wins.
            self._set_result([1 - seat])
            return []
        return [{"from": self._sq(*f), "to": self._sq(*t), "moves": None} for f, t in simple]

    def _is_legal(self, seat: int, path: list) -> bool:
        """True when `path` (list of (r,c) landings) is a legal move for `seat`."""
        side = self.sides[seat]
        chains = self._capture_chains(side, self.board)
        if chains:
            return any(path == ch for ch in chains)
        simple = self._simple_moves(side, self.board)
        return any(path[:2] == [f, t] for f, t in simple)

    def apply_action(self, action: Any) -> None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be {'from','to','moves'}")
        if self.is_terminal():
            raise IllegalMove("game_over", "match has already ended")
        seat = self.current_seat()
        side = self.sides[seat]

        # Rebuild the landing path from the structured action.
        from_sq, to_sq, moves = action.get("from"), action.get("to"), action.get("moves")
        if moves is None:
            moves = []
        if not isinstance(moves, list):
            raise IllegalMove("invalid_action", "'moves' must be a list or null")
        try:
            path = [self._rc(from_sq), self._rc(to_sq)]
            for mv in moves:
                if not isinstance(mv, dict) or "to" not in mv:
                    raise ValueError
                path.append(self._rc(mv["to"]))
        except (ValueError, TypeError, KeyError):
            raise IllegalMove("invalid_action", "malformed coordinates in action")

        chains = self._capture_chains(side, self.board)
        if chains:
            if path not in chains:
                raise IllegalMove("illegal_move", f"not a legal capture chain {action}")
            is_capture = True
        else:
            simple = self._simple_moves(side, self.board)
            if len(path) != 2 or path not in [[f, t] for f, t in simple]:
                raise IllegalMove("illegal_move", f"illegal move {action}")
            is_capture = False

        # Apply each segment in order.
        piece = None
        for i in range(1, len(path)):
            lr, lc = path[i - 1]
            rr, rc = path[i]
            piece = self.board[lr][lc]
            if is_capture:
                dr = (rr - lr) // abs(rr - lr) if rr != lr else 0
                dc = (rc - lc) // abs(rc - lc) if rc != lc else 0
                r2, c2 = lr + dr, lc + dc
                while (r2, c2) != (rr, rc):
                    if self.board[r2][c2] is not None:
                        self.board[r2][c2] = None
                        break
                    r2 += dr
                    c2 += dc
            self.board[lr][lc] = None
            self.board[rr][rc] = piece

        # Promote a man that reached the far rank.
        final_r, final_c = path[-1]
        if piece in ("b", "w"):
            if (piece == "b" and final_r == SIZE - 1) or (piece == "w" and final_r == 0):
                self.board[final_r][final_c] = "B" if piece == "b" else "W"

        self.move_count += 1
        self.last_move = {"seat": seat, "from": from_sq, "to": to_sq, "moves": moves,
                          "move": self.move_count}
        self.turn += 1
        self._note_move(seat)

        # Win when the opponent has no pieces or no legal move.
        if not self._player_has_move(self.sides[self.current_seat()], self.board):
            self._set_result([seat])

    # ---- shared -----------------------------------------------------------
    def _piece_count(self, side: str) -> int:
        return sum(1 for r in range(SIZE) for c in range(SIZE)
                   if _color_of(self.board[r][c]) == side)

    def get_scores(self) -> dict:
        return {"black": self._piece_count("b"), "white": self._piece_count("w"),
                "moves": self.move_count}

    def _board_rendered(self) -> list:
        # Render from Black's perspective: rank 8 (Black's far side) on top,
        # so Black's home ranks appear at the bottom of the draw.
        return [[self.board[r][c] if self.board[r][c] is not None else ""
                 for c in range(SIZE)] for r in range(SIZE - 1, -1, -1)]

    def get_render_data(self) -> dict:
        return {"board": self._board_rendered(), "turn": self.current_seat(),
                "last_move": self.last_move}

    def observe(self, perspective: int | None = None) -> dict:
        if self.is_terminal():
            summary = f"Game over — {self.summary()}"
        else:
            summary = f"Checkers — move {self.move_count}; player {self.current_seat()} to move"
        return {
            "state": {"board": self._board_rendered(), "rows": SIZE, "cols": SIZE,
                      "turn": self.current_seat(), "sides": self.sides},
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": summary,
            "last_move": self.last_move,
            "time": None,
        }

    def summary(self) -> str:
        if not self.is_terminal():
            return f"Checkers in progress"
        w = self.get_winner()
        if w is None:
            return "Checkers drawn"
        return f"Checkers won by player {w[0]}"


CATALOG = {
    "game": "checkers",
    "mode": "turnbased",
    "name": "Checkers",
    "players": {"min": 2, "max": 2},
    "players_before_start": 2,
    "elo_ranked": True,
    "blurb": "Jump 'em and crown 'em.",
}
