"""Full lifecycle, persistence, rating, privacy, and replay for new arcade games."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

import pytest
from sqlalchemy import func, select

from app.api.matches import replay_match
from app.db import get_sessionmaker, init_db
from app.engine.games.battleship import FLEET
from app.engine.match_manager import MatchManager
from app.models import ActionLogEntry, Agent, Match, RatingEvent


async def _stop_background_loop(host: MatchManager, match_id: uuid.UUID) -> None:
    task = host._tasks.pop(match_id)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _agents(session, game: str) -> tuple[Agent, Agent]:
    nonce = uuid.uuid4().hex
    players = (
        Agent(display_name=f"{game}-integration-a-{nonce}", api_key_hash=f"a-{nonce}", stats={}),
        Agent(display_name=f"{game}-integration-b-{nonce}", api_key_hash=f"b-{nonce}", stats={}),
    )
    session.add_all(players)
    await session.commit()
    return players


def _fleet(vertical: bool) -> dict:
    return {
        "ships": [
            {
                "id": ship_id,
                "start": {
                    "row": 0 if vertical else index,
                    "column": 9 - index if vertical else 0,
                },
                "orientation": "vertical" if vertical else "horizontal",
            }
            for index, (ship_id, _length) in enumerate(FLEET)
        ]
    }


@pytest.mark.parametrize("game", ["ultimate_ttt", "battleship"])
async def test_new_turnbased_game_persists_rates_and_replays(game: str) -> None:
    await init_db()
    host = MatchManager()
    async with get_sessionmaker()() as session:
        first, second = await _agents(session, game)
        match = await host.create(
            first,
            game,
            {"time_control": {"enabled": False}},
            session,
        )
        match = await host.join(match, second, session)
        match_id = match.id
        await _stop_background_loop(host, match_id)
        engine = host._engines[match_id]

        if game == "battleship":
            for agent, action in ((first, _fleet(False)), (second, _fleet(True))):
                await host.submit_action(match, agent, action)
                host._apply_turnbased(match, engine)
            public = host.observation(match)
            assert all("ships" not in board for board in public["state"]["boards"])
            private = host.observation(match, viewer_agent_id=str(first.id))
            own_board = next(board for board in private["state"]["boards"] if board["seat"] == 0)
            enemy_board = next(
                board for board in private["state"]["boards"] if board["seat"] == 1
            )
            assert "ships" in own_board and "ships" not in enemy_board

        await host.submit_action(match, first, {"resign": True})
        host._apply_turnbased(match, engine)
        expected_render = engine.get_render_data()
        expected_moves = engine.move_count
        await host._finish(match, engine)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        assert finished is not None and finished.status == "finished"
        assert finished.result is not None
        assert finished.result["winner_seats"] == [1]
        assert finished.result["final_render"] == expected_render
        assert finished.tick_or_move_count == expected_moves
        assert await session.get(RatingEvent, match_id) is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ActionLogEntry)
                .where(ActionLogEntry.match_id == match_id)
            )
            == expected_moves
        )

        replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert replay["frame_count"] == expected_moves + 1
        assert replay["frames"][0]["kind"] == "initial"
        assert replay["frames"][-1]["render"] == expected_render
        if game == "battleship":
            for frame in replay["frames"][:-1]:
                assert all("ships" not in board for board in frame["render"]["boards"])
            assert all("ships" in board for board in replay["frames"][-1]["render"]["boards"])


@pytest.mark.parametrize(
    ("game", "config", "actions"),
    [
        (
            "tron",
            {"max_ticks": 1, "tick_rate": 60},
            ({"turn": "left"}, {"turn": "right"}),
        ),
        (
            "bomberman",
            {"max_ticks": 1, "tick_rate": 30, "crate_density": 0.0},
            (
                {"move": "noop", "bomb": False},
                {"move": "noop", "bomb": False},
            ),
        ),
        (
            "tetris",
            {
                "tick_rate": 1,
                "max_duration_seconds": 30,
                "max_pieces_per_player": 1,
            },
            (
                {"rotation": 0, "column": 3, "drop": True},
                {"rotation": 0, "column": 3, "drop": True},
            ),
        ),
    ],
)
async def test_new_realtime_lifecycle_persists_batches_and_replays(
    game: str,
    config: dict,
    actions: tuple[dict, dict],
) -> None:
    await init_db()
    host = MatchManager()
    async with get_sessionmaker()() as session:
        first, second = await _agents(session, game)
        match = await host.create(first, game, config, session)
        match = await host.join(match, second, session)
        match_id = match.id
        await _stop_background_loop(host, match_id)
        engine = host._engines[match_id]

        await host.submit_action(match, first, actions[0])
        await host.submit_action(match, second, actions[1])
        host._tick_realtime(match_id, engine)
        assert engine.is_terminal() and engine.get_winner() is None
        expected_render = engine.get_render_data()
        await host._finish(match, engine)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        assert finished is not None and finished.status == "finished"
        assert finished.tick_or_move_count == 1
        assert finished.result is not None
        assert finished.result["reason"] == "draw"
        assert await session.get(RatingEvent, match_id) is not None

        ledger = list(
            (
                await session.scalars(
                    select(ActionLogEntry).where(ActionLogEntry.match_id == match_id)
                )
            ).all()
        )
        assert len(ledger) == 1
        assert ledger[0].agent_id is None
        assert ledger[0].action_json == {"moves": {"0": actions[0], "1": actions[1]}}

        replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert replay["frame_count"] == 2
        assert replay["frames"][0]["kind"] == "initial"
        assert replay["frames"][-1]["render"] == expected_render
