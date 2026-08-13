"""Six-seat lifecycle, privacy, persistence, and replay for Last Server."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.matches import _detail, replay_match
from app.db import get_sessionmaker, init_db
from app.engine.match_manager import MatchManager, _seats_left
from app.models import ActionLogEntry, Agent, Match, MatchParticipant, Rating, RatingEvent


async def test_last_server_six_seat_lifecycle_is_private_durable_and_unranked() -> None:
    await init_db()
    host = MatchManager()
    nonce = uuid.uuid4().hex
    async with get_sessionmaker()() as session:
        agents = [
            Agent(
                display_name=f"last-server-{seat}-{nonce}",
                api_key_hash=f"last-server-key-{seat}-{nonce}",
                stats={},
            )
            for seat in range(6)
        ]
        session.add_all(agents)
        await session.commit()

        match = await host.create(
            agents[0],
            "last_server",
            {"time_control": {"enabled": False}},
            session,
        )
        assert match.status == "lobby"
        assert _seats_left(match) == 5
        for index, agent in enumerate(agents[1:], start=1):
            match = await host.join(match, agent, session)
            assert _seats_left(match) == max(0, 5 - index)
            if index < 5:
                assert match.status == "lobby"
        assert match.status == "running"
        match_id = match.id

        task = host._tasks.pop(match_id)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        engine = host._engines[match_id]

        public = host.observation(match)
        private = host.observation(match, viewer_agent_id=str(agents[0].id))
        live_detail = _detail(match)
        assert "roles" not in public["render"]
        assert "your_role" not in public["state"]
        assert public["legal_actions"] == []
        assert private["state"]["your_role"] in {"maintainer", "corrupted"}
        assert private["legal_actions"]
        assert "seed" not in live_detail
        assert "seed" not in live_detail["config"]

        live_replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert "seed" not in live_replay
        assert "roles" not in live_replay["frames"][0]["render"]

        # Python considers False equal to 0. The HTTP-side exact-action guard
        # must still reject that type-smuggled seat before it reaches the buffer.
        with pytest.raises(HTTPException) as invalid:
            await host.submit_action(match, agents[0], {"team": [False, 1]})
        assert invalid.value.status_code == 400
        assert host._buffers[match_id] == {}

        await host.submit_action(match, agents[0], {"resign": True})
        host._apply_turnbased(match, engine)
        expected_render = engine.get_render_data()
        expected_winners = engine.get_winner()
        assert expected_render["roles"]
        await host._finish(match, engine)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        assert finished is not None and finished.status == "finished"
        assert _detail(finished)["seed"] == finished.seed
        assert finished.result is not None
        assert finished.result["winner_seats"] == expected_winners
        assert finished.result["final_render"] == expected_render
        assert finished.tick_or_move_count == 1
        assert await session.get(RatingEvent, match_id) is None
        assert (
            await session.scalar(
                select(func.count()).select_from(Rating).where(Rating.game == "last_server")
            )
            == 0
        )
        participants = list(
            (
                await session.scalars(
                    select(MatchParticipant)
                    .where(MatchParticipant.match_id == match_id)
                    .order_by(MatchParticipant.seat)
                )
            ).all()
        )
        assert [participant.seat for participant in participants] == list(range(6))
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ActionLogEntry)
                .where(ActionLogEntry.match_id == match_id)
            )
            == 1
        )

        replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert replay["frame_count"] == 2
        assert replay["seed"] == finished.seed
        assert "roles" not in replay["frames"][0]["render"]
        assert replay["frames"][-1]["render"] == expected_render
        assert replay["frames"][-1]["render"]["roles"]
