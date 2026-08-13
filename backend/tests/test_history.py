"""Durable cross-game history discovery and terminal replay coverage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.matches import match_history, replay_match
from app.db import get_sessionmaker, init_db
from app.engine.games.chess import Chess
from app.engine.registry import normalize_game_config
from app.models import Agent, Match, MatchParticipant


def _players(*agents: Agent) -> list[dict]:
    return [
        {
            "agent_id": str(agent.id),
            "seat": seat,
            "side": None,
            "name": agent.display_name,
        }
        for seat, agent in enumerate(agents)
    ]


async def test_history_is_cursor_paginated_filterable_and_agent_relative() -> None:
    await init_db()
    now = datetime.now(UTC)
    async with get_sessionmaker()() as session:
        first = Agent(
            display_name=f"history-a-{uuid.uuid4()}",
            api_key_hash=str(uuid.uuid4()),
            stats={},
        )
        second = Agent(
            display_name=f"history-b-{uuid.uuid4()}",
            api_key_hash=str(uuid.uuid4()),
            stats={},
        )
        session.add_all([first, second])
        await session.flush()
        players = _players(first, second)
        matches = []
        for index, game in enumerate(("chess", "pong", "chess")):
            winner_seat = index % 2
            match = Match(
                game_type=game,
                mode="turnbased" if game == "chess" else "realtime",
                status="finished",
                config=normalize_game_config(game, {}),
                seed=index,
                players=players,
                result={
                    "winner_seats": [winner_seat],
                    "winner_agents": [players[winner_seat]["agent_id"]],
                    "final_summary": f"finished-{index}",
                    "final_render": {},
                },
                ended_at=now + timedelta(seconds=index),
                tick_or_move_count=index + 1,
            )
            session.add(match)
            await session.flush()
            session.add_all(
                [
                    MatchParticipant(
                        match_id=match.id,
                        agent_id=agent.id,
                        seat=seat,
                        side=None,
                        display_name=agent.display_name,
                    )
                    for seat, agent in enumerate((first, second))
                ]
            )
            matches.append(match)
        await session.commit()

        newest = await match_history(
            game=None,
            agent_id=first.id,
            before=None,
            limit=2,
            _rate=None,
            session=session,
        )
        assert [row["final_summary"] for row in newest["matches"]] == [
            "finished-2",
            "finished-1",
        ]
        assert [row["outcome"] for row in newest["matches"]] == ["win", "loss"]
        assert "result" not in newest["matches"][0]
        assert "config" not in newest["matches"][0]
        assert newest["next_cursor"]

        older = await match_history(
            game=None,
            agent_id=first.id,
            before=newest["next_cursor"],
            limit=2,
            _rate=None,
            session=session,
        )
        assert [row["final_summary"] for row in older["matches"]] == ["finished-0"]
        assert older["next_cursor"] is None

        chess_only = await match_history(
            game="chess",
            agent_id=second.id,
            before=None,
            limit=10,
            _rate=None,
            session=session,
        )
        assert len(chess_only["matches"]) == 2
        assert {row["outcome"] for row in chess_only["matches"]} == {"loss"}


async def test_replay_appends_durable_terminal_snapshot_for_clock_timeout() -> None:
    await init_db()
    async with get_sessionmaker()() as session:
        first = Agent(
            display_name=f"timeout-a-{uuid.uuid4()}",
            api_key_hash=str(uuid.uuid4()),
            stats={},
        )
        second = Agent(
            display_name=f"timeout-b-{uuid.uuid4()}",
            api_key_hash=str(uuid.uuid4()),
            stats={},
        )
        session.add_all([first, second])
        await session.flush()
        players = _players(first, second)
        config = normalize_game_config("chess", {})
        terminal_engine = Chess(config, 17, players)
        terminal_engine._clock_remaining_ms[0] = 0
        terminal_engine.timeout_loss(0)
        match = Match(
            game_type="chess",
            mode="turnbased",
            status="finished",
            config=config,
            seed=17,
            players=players,
            result={
                "winner_seats": [1],
                "winner_agents": [str(second.id)],
                "scores": terminal_engine.get_scores(),
                "final_render": terminal_engine.get_render_data(),
                "final_summary": terminal_engine.summary(),
            },
            ended_at=datetime.now(UTC),
            tick_or_move_count=0,
        )
        session.add(match)
        await session.commit()

        replay = await replay_match(
            match.id,
            frame_offset=0,
            frame_limit=500,
            _rate=None,
            session=session,
        )
        assert replay["frame_count"] == 2
        assert replay["frames"][0]["kind"] == "initial"
        assert replay["frames"][0]["terminal"] is False
        assert replay["frames"][1] == {
            "tick": 0,
            "render": match.result["final_render"],
            "summary": match.result["final_summary"],
            "terminal": True,
            "terminal_reason": "external_adjudication",
            "kind": "terminal",
        }


@pytest.mark.parametrize(
    ("game", "before", "detail"),
    [
        ("not-a-game", None, "unknown_game"),
        (None, "not-a-cursor", "invalid_history_cursor"),
    ],
)
async def test_history_rejects_unknown_games_and_malformed_cursors(
    game: str | None,
    before: str | None,
    detail: str,
) -> None:
    await init_db()
    async with get_sessionmaker()() as session:
        with pytest.raises(HTTPException) as caught:
            await match_history(
                game=game,
                agent_id=None,
                before=before,
                limit=24,
                _rate=None,
                session=session,
            )
        assert caught.value.status_code in {404, 422}
        assert caught.value.detail == detail
