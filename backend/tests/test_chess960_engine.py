"""Fischer Random rules, reproducibility, castling, and lifecycle tests."""

from __future__ import annotations

import asyncio
import io

import chess
import chess.pgn
import pytest
from pydantic import ValidationError

from app.db import get_sessionmaker, init_db
from app.engine.games.chess960 import Chess960
from app.engine.match_manager import MatchManager
from app.models import Agent, Match

SEATS = [{"seat": 0}, {"seat": 1}]


def _chess960(seed: int = 1, **config: object) -> Chess960:
    return Chess960(config=config, seed=seed, seats=list(SEATS))


def test_all_numbered_positions_are_unique_and_obey_back_rank_invariants() -> None:
    placements: set[str] = set()
    for position in range(960):
        engine = _chess960(seed=position)
        placements.add(engine.board.board_fen())
        white_back_rank = [engine.board.piece_at(square) for square in chess.SQUARES[:8]]
        bishop_files = [
            file
            for file, piece in enumerate(white_back_rank)
            if piece is not None and piece.piece_type == chess.BISHOP
        ]
        rook_files = [
            file
            for file, piece in enumerate(white_back_rank)
            if piece is not None and piece.piece_type == chess.ROOK
        ]
        king_file = next(
            file
            for file, piece in enumerate(white_back_rank)
            if piece is not None and piece.piece_type == chess.KING
        )
        assert bishop_files[0] % 2 != bishop_files[1] % 2
        assert rook_files[0] < king_file < rook_files[1]
        assert engine.board.chess960 is True
        assert engine.chess960_position == position

    assert len(placements) == 960


@pytest.mark.parametrize("seed", [0, 1, 518, 959, 960, 2**63 - 1])
def test_seeded_position_is_stable_across_reset_and_replay(seed: int) -> None:
    engine = _chess960(seed=seed)
    initial_fen = engine.board.fen()
    assert engine.chess960_position == seed % 960
    assert engine.observe()["state"]["chess960_position"] == seed % 960
    assert engine.get_render_data()["chess960_position"] == seed % 960

    engine.reset()
    replay = _chess960(seed=seed)
    assert engine.board.fen() == replay.board.fen() == initial_fen


def test_chess960_castling_uses_advertised_king_to_rook_action() -> None:
    engine = _chess960(start_fen="rk5r/8/8/8/8/8/8/RK5R w HAha - 0 1")
    kingside = {"from": "b1", "to": "h1", "promotion": None}
    queenside = {"from": "b1", "to": "a1", "promotion": None}
    legal = engine.get_legal_actions(0)
    assert kingside in legal and queenside in legal

    engine.apply_action(kingside)

    assert engine.board.king(chess.WHITE) == chess.G1
    assert engine.board.piece_at(chess.F1) == chess.Piece(chess.ROOK, chess.WHITE)
    assert engine.board.piece_at(chess.A1) == chess.Piece(chess.ROOK, chess.WHITE)
    assert engine.last_move["san"] == "O-O"


@pytest.mark.parametrize(
    "config",
    [
        {"chess960_position": -1},
        {"chess960_position": 960},
        {"chess960_position": True},
        {"chess960_position": "518"},
        {"unknown_variant_rule": True},
    ],
)
def test_chess960_rejects_invalid_admin_config(config: dict) -> None:
    with pytest.raises(ValidationError):
        Chess960(config=config, seed=1, seats=list(SEATS))


def test_position_518_retains_full_chess_terminal_rules() -> None:
    engine = _chess960(chess960_position=518)
    for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
        engine.apply_action({"from": uci[:2], "to": uci[2:]})

    assert engine.is_terminal()
    assert engine.get_winner() == [1]
    assert engine.summary() == "Fischer Random Chess — Black wins (checkmate)"


async def test_manager_persists_variant_pgn_and_reconstructible_seed() -> None:
    await init_db()
    manager = MatchManager()
    async with get_sessionmaker()() as session:
        white = Agent(display_name="960-white", api_key_hash="h-960-white", stats={})
        black = Agent(display_name="960-black", api_key_hash="h-960-black", stats={})
        session.add_all([white, black])
        await session.commit()
        match = await manager.create(white, "chess960", {}, session)
        match = await manager.join(match, black, session)
        match_id = match.id
        engine = manager._engines[match_id]
        expected_initial_fen = engine.pgn_initial_fen
        expected_position = engine.chess960_position

        first_move = next(action for action in engine.get_legal_actions(0) if "from" in action)
        await manager.submit_action(match, white, first_move)
        for _ in range(200):
            if engine.move_count == 1:
                break
            await asyncio.sleep(0.01)
        assert engine.move_count == 1

        await manager.submit_action(match, black, {"resign": True})
        task = manager._tasks.get(match_id)
        if task is not None:
            await asyncio.wait_for(task, timeout=5)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        assert finished is not None and finished.status == "finished"
        assert finished.notation is not None
        game = chess.pgn.read_game(io.StringIO(finished.notation))
        assert game is not None and game.errors == []
        assert game.headers["Variant"] == "Chess960"
        assert game.headers["SetUp"] == "1"
        assert game.headers["FEN"] == expected_initial_fen
        assert game.board().chess960 is True
        replay = Chess960(finished.config, finished.seed, list(finished.players))
        assert replay.chess960_position == expected_position
        assert replay.pgn_initial_fen == expected_initial_fen
