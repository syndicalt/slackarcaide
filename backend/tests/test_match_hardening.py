"""Adversarial lifecycle, replay, buffering, and rating invariants."""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.matches import (
    MAX_REPLAY_TICKS,
    CreateMatchRequest,
    list_matches,
    replay_match,
)
from app.db import get_sessionmaker, init_db
from app.engine import match_manager as mm
from app.engine.games.chess import Chess
from app.engine.games.pong import Pong
from app.engine.match_manager import MatchManager
from app.engine.registry import normalize_game_config
from app.models import ActionLogEntry, Agent, Match, Rating, RatingEvent
from app.services.ratings import seed_initial_ratings, update_ratings


def _players(*ids: uuid.UUID) -> list[dict]:
    return [
        {"agent_id": str(agent_id), "seat": seat, "side": None, "name": f"p{seat}"}
        for seat, agent_id in enumerate(ids)
    ]


def test_public_create_contract_rejects_admin_fields() -> None:
    assert CreateMatchRequest.model_validate({"game_type": "chess"}).game_type == "chess"
    with pytest.raises(ValidationError):
        CreateMatchRequest.model_validate({"game_type": "pong", "config": {"win_points": 1}})
    with pytest.raises(ValidationError):
        CreateMatchRequest.model_validate({"game_type": "chess", "mode": "turnbased"})


async def test_action_buffers_have_bounded_semantics() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    players = _players(a, b)
    mgr = MatchManager()

    chess_id = uuid.uuid4()
    chess = Chess({}, 1, players)
    chess_match = SimpleNamespace(
        id=chess_id,
        status="running",
        players=players,
        game_type="chess",
        mode="turnbased",
    )
    mgr._engines[chess_id] = chess
    mgr._buffers[chess_id] = {}
    mgr._ledgers[chess_id] = []
    white = SimpleNamespace(id=a)
    await mgr.submit_action(chess_match, white, {"from": "e2", "to": "e4"})
    with pytest.raises(HTTPException) as exc:
        await mgr.submit_action(chess_match, white, {"from": "d2", "to": "d4"})
    assert exc.value.status_code == 409 and exc.value.detail == "action_pending"
    assert len(mgr._buffers[chess_id]) == 1
    mgr._apply_turnbased(chess_match, chess)
    assert not mgr._buffers[chess_id]

    pong_id = uuid.uuid4()
    pong = Pong({"serve_delay_ticks": 10}, 1, players)
    pong_match = SimpleNamespace(
        id=pong_id,
        status="running",
        players=players,
        game_type="pong",
        mode="realtime",
    )
    mgr._engines[pong_id] = pong
    mgr._buffers[pong_id] = {}
    mgr._ledgers[pong_id] = []
    await mgr.submit_action(pong_match, white, {"action": "up"})
    await mgr.submit_action(pong_match, white, {"action": "down"})
    assert len(mgr._buffers[pong_id]) == 1
    mgr._tick_realtime(pong_id, pong)
    assert pong.vys[0] > 0
    assert not mgr._buffers[pong_id]
    assert mgr._ledgers[pong_id][0]["moves"] == {"0": {"action": "down"}}


async def test_realtime_ledger_replays_terminal_state_and_finish_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await init_db()

    async def no_publish(*_args: object) -> None:
        return None

    monkeypatch.setattr(mm, "publish", no_publish)
    mgr = MatchManager()
    async with get_sessionmaker()() as session:
        a = Agent(display_name=f"replay-a-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        b = Agent(display_name=f"replay-b-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        session.add_all([a, b])
        await session.commit()
        players = _players(a.id, b.id)
        config = normalize_game_config("pong", {"win_points": 1, "serve_delay_ticks": 0})
        match = Match(
            game_type="pong",
            mode="realtime",
            status="running",
            config=config,
            seed=7,
            players=players,
        )
        session.add(match)
        await session.commit()
        match_id = match.id

    engine = Pong(config, 7, players)
    mgr._registry[match_id] = match
    mgr._engines[match_id] = engine
    mgr._buffers[match_id] = {0: {"action": {"action": "up"}, "intent": None}}
    mgr._ledgers[match_id] = []
    mgr._lifecycle_locks[match_id] = asyncio.Lock()
    for _ in range(1_000):
        mgr._tick_realtime(match_id, engine)
        if engine.is_terminal():
            break
    assert engine.is_terminal()
    await mgr._finish(match, engine)
    await mgr._finish(match, engine)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        rows = list(
            (
                await session.scalars(
                    select(ActionLogEntry).where(ActionLogEntry.match_id == match_id)
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].agent_id is None
        assert "moves" in rows[0].action_json
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RatingEvent)
                .where(RatingEvent.match_id == match_id)
            )
            == 1
        )
        replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=2_000,
            _rate=None,
            session=session,
        )
        assert replay["frames"][-1]["render"] == finished.result["final_render"]
        ratings = list(
            (
                await session.scalars(
                    select(Rating).where(Rating.agent_id.in_([a.id, b.id]), Rating.game == "pong")
                )
            ).all()
        )
        assert {rating.games_played for rating in ratings} == {1}
    assert match_id not in mgr._registry
    assert match_id not in mgr._lifecycle_locks


