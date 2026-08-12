"""Full match lifecycle test: a pong match driven to a win must exit cleanly.

Asserts the whole terminal path end-to-end (in-memory SQLite, real manager):
  * loop task terminates once a player reaches win_points;
  * the match row is persisted: status=finished, ended_at, result with winner
    and scores, tick count;
  * ratings are written for both players (700 START_ELO, +-24 provisional);
  * manager state (engine/buffers/ledger/task) is cleaned up;
  * the FINAL published frame carries the finished board — regression for the
    bug where _finish_cleanup cancelled the loop task mid-_finish, so the
    terminal publish was silently cancelled and the last frame spectators saw
    was the engine-less placeholder ("Match in finished", no render).
"""
import os

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import asyncio

import pytest
from sqlalchemy import select

from app.db import get_sessionmaker, init_db
from app.engine import match_manager as mm
from app.engine.match_manager import MatchManager
from app.models import Agent, Match, Rating


async def test_ranked_match_strips_start_fen():
    """Ranked games must not accept custom start positions (Elo farming)."""
    await init_db()
    mgr = MatchManager()
    async with get_sessionmaker()() as s:
        a = Agent(display_name="fen-guard", api_key_hash="h-fen-guard", stats={})
        s.add(a)
        await s.commit()
        m = await mgr.create(
            a, "chess", "turnbased",
            {"start_fen": "7k/8/8/6Q1/8/5K2/8/8 w - - 0 1"},
            s,
        )
        assert "start_fen" not in m.config


async def test_pong_match_clean_exit_on_win(monkeypatch):
    await init_db()

    published: list[tuple[str, dict]] = []

    async def fake_publish(channel, payload):
        published.append((channel, payload))

    monkeypatch.setattr(mm, "publish", fake_publish)

    mgr = MatchManager()
    async with get_sessionmaker()() as s:
        a1 = Agent(display_name="exit-a", api_key_hash="h-exit-a", stats={})
        a2 = Agent(display_name="exit-b", api_key_hash="h-exit-b", stats={})
        s.add_all([a1, a2])
        await s.commit()
        m = await mgr.create(
            a1, "pong", "realtime",
            {"win_points": 1, "serve_delay_ticks": 0, "tick_rate": 200},
            s,
        )
        m = await mgr.join(m, a2, s)  # second join auto-starts the match
        mid = m.id
        assert m.status == "running"
        # pin both paddles to the top corner so the centered serve sails past
        # (two static centered paddles rally the serve back and forth forever)
        mgr._engines[mid].paddles[0] = 0.0
        mgr._engines[mid].paddles[1] = 0.0
        mgr._engines[mid].vys[0] = 0.0
        mgr._engines[mid].vys[1] = 0.0

    task = mgr._tasks[mid]
    await asyncio.wait_for(task, timeout=15)

    async with get_sessionmaker()() as s:
        fin = await s.get(Match, mid)
        assert fin.status == "finished"
        assert fin.ended_at is not None
        assert fin.result["reason"] == "finished"
        assert fin.result["winner_seats"] in ([0], [1])
        total = fin.result["scores"]["left"] + fin.result["scores"]["right"]
        assert total == 1  # first to 1: exactly one point was played
        assert fin.tick_or_move_count > 0

        rows = (await s.scalars(select(Rating).where(Rating.game == "pong"))).all()
        by_agent = {r.agent_id: r for r in rows}
        winner_id = fin.result["winner_agents"][0]
        import uuid as _uuid

        winner = by_agent[_uuid.UUID(winner_id)]
        loser = next(r for a, r in by_agent.items() if str(a) != winner_id)
        assert winner.elo == 724 and winner.wins == 1 and winner.games_played == 1
        assert loser.elo == 676 and loser.losses == 1

    # manager state fully cleaned
    assert mid not in mgr._engines
    assert mid not in mgr._tasks
    assert mid not in mgr._buffers
    assert mid not in mgr._ledgers

    # the terminal WS frame carries the finished board, not the placeholder
    frames = [p for c, p in published if c == f"match:{mid}"]
    assert frames, "no frames published"
    final = frames[-1]
    assert final["status"] == "finished"
    assert final["render"]["scores"] in ([1, 0], [0, 1])
    assert "ball" in final["render"]
