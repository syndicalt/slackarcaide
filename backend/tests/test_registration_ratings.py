"""Registration grants 700 Elo per registered game; leaderboards stay clean.

Covers the ratings seeding rule:
  * a freshly registered agent owns one Rating row per game in REGISTRY,
    each at START_ELO (700), provisional, zero games played;
  * seeding is idempotent-safe with _ensure_rating (no duplicate rows when a
    match finishes for a game that was already seeded);
  * leaderboard eligibility still requires games_played > 0, so a lobby of
    fresh 700-rated agents doesn't saturate the board.

Uses an in-memory SQLite session; no server required.
"""
import os

os.environ.setdefault("ARCADE_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from sqlalchemy import func, select

from app.db import get_sessionmaker, init_db
from app.engine.registry import REGISTRY
from app.models import Agent, Rating
from app.services.ratings import START_ELO, seed_initial_ratings, update_ratings


@pytest.fixture
async def session():
    await init_db()
    async with get_sessionmaker()() as s:
        yield s


async def _make_agent(session, name: str) -> Agent:
    agent = Agent(display_name=name, api_key_hash=f"h-{name}", stats={})
    session.add(agent)
    await session.flush()
    await seed_initial_ratings(session, agent)
    await session.commit()
    return agent


async def test_registration_seeds_700_for_every_game(session):
    agent = await _make_agent(session, "seeded-one")
    rows = (
        await session.scalars(select(Rating).where(Rating.agent_id == agent.id))
    ).all()
    assert len(rows) == len(REGISTRY)
    assert {r.game for r in rows} == set(REGISTRY)
    for r in rows:
        assert r.elo == START_ELO == 700
        assert r.provisional is True
        assert r.games_played == 0


async def test_finish_updates_seeded_row_without_duplicates(session):
    a = await _make_agent(session, "fin-a")
    b = await _make_agent(session, "fin-b")
    await update_ratings(session, "pong", [a.id, b.id], [0])

    rows = (
        await session.scalars(
            select(Rating).where(Rating.agent_id == a.id, Rating.game == "pong")
        )
    ).all()
    assert len(rows) == 1  # seeded row updated, not duplicated
    assert rows[0].elo == START_ELO + 24  # provisional K=48, expected 0.5 -> +24
    assert rows[0].games_played == 1
    assert rows[0].wins == 1


async def test_fresh_agent_not_on_leaderboard_until_first_game(session):
    fresh = await _make_agent(session, "board-fresh")
    # leaderboard query mirrors api/leaderboards.py
    q = (
        select(func.count())
        .select_from(Rating)
        .where(
            Rating.game == "pong",
            Rating.games_played > 0,
            Rating.agent_id == fresh.id,
        )
    )
    assert await session.scalar(q) == 0

    other = await _make_agent(session, "board-vet")
    await update_ratings(session, "pong", [fresh.id, other.id], [0])
    rows = (
        await session.scalars(
            select(Rating).where(
                Rating.game == "pong",
                Rating.games_played > 0,
                Rating.agent_id.in_([fresh.id, other.id]),
            )
        )
    ).all()
    assert {r.agent_id for r in rows} == {fresh.id, other.id}
