"""PGN recording: finished chess matches persist standards-compliant notation.

Covers:
  * SAN is captured in the ledger and a full PGN (headers incl. BOTH player
    agent ids, result, wrapped movetext) is stored on the match row at finish;
  * the PGN round-trips through python-chess's parser (validity proof);
  * non-chess games simply leave notation NULL.
"""
import os

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import io

import chess.pgn
import pytest

from app.db import get_sessionmaker, init_db
from app.models import Agent, Match
from app.services.notation import build_pgn


class _FakeMatch:
    id = "11111111-2222-3333-4444-555555555555"
    config: dict = {}
    players = [
        {"agent_id": "aaaaaaaa-0000-0000-0000-000000000001", "seat": 0, "name": "Whitey"},
        {"agent_id": "bbbbbbbb-0000-0000-0000-000000000002", "seat": 1, "name": "Blackie"},
    ]


def test_pgn_headers_and_movetext():
    pgn = build_pgn(_FakeMatch(), ["f3", "e5", "g4", "Qh4#"], [1])
    assert '[White "Whitey"]' in pgn
    assert '[Black "Blackie"]' in pgn
    assert '[WhiteAgentId "aaaaaaaa-0000-0000-0000-000000000001"]' in pgn
    assert '[BlackAgentId "bbbbbbbb-0000-0000-0000-000000000002"]' in pgn
    assert '[Result "0-1"]' in pgn
    assert "1. f3 e5 2. g4 Qh4# 0-1" in pgn


def test_pgn_roundtrips_through_python_chess():
    sans = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O", "Nf6"]
    pgn = build_pgn(_FakeMatch(), sans, [])
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    board = game.board()
    out = []
    for m in game.mainline_moves():
        out.append(board.san(m))
        board.push(m)
    assert out == sans
    assert game.headers["Result"] == "1/2-1/2"


async def test_finish_persists_pgn_on_match_row():
    """Integration: drive a Fool's mate through the manager and check the DB."""
    import asyncio

    from app.engine.match_manager import MatchManager

    await init_db()
    mgr = MatchManager()
    async with get_sessionmaker()() as s:
        a1 = Agent(display_name="pgn-w", api_key_hash="h-pgn-w", stats={})
        a2 = Agent(display_name="pgn-b", api_key_hash="h-pgn-b", stats={})
        s.add_all([a1, a2])
        await s.commit()
        m = await mgr.create(a1, "chess", "turnbased", {}, s)
        m = await mgr.join(m, a2, s)
        mid = m.id

        # fool's mate via the public submit path
        agents = {0: a1, 1: a2}
        for ply in [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]:
            seat = mgr._engines[mid].current_seat()
            await mgr.submit_action(m, agents[seat], {"from": ply[0], "to": ply[1]})
            # wait until the turn loop applies the buffered move (or game ends)
            for _ in range(200):
                eng = mgr._engines.get(mid)
                if eng is None or (
                    isinstance(eng.last_move, dict) and eng.last_move.get("to") == ply[1]
                ):
                    break
                await asyncio.sleep(0.02)

        task = mgr._tasks.get(mid)
        if task is not None:
            await asyncio.wait_for(task, timeout=10)

    async with get_sessionmaker()() as s:
        fin = await s.get(Match, mid)
        assert fin.status == "finished"
        assert fin.notation is not None
        assert "1. f3 e5 2. g4 Qh4# 0-1" in fin.notation
        assert '[White "pgn-w"]' in fin.notation
        assert "[WhiteAgentId" in fin.notation and "[BlackAgentId" in fin.notation
        game = chess.pgn.read_game(io.StringIO(fin.notation))
        assert game is not None and len(list(game.mainline_moves())) == 4
