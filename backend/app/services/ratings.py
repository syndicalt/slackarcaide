"""Per-game Elo ratings (spec §7).

Updated when a ranked match finishes. Standard two-player Elo (all ranked games
are head-to-head). `Rating` is the ranking source of truth; each `Agent.stats`
JSON is mirrored here for cheap profile reads.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Rating

START_ELO = 700
K = 24
PROVISIONAL_GAMES = 10


async def seed_initial_ratings(session: AsyncSession, agent: Agent) -> None:
    """Grant every new agent a START_ELO rating row for each registered game.

    Called once at registration. Rows start at games_played=0, so the agent
    appears on leaderboards only after their first finished game; _ensure_rating
    back-fills the same START_ELO if a game is added to the registry later.
    """
    from app.engine.registry import REGISTRY  # lazy: avoids import cycle

    for game in REGISTRY:
        session.add(Rating(agent_id=agent.id, game=game, elo=START_ELO))
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
    seat_agent_ids: list[str],
    winner_seats: list[int] | None,
) -> None:
    """Apply an Elo adjustment for a finished head-to-head match.

    `seat_agent_ids` is the agent id at each seat; `winner_seats` is None for a
    draw, else the winning seat indices (single-element for win, both for draw).
    """
    if len(seat_agent_ids) != 2:
        return  # only 2-player Elo supported (v1)

    # _finish normalizes None -> [], so treat "no winner seats" as a draw too;
    # indexing winner_seats[0] below would crash on a draw otherwise
    draw = not winner_seats or len(winner_seats) >= 2

    red = await session.get(Agent, seat_agent_ids[0])
    blue = await session.get(Agent, seat_agent_ids[1])
    if red is None or blue is None:
        return

    ra = await _ensure_rating(session, red, game)
    rb = await _ensure_rating(session, blue, game)

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
    red.stats = {**red.stats, game: _mirror(ra, red.stats.get(game, {}))}
    blue.stats = {**blue.stats, game: _mirror(rb, blue.stats.get(game, {}))}

    await session.commit()


def _mirror(r: Rating, old: dict) -> dict:
    old.update(
        {
            "elo": r.elo,
            "wins": r.wins,
            "losses": r.losses,
            "draws": r.draws,
            "matches": r.games_played,
            "provisional": r.provisional,
        }
    )
    return old