async def test_casual_match_does_not_update_ratings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await init_db()

    async def no_publish(*_args: object) -> None:
        return None

    monkeypatch.setattr(mm, "publish", no_publish)
    mgr = MatchManager()
    async with get_sessionmaker()() as session:
        a = Agent(display_name=f"casual-a-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        b = Agent(display_name=f"casual-b-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        session.add_all([a, b])
        await session.commit()
        players = _players(a.id, b.id)
        config = normalize_game_config("pong", {"ranked": False})
        match = Match(
            game_type="pong",
            mode="realtime",
            status="running",
            config=config,
            seed=1,
            players=players,
        )
        session.add(match)
        await session.commit()
    engine = Pong(config, 1, players)
    engine._set_result([0])
    mgr._engines[match.id] = engine
    mgr._buffers[match.id] = {}
    mgr._ledgers[match.id] = []
    await mgr._finish(match, engine)
    async with get_sessionmaker()() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Rating)
                .where(Rating.agent_id.in_([a.id, b.id]), Rating.game == "pong")
            )
            == 0
        )
        assert await session.get(RatingEvent, match.id) is None


async def test_concurrent_rating_updates_are_not_lost() -> None:
    await init_db()
    async with get_sessionmaker()() as session:
        a = Agent(display_name=f"race-a-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        b = Agent(display_name=f"race-b-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        c = Agent(display_name=f"race-c-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
        session.add_all([a, b, c])
        await session.flush()
        for agent in (a, b, c):
            await seed_initial_ratings(session, agent)
        first = Match(
            game_type="pong", mode="realtime", status="finished", config={}, seed=1, players=[]
        )
        second = Match(
            game_type="pong", mode="realtime", status="finished", config={}, seed=2, players=[]
        )
        session.add_all([first, second])
        await session.commit()
        ids = a.id, b.id, c.id, first.id, second.id

    async def apply(match_id: uuid.UUID, seats: list[uuid.UUID]) -> None:
        async with get_sessionmaker()() as session:
            await update_ratings(session, "pong", seats, [0], match_id=match_id)
            await session.commit()

    await asyncio.gather(
        apply(ids[3], [ids[0], ids[1]]),
        apply(ids[4], [ids[0], ids[2]]),
    )
    async with get_sessionmaker()() as session:
        rating = await session.scalar(
            select(Rating).where(Rating.agent_id == ids[0], Rating.game == "pong")
        )
        assert rating.games_played == 2
        assert rating.wins == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RatingEvent)
                .where(RatingEvent.match_id.in_([ids[3], ids[4]]))
            )
            == 2
        )


async def test_concurrent_join_has_one_winner_and_one_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await init_db()

    async def no_publish(*_args: object) -> None:
        return None

    monkeypatch.setattr(mm, "publish", no_publish)
    mgr = MatchManager()
    async with get_sessionmaker()() as session:
        agents = [
            Agent(display_name=f"join-{uuid.uuid4()}", api_key_hash=str(uuid.uuid4()), stats={})
            for _ in range(3)
        ]
        session.add_all(agents)
        await session.commit()
        lobby = await mgr.create(agents[0], "chess", {}, session)
        lobby_id = lobby.id
        agent_ids = [agent.id for agent in agents]

    async def join(agent_id: uuid.UUID) -> object:
        async with get_sessionmaker()() as session:
            agent = await session.get(Agent, agent_id)
            match = await session.get(Match, lobby_id)
            try:
                return await mgr.join(match, agent, session)
            except HTTPException as exc:
                return exc

    results = await asyncio.gather(join(agent_ids[1]), join(agent_ids[2]))
    assert sum(isinstance(result, Match) for result in results) == 1
    rejection = next(result for result in results if isinstance(result, HTTPException))
    assert rejection.status_code == 409
    async with get_sessionmaker()() as session:
        persisted = await session.get(Match, lobby_id)
        assert persisted.status == "running"
        assert len(persisted.players) == 2
        assert len({player["seat"] for player in persisted.players}) == 2

    task = mgr._tasks.get(lobby_id)
    mgr._finish_cleanup(lobby_id)
    if task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_default_listing_and_replay_have_hard_bounds() -> None:
    await init_db()
    async with get_sessionmaker()() as session:
        a, b = uuid.uuid4(), uuid.uuid4()
        players = _players(a, b)
        config = normalize_game_config("pong", {})
        matches = [
            Match(
                game_type="pong",
                mode="realtime",
                status="lobby",
                config=config,
                seed=index,
                players=players[:1],
            )
            for index in range(3)
        ]
        oversized = Match(
            game_type="pong",
            mode="realtime",
            status="finished",
            config=config,
            seed=99,
            players=players,
            tick_or_move_count=MAX_REPLAY_TICKS + 1,
        )
        session.add_all([*matches, oversized])
        await session.commit()

        page = await list_matches(
            status=None,
            game=None,
            limit=2,
            _rate=None,
            session=session,
        )
        assert len(page["matches"]) == 2
        with pytest.raises(HTTPException) as exc:
            await replay_match(
                oversized.id,
                frame_offset=0,
                frame_limit=500,
                _rate=None,
                session=session,
            )
        assert exc.value.status_code == 413
        assert exc.value.detail == "replay_tick_limit_exceeded"
