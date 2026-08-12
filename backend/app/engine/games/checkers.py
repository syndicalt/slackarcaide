"""English draughts (American checkers) on an 8x8 board.

This engine implements the WCDF English rules rather than mixing in rules from
international draughts: men move and capture forward only, kings move and jump
one square in either direction, captures are compulsory, and crowning ends the
turn.  Capture sequences are submitted as atomic jumps so the engine can expose
the exact required continuation after each action.

Seat 0 has the dark pieces, moves first, and advances from rank 1 toward rank 8.
Actions are exact dictionaries::

    {"from": "c3", "to": "e5"}
    {"resign": True}

The no-progress draw counter follows the WCDF 40-move condition: it resets when
a man advances or a piece is captured and otherwise counts completed player
turns. The default of 80 therefore represents 40 turns per seat under normal
alternation.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

_BOARD_SIZE = 8
_SQUARE_RE = re.compile(r"^[a-h][1-8]$")
_FORWARD = {0: 1, 1: -1}
_KING_ROW = {0: 7, 1: 0}


class CheckersTimeControl(BaseModel):
    """Admin-controlled Fischer clock settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=600, ge=1, le=86_400)
    increment_sec: int = Field(default=5, ge=0, le=3_600)
    enabled: bool = True


class CheckersConfig(BaseModel):
    """Validated configuration for a bounded two-player match."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    time_control: CheckersTimeControl = Field(default_factory=CheckersTimeControl)
    no_progress_halfmoves: int = Field(default=80, ge=2, le=1_000)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


@dataclass(frozen=True, slots=True)
class _Piece:
    seat: int
    king: bool = False


type _Square = tuple[int, int]


def _square_name(square: _Square) -> str:
    file_index, rank_index = square
    return f"{chr(97 + file_index)}{rank_index + 1}"


def _parse_square(value: str) -> _Square:
    return ord(value[0]) - 97, int(value[1]) - 1


class Checkers(BaseGame):
    mode = "turnbased"
    name = "checkers"
    CATALOG = {
        "title": "Checkers",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "English draughts with mandatory captures and short-range kings.",
    }
    CONFIG_MODEL = CheckersConfig
    CONFIG_DEFAULTS = CheckersConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.board: dict[_Square, _Piece] = {}
        for rank_index in range(3):
            for file_index in range(_BOARD_SIZE):
                if (file_index + rank_index) % 2 == 0:
                    self.board[(file_index, rank_index)] = _Piece(0)
        for rank_index in range(5, _BOARD_SIZE):
            for file_index in range(_BOARD_SIZE):
                if (file_index + rank_index) % 2 == 0:
                    self.board[(file_index, rank_index)] = _Piece(1)

        self.turn = 0
        self.move_count = 0
        self.no_progress_halfmoves = 0
        self.forced_from: _Square | None = None
        self._pending_captures: set[_Square] = set()
        self._turn_path: list[_Square] = []
        self.last_move: dict[str, Any] | None = None
        self._end_reason: str | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self.turn

    @staticmethod
    def _inside(square: _Square) -> bool:
        return all(0 <= coordinate < _BOARD_SIZE for coordinate in square)

    @staticmethod
    def _directions(piece: _Piece) -> tuple[tuple[int, int], ...]:
        if piece.king:
            return ((-1, -1), (1, -1), (-1, 1), (1, 1))
        forward = _FORWARD[piece.seat]
        return ((-1, forward), (1, forward))

    def _captures_from(self, origin: _Square) -> list[tuple[_Square, _Square]]:
        piece = self.board.get(origin)
        if piece is None or origin in self._pending_captures:
            return []
        captures: list[tuple[_Square, _Square]] = []
        for dx, dy in self._directions(piece):
            jumped = (origin[0] + dx, origin[1] + dy)
            destination = (origin[0] + 2 * dx, origin[1] + 2 * dy)
            jumped_piece = self.board.get(jumped)
            if (
                self._inside(destination)
                and destination not in self.board
                and jumped_piece is not None
                and jumped_piece.seat != piece.seat
                and jumped not in self._pending_captures
            ):
                captures.append((destination, jumped))
        return captures

    def _all_captures(self, seat: int) -> list[tuple[_Square, _Square, _Square]]:
        captures: list[tuple[_Square, _Square, _Square]] = []
        origins = [self.forced_from] if self.forced_from is not None else sorted(self.board)
        for origin in origins:
            if origin is None:
                continue
            piece = self.board.get(origin)
            if piece is None or piece.seat != seat or origin in self._pending_captures:
                continue
            for destination, jumped in self._captures_from(origin):
                captures.append((origin, destination, jumped))
        return captures

    def _quiet_moves(self, seat: int) -> list[tuple[_Square, _Square]]:
        moves: list[tuple[_Square, _Square]] = []
        for origin in sorted(self.board):
            piece = self.board[origin]
            if piece.seat != seat or origin in self._pending_captures:
                continue
            for dx, dy in self._directions(piece):
                destination = (origin[0] + dx, origin[1] + dy)
                if self._inside(destination) and destination not in self.board:
                    moves.append((origin, destination))
        return moves

    def _board_actions(self, seat: int) -> list[dict[str, str]]:
        captures = self._all_captures(seat)
        if captures:
            return [
                {"from": _square_name(origin), "to": _square_name(destination)}
                for origin, destination, _jumped in captures
            ]
        if self.forced_from is not None:
            return []
        return [
            {"from": _square_name(origin), "to": _square_name(destination)}
            for origin, destination in self._quiet_moves(seat)
        ]

    def get_legal_actions(self, seat: int) -> list[dict[str, Any]]:
        if self.is_terminal() or isinstance(seat, bool) or seat != self.current_seat():
            return []
        return [*self._board_actions(seat), {"resign": True}]

    def _remove_pending_captures(self) -> None:
        for square in self._pending_captures:
            self.board.pop(square, None)
        self._pending_captures.clear()

    def _has_board_move(self, seat: int) -> bool:
        return bool(self._all_captures(seat) or self._quiet_moves(seat))

    def _complete_turn(self, seat: int, made_progress: bool) -> None:
        self._remove_pending_captures()
        self.forced_from = None
        self._turn_path = []
        self.no_progress_halfmoves = 0 if made_progress else self.no_progress_halfmoves + 1
        self.turn = 1 - seat
        self._note_move(seat)

        has_piece = any(piece.seat == self.turn for piece in self.board.values())
        if not has_piece or not self._has_board_move(self.turn):
            self._end_reason = "no legal moves"
            self._set_result([seat])
        elif self.no_progress_halfmoves >= self.config["no_progress_halfmoves"]:
            self._end_reason = "no progress"
            self._set_result(None)

    @staticmethod
    def _validated_action(action: Any) -> tuple[str, str] | None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be {'from','to'} or {'resign': true}")
        if set(action) == {"resign"}:
            if action["resign"] is True:
                return None
            raise IllegalMove("invalid_action", "resign must be true")
        if set(action) != {"from", "to"}:
            raise IllegalMove("invalid_action", "action must contain exactly 'from' and 'to'")
        origin, destination = action["from"], action["to"]
        if (
            not isinstance(origin, str)
            or not isinstance(destination, str)
            or _SQUARE_RE.fullmatch(origin) is None
            or _SQUARE_RE.fullmatch(destination) is None
        ):
            raise IllegalMove("invalid_square", "from/to must be lowercase squares like 'c3'")
        return origin, destination

    def apply_action(self, action: Any) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        validated = self._validated_action(action)

        seat = self.current_seat()
        remaining = self.clock_ms(seat)
        if remaining is not None and remaining <= 0:
            raise IllegalMove("clock_expired", "clock expired before action")

        if validated is None:
            self._remove_pending_captures()
            self.forced_from = None
            self._turn_path = []
            self._note_move(seat)
            self._end_reason = "resignation"
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            self._set_result([1 - seat])
            return

        origin_name, destination_name = validated
        legal_actions = self._board_actions(seat)
        if {"from": origin_name, "to": destination_name} not in legal_actions:
            if self.forced_from is not None:
                raise IllegalMove(
                    "must_continue_capture",
                    f"capture sequence must continue from {_square_name(self.forced_from)}",
                )
            if self._all_captures(seat):
                raise IllegalMove("capture_required", "a capture is mandatory")
            raise IllegalMove("illegal_move", f"illegal move {origin_name}{destination_name}")

        origin = _parse_square(origin_name)
        destination = _parse_square(destination_name)
        piece = self.board.pop(origin)
        was_man = not piece.king
        capture_square: _Square | None = None
        if abs(destination[0] - origin[0]) == 2:
            capture_square = (
                (origin[0] + destination[0]) // 2,
                (origin[1] + destination[1]) // 2,
            )
            self._pending_captures.add(capture_square)

        promoted = was_man and destination[1] == _KING_ROW[seat]
        self.board[destination] = _Piece(seat=seat, king=piece.king or promoted)
        if not self._turn_path:
            self._turn_path = [origin]
        self._turn_path.append(destination)
        self.last_move = {
            "from": origin_name,
            "to": destination_name,
            "capture": _square_name(capture_square) if capture_square is not None else None,
            "promoted": promoted,
            "seat": seat,
            "move": self.move_count + 1,
            "sequence": [_square_name(square) for square in self._turn_path],
        }

        # WCDF 1.16: reaching the king-row crowns the man and completes the turn.
        if capture_square is not None and not promoted and self._captures_from(destination):
            self.forced_from = destination
            # The host uses move_count as the action-ledger sequence number.
            # Keep the clock running for the same seat; the Fischer increment
            # is awarded only when the full capture turn is complete.
            self.move_count += 1
            return

        self._complete_turn(seat, made_progress=capture_square is not None or was_man)

    def _piece_counts(self) -> tuple[list[int], list[int]]:
        pieces = [0, 0]
        kings = [0, 0]
        for square, piece in self.board.items():
            if square in self._pending_captures:
                continue
            pieces[piece.seat] += 1
            kings[piece.seat] += int(piece.king)
        return pieces, kings

    def get_scores(self) -> dict[str, Any]:
        pieces, kings = self._piece_counts()
        return {
            "pieces": pieces,
            "kings": kings,
            "moves": self.move_count,
            "no_progress_halfmoves": self.no_progress_halfmoves,
        }

    def _serialized_pieces(self) -> list[dict[str, Any]]:
        return [
            {
                "square": _square_name(square),
                "seat": piece.seat,
                "king": piece.king,
                "captured": square in self._pending_captures,
            }
            for square, piece in sorted(self.board.items())
        ]

    def get_render_data(self) -> dict[str, Any]:
        return {
            "size": _BOARD_SIZE,
            "pieces": self._serialized_pieces(),
            "turn": self.current_seat(),
            "forced_from": _square_name(self.forced_from) if self.forced_from else None,
            "last_move": deepcopy(self.last_move),
        }

    def summary(self) -> str:
        if self.is_terminal():
            if self.get_winner() is None:
                return "Checkers — draw (no progress)"
            winner = self.get_winner()[0]
            side = "Black" if winner == 0 else "White"
            if self._end_reason == "resignation":
                return f"Checkers — {side} wins by resignation"
            return f"Checkers — {side} wins; opponent has no legal moves"

        side = "Black" if self.turn == 0 else "White"
        if self.forced_from is not None:
            return f"Checkers — {side} must continue from {_square_name(self.forced_from)}"
        pieces, _kings = self._piece_counts()
        return f"Checkers — {side} to move; {pieces[0]}-{pieces[1]} pieces"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        return {
            "state": {
                "pieces": self._serialized_pieces(),
                "turn": self.current_seat(),
                "forced_from": _square_name(self.forced_from) if self.forced_from else None,
                "no_progress_halfmoves": self.no_progress_halfmoves,
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": deepcopy(self.last_move),
            "time": self.clock_state(),
        }
