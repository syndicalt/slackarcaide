"""Chess engine tests — the engine must be exactly FIDE chess.

Uses python-chess as the rules oracle plus targeted positions for every rule
an agent can hit: legal play, captures, promotion (all four pieces + the
queen-default convenience), castling, en passant, check/checkmate, stalemate,
insufficient material, repetition/fifty-move draws, resignation, and the
ratings draw path (regression: drawn ranked matches used to crash _finish).
"""
import os

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker, init_db
from app.engine.base import IllegalMove
from app.engine.games.chess import Chess
from app.models import Agent, Rating
from app.services.ratings import update_ratings

SEATS = [{"seat": 0}, {"seat": 1}]


def _chess(**config) -> Chess:
    return Chess(config=config, seed=1, seats=list(SEATS))


def _play(e: Chess, *ucis: str) -> None:
    for u in ucis:
        e.apply_action({"from": u[:2], "to": u[2:4], "promotion": u[4:] or None})


def test_opening_move_and_legal_actions_shape():
    e = _chess()
    assert e.current_seat() == 0
    legal = e.get_legal_actions(0)
    assert len(legal) == 21  # 20 moves + resign
    assert {"from": "e2", "to": "e4", "promotion": None} in legal
    e.apply_action({"from": "e2", "to": "e4"})
    assert e.current_seat() == 1
    assert e.board.fen().startswith("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b")
    assert e.last_move["san"] == "e4"


def test_illegal_moves_rejected():
    e = _chess()
    with pytest.raises(IllegalMove):
        e.apply_action({"from": "e2", "to": "e5"})  # too far
    with pytest.raises(IllegalMove):
        e.apply_action({"from": "e7", "to": "e5"})  # black piece on white's turn
    with pytest.raises(IllegalMove):
        e.apply_action({"from": "e9", "to": "e4"})  # off board
    with pytest.raises(IllegalMove):
        e.apply_action({"from": "e2"})  # missing 'to'
    with pytest.raises(IllegalMove):
        e.apply_action("e2e4")  # not a dict
    assert e.board.fullmove_number == 1 and e.current_seat() == 0  # state untouched


def test_capture_and_material_score():
    e = _chess()
    _play(e, "e2e4", "d7d5", "e4d5")  # white captures on d5
    scores = e.get_scores()
    assert scores["material"] == {"white": 39, "black": 38}
    assert e.last_move["san"] == "exd5"


def test_fools_mate_checkmate():
    e = _chess()
    _play(e, "f2f3", "e7e5", "g2g4", "d8h4")
    assert e.is_terminal()
    assert e.get_winner() == [1]  # Black
    assert "Black wins" in e.summary()
    with pytest.raises(IllegalMove):
        e.apply_action({"from": "a2", "to": "a3"})  # game over


def test_castling_both_sides():
    e = _chess()
    _play(e, "e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "e1g1")
    assert e.board.fen().split()[0] == "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1"


def test_en_passant():
    e = _chess()
    _play(e, "e2e4", "a7a6", "e4e5", "d7d5", "e5d6")  # exd6 e.p.
    assert e.board.fen().split()[0] == "rnbqkbnr/1pp1pppp/p2P4/8/8/8/PPPP1PPP/RNBQKBNR"


def test_promotion_all_pieces_and_queen_default():
    # white pawn on a7, black king far away
    fen = "8/P7/8/8/8/8/k6K/8 w - - 0 1"
    for promo, piece in (("q", "Q"), ("r", "R"), ("b", "B"), ("n", "N")):
        e = _chess(start_fen=fen)
        e.apply_action({"from": "a7", "to": "a8", "promotion": promo})
        assert e.board.piece_at(56).symbol() == piece
    # omitted promotion key defaults to queen
    e = _chess(start_fen=fen)
    e.apply_action({"from": "a7", "to": "a8"})
    assert e.board.piece_at(56).symbol() == "Q"


def test_stalemate_is_draw():
    # White to move: Qg5-g6 leaves Black (Kh8) with no legal move and no check
    e = _chess(start_fen="7k/8/8/6Q1/8/5K2/8/8 w - - 0 1")
    e.apply_action({"from": "g5", "to": "g6"})
    assert e.is_terminal()
    assert e.get_winner() is None
    assert "stalemate" in e.summary()


def test_insufficient_material_draw():
    e = _chess(start_fen="8/8/4k3/8/8/3NK3/8/8 w - - 0 1")
    e.apply_action({"from": "d3", "to": "e5"})  # any knight move; K+N vs K
    assert e.is_terminal()
    assert e.get_winner() is None  # draw


def test_resign():
    e = _chess()
    e.apply_action({"resign": True})
    assert e.is_terminal()
    assert e.get_winner() == [1]  # white (seat 0) resigned
    assert "resign" in e.summary()


def test_threefold_repetition_auto_draw():
    e = _chess()
    # FIDE 9.2: a draw is claimable when the third repetition is ABOUT to occur,
    # so the shuffle ends one ply before the literal third occurrence
    _play(e, "g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1")
    assert e.is_terminal()
    assert e.get_winner() is None
    assert "repetition" in e.summary()


def test_fifty_move_rule_auto_draw():
    # halfmove clock 99 via FEN; one quiet rook move hits 100 -> draw
    e = _chess(start_fen="8/7r/8/8/8/7k/8/R3K3 w - - 99 50")
    e.apply_action({"from": "a1", "to": "a2"})
    assert e.is_terminal()
    assert e.get_winner() is None
    assert "fifty" in e.summary()


async def test_draw_updates_ratings_without_crash():
    """Regression: _finish passes winner_seats=[] for draws; update_ratings
    used to IndexError on it, stranding every drawn ranked match."""
    await init_db()
    async with get_sessionmaker()() as s:
        a = Agent(display_name="draw-a", api_key_hash="h-draw-a", stats={})
        b = Agent(display_name="draw-b", api_key_hash="h-draw-b", stats={})
        s.add_all([a, b])
        await s.commit()
        await update_ratings(s, "chess", [a.id, b.id], [])  # draw as _finish passes it
        rows = (await s.scalars(select(Rating).where(Rating.game == "chess"))).all()
        assert len(rows) == 2
        for r in rows:
            assert r.elo == 700  # equal ratings draw: no change
            assert r.draws == 1 and r.games_played == 1
