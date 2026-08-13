"""Transactional, auditable Elo updates for head-to-head ranked matches."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import AsyncExitStack

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Rating, RatingEvent

START_ELO = 700
K = 24
PROVISIONAL_GAMES = 10
_RATING_LOCKS = tuple(asyncio.Lock() for _ in range(256))


async def seed_initial_ratings(session: AsyncSession, agent: Agent) -> None:
    """Grant every new agent a START_ELO rating row for each ranked game.

    Called once at registration. Rows start at games_played=0, so the agent
    appears on leaderboards only after their first finished game; _ensure_rating
    back-fills the same START_ELO if a game is added to the registry later.
    """
    from app.engine.registry import GAMES_CATALOG  # lazy: avoids import cycle

    for game in GAMES_CATALOG:
        if game["elo_ranked"]:
            session.add(Rating(agent_id=agent.id, game=game["game"], elo=START_ELO))
    await session.flush()


async def _ensure_rating(session: AsyncSession, agent: Agent, game: str) -> Rating:
    rating = await session.scalar(
        select(Rating).where(Rating.agent_id == agent.id, Rating.game == game)
    )
    if rating is None:
        rating = Rating(agent_id=agent.id, game=game, elo=START_ELO)
        session.add(rating)
        await session.flush()
    return rating


async def update_ratings(
    session: AsyncSession,
    game: str,
    seat_agent_ids: list[uuid.UUID],
    winner_seats: list[int] | None,
    *,
    match_id: uuid.UUID | None = None,
) -> bool:
    """Serialize locally and lock rows transactionally across processes."""
    if len(seat_agent_ids) != 2:
        return False
    stripes = sorted(
        {_RATING_LOCKS[agent_id.int % len(_RATING_LOCKS)] for agent_id in seat_agent_ids},
        key=id,
    )
    async with AsyncExitStack() as stack:
        for lock in stripes:
            await stack.enter_async_context(lock)
        return await _update_ratings_locked(
            session,
            game,
            seat_agent_ids,
            winner_seats,
            match_id=match_id,
        )


async def _update_ratings_locked(
    session: AsyncSession,
    game: str,
    seat_agent_ids: list[uuid.UUID],
    winner_seats: list[int] | None,
    *,
    match_id: uuid.UUID | None,
) -> bool:
    """Apply an Elo adjustment for a finished head-to-head match.

    `seat_agent_ids` is the agent id at each seat; `winner_seats` is None for a
    draw, else the winning seat indices (single-element for win, both for draw).
    """
    if len(seat_agent_ids) != 2 or seat_agent_ids[0] == seat_agent_ids[1]:
        return False

    # The Match row is locked by MatchManager before this function. This
    # durable marker additionally makes retries and post-commit re-entry a
    # no-op. The primary key enforces the invariant in the database.
    if match_id is not None and await session.get(RatingEvent, match_id) is not None:
        return False

    # _finish normalizes None -> [], so treat "no winner seats" as a draw too;
    # indexing winner_seats[0] below would crash on a draw otherwise
    draw = not winner_seats or len(winner_seats) >= 2

    ordered_ids = sorted(seat_agent_ids, key=str)
    locked_agents = list(
        (
            await session.scalars(
                select(Agent).where(Agent.id.in_(ordered_ids)).order_by(Agent.id).with_for_update()
            )
        ).all()
    )
    agents = {agent.id: agent for agent in locked_agents}
    red = agents.get(seat_agent_ids[0])
    blue = agents.get(seat_agent_ids[1])
    if red is None or blue is None:
        return False

    locked_ratings = list(
        (
            await session.scalars(
                select(Rating)
                .where(Rating.agent_id.in_(ordered_ids), Rating.game == game)
                .order_by(Rating.agent_id)
                .with_for_update()
            )
        ).all()
    )
    by_agent = {rating.agent_id: rating for rating in locked_ratings}
    ra = by_agent.get(red.id) or await _ensure_rating(session, red, game)
    rb = by_agent.get(blue.id) or await _ensure_rating(session, blue, game)

    before = {
        str(red.id): _snapshot(ra),
        str(blue.id): _snapshot(rb),
    }

    pa = 1.0 / (1.0 + 10 ** ((rb.elo - ra.elo) / 400.0))
    pb = 1.0 - pa
    ka = K * (2 if ra.provisional else 1)
    kb = K * (2 if rb.provisional else 1)

    if draw:
        sa = sb = 0.5
    elif winner_seats[0] == 0:
        sa, sb = 1.0, 0.0
    else:
        sa, sb = 0.0, 1.0

    old_ra, old_rb = ra.elo, rb.elo
    ra.elo = max(100, ra.elo + round(ka * (sa - pa)))
    rb.elo = max(100, rb.elo + round(kb * (sb - pb)))
    ra.last_change = ra.elo - old_ra
    rb.last_change = rb.elo - old_rb
    ra.games_played += 1
    rb.games_played += 1
    if draw:
        ra.draws += 1
        rb.draws += 1
    else:
        winner = 0 if winner_seats[0] == 0 else 1
        if winner == 0:
            ra.wins += 1
            rb.losses += 1
        else:
            rb.wins += 1
            ra.losses += 1
    ra.provisional = ra.games_played < PROVISIONAL_GAMES
    rb.provisional = rb.games_played < PROVISIONAL_GAMES

    # mirror into Agent.stats for cheap profile reads (preserve other games)
    red.stats = {**(red.stats or {}), game: _mirror(ra)}
    blue.stats = {**(blue.stats or {}), game: _mirror(rb)}

    if match_id is not None:
        session.add(
            RatingEvent(
                match_id=match_id,
                game=game,
                agent_ids=[str(agent_id) for agent_id in seat_agent_ids],
                winner_seats=list(winner_seats or []),
                before=before,
                after={str(red.id): _snapshot(ra), str(blue.id): _snapshot(rb)},
            )
        )
    await session.flush()
    return True


def _snapshot(rating: Rating) -> dict:
    return {
        "elo": rating.elo,
        "wins": rating.wins,
        "losses": rating.losses,
        "draws": rating.draws,
        "matches": rating.games_played,
        "provisional": rating.provisional,
        "last_change": rating.last_change,
    }


def _mirror(rating: Rating) -> dict:
    snapshot = _snapshot(rating)
    snapshot.pop("last_change")
    return snapshot
