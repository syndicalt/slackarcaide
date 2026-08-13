"""End-to-end persistence and replay coverage for the four board-game engines."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

import pytest

from app.api.matches import replay_match
from app.db import get_sessionmaker, init_db
from app.engine.match_manager import MatchManager
from app.models import Agent, Match


async def _stop_background_loop(manager: MatchManager, match_id) -> None:
    task = manager._tasks.pop(match_id)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _next_action(game: str, engine) -> dict[str, Any]:
    if game == "connect_four":
        winning_line = (0, 1, 0, 1, 0, 1, 0)
        return {"column": winning_line[engine.move_count]}
    if game == "go":
        return {"pass": True}
    return next(
        action
        for action in engine.get_legal_actions(engine.current_seat())
        if "resign" not in action
    )


@pytest.mark.parametrize("game", ["connect_four", "reversi", "checkers", "go"])
async def test_new_game_finishes_persists_rates_and_replays(game: str) -> None:
    await init_db()
    manager = MatchManager()
    async with get_sessionmaker()() as session:
        white = Agent(
            display_name=f"{game}-integration-a", api_key_hash=f"h-{game}-integration-a", stats={}
        )
        black = Agent(
            display_name=f"{game}-integration-b", api_key_hash=f"h-{game}-integration-b", stats={}
        )
        session.add_all([white, black])
        await session.commit()

        match = await manager.create(white, game, {}, session)
        match = await manager.join(match, black, session)
        match_id = match.id
        await _stop_background_loop(manager, match_id)
        engine = manager._engines[match_id]
        agents = {0: white, 1: black}

        while not engine.is_terminal():
            seat = engine.current_seat()
            await manager.submit_action(match, agents[seat], _next_action(game, engine))
            manager._apply_turnbased(match, engine)

        expected_render = engine.get_render_data()
        expected_moves = engine.move_count
        await manager._finish(match, engine)

    async with get_sessionmaker()() as session:
        finished = await session.get(Match, match_id)
        assert finished is not None and finished.status == "finished"
        assert finished.tick_or_move_count == expected_moves
        assert finished.result is not None
        assert finished.result["final_render"] == expected_render

        replay = await replay_match(
            match_id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert replay["game"] == game
        assert replay["frame_count"] == expected_moves + 1
        assert replay["frames"][0]["kind"] == "initial"
        assert replay["frames"][-1]["render"] == expected_render
