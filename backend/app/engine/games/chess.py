"""Chess — 2-player turn-based engine (spec §8.2).

Rules are delegated to `python-chess` (perft-validated against reference move
generators), so the game is exactly FIDE chess: full legal move generation
(pins, castling rights and castling through check, en passant incl. the rare
pin cases), promotion to q/r/b/n, checkmate, stalemate, insufficient material,
and the draw rules. Draws that FIDE makes claimable (threefold repetition,
fifty-move) are auto-adjudicated here — agents have no claim UI — alongside the
automatic ones (fivefold, seventy-five-move).

Seat 0 is always White, seat 1 is always Black. Actions are UCI dicts:

    {"from": "e2", "to": "e4", "promotion": null}
    {"from": "a7", "to": "a8", "promotion": "q"}   # any of q/r/b/n
    {"resign": true}                                # current seat resigns

A promotion move submitted without "promotion" defaults to queen (documented
convenience, matches the pre-library behavior).

Deterministic given (config, seed, seats): no randomness is used during play.
Optional config ``start_fen`` sets a custom starting position (testing,
variants, puzzles); seat 0 still maps to White regardless of side to move.
"""
from __future__ import annotations

from typing import Any

import chess

from app.engine.base import BaseGame, IllegalMove

_PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}


class Chess(BaseGame):
    mode = "turnbased"
    name = "chess"
    CATALOG = {
        "title": "Chess",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Full FIDE rules chess. UCI-style moves.",
    }
    CONFIG_DEFAULTS = {
        "players": 2,
        "players_before_start": 2,
        "time_control": {"base_sec": 600, "increment_sec": 5, "enabled": True},
        "start_fen": None,
    }

    # ---- state -----------------------------------------------------------
    def reset(self) -> None:
        fen = self.config.get("start_fen")
        try:
            self.board = chess.Board(fen) if fen else chess.Board()
        except ValueError as exc:
            raise ValueError(f"invalid start_fen: {exc}") from exc
        self.move_count = 0
        self.last_move: dict | None = None

    # ---- turn-based ------------------------------------------------------
    def current_seat(self) -> int:
        return 0 if self.board.turn == chess.WHITE else 1

    def get_legal_actions(self, seat: int) -> list[dict]:
        if self.is_terminal() or seat != self.current_seat():
            return []
        actions = [
            {
                "from": chess.square_name(m.from_square),
                "to": chess.square_name(m.to_square),
                "promotion": chess.piece_symbol(m.promotion) if m.promotion else None,
            }
            for m in self.board.legal_moves
        ]
        actions.append({"resign": True})
        return actions

    def apply_action(self, action: Any) -> None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be {'from','to','promotion'} or {'resign': true}")
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        seat = self.current_seat()

        if action.get("resign") is True:
            self._note_move(seat)
            self._set_result([1 - seat])
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            return

        frs, tos = action.get("from"), action.get("to")
        promo = action.get("promotion")
        if not isinstance(frs, str) or not isinstance(tos, str):
            raise IllegalMove("invalid_square", "from/to must be squares like 'e2'")
        if promo is not None and promo not in ("q", "r", "b", "n"):
            raise IllegalMove("invalid_promotion", "promotion must be one of q,r,b,n")

        uci = frs.lower() + tos.lower() + (promo or "")
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise IllegalMove("invalid_square", f"bad square in '{uci}'")

        if move not in self.board.legal_moves:
            if promo is None:
                # convenience: a promotion move submitted without the key
                # defaults to queen, if that promotion exists
                try:
                    qmove = chess.Move.from_uci(uci + "q")
                except ValueError:
                    qmove = None
                if qmove is not None and qmove in self.board.legal_moves:
                    move = qmove
                else:
                    raise IllegalMove("illegal_move", f"illegal move {frs}{tos}")
            else:
                raise IllegalMove("illegal_move", f"illegal move {frs}{tos}")

        san = self.board.san(move)  # before push
        self.board.push(move)
        self.last_move = {
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
            "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
            "san": san,
            "seat": seat,
            "move": self.move_count + 1,
        }
        self._note_move(seat)

        # terminal adjudication — claimable draws auto-claimed (no claim UI)
        outcome = self.board.outcome(claim_draw=True)
        if outcome is not None:
            if outcome.winner is None:
                self._set_result(None)  # draw (see outcome.termination)
            else:
                self._set_result([0 if outcome.winner == chess.WHITE else 1])

    # ---- shared -----------------------------------------------------------
    def _material(self) -> dict:
        white = black = 0
        for _, piece in self.board.piece_map().items():
            value = _PIECE_VALUES.get(piece.piece_type, 0)  # kings: 0
            if piece.color == chess.WHITE:
                white += value
            else:
                black += value
        return {"white": white, "black": black}

    def get_scores(self) -> dict:
        return {"material": self._material(), "moves": self.move_count}

    def get_render_data(self) -> dict:
        return {
            "fen": self.board.fen(),
            "turn": self.current_seat(),
            "check": self.board.is_check(),
            "legal_count": 0 if self.is_terminal() else self.board.legal_moves.count(),
            "last_move": self.last_move,
        }

    def summary(self) -> str:
        if self.is_terminal():
            outcome = self.board.outcome(claim_draw=True)
            if self.last_move and self.last_move.get("event") == "resign":
                return f"Chess — player {self.last_move['seat']} resigns; player {1 - self.last_move['seat']} wins"
            if outcome is None:
                return "Chess — over"
            if outcome.winner is None:
                return f"Chess — draw ({outcome.termination.name.lower().replace('_', ' ')})"
            who = "White" if outcome.winner == chess.WHITE else "Black"
            return f"Chess — {who} wins ({outcome.termination.name.lower().replace('_', ' ')})"
        side = "White" if self.board.turn == chess.WHITE else "Black"
        check = " — check!" if self.board.is_check() else ""
        return f"Chess — move {self.board.fullmove_number}; {side} to move{check}"

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "fen": self.board.fen(),
                "turn": self.current_seat(),
                "check": self.board.is_check(),
                "move_number": self.board.fullmove_number,
                "castling": self.board.castling_xfen(),
                "ep_square": (chess.square_name(self.board.ep_square)
                              if self.board.ep_square is not None else None),
            },
            "legal_actions": self.get_legal_actions(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }
