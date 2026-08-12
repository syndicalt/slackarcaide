"""Per-game leaderboard and stable rank endpoints.

Lean on `Rating` (the ranking source of truth). A leaderboard rank is the
Elo-sorted position among agents who have played the game, optionally filtered
to non-provisional players so fresh accounts don't saturate the top.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.engine.registry import GAMES_CATALOG
from app.models import Agent, Rating
from app.ratelimit import client_rate_limited, register_limit

router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])
register_limit("leaderboard_read", max_count=3_600, window_s=60)

_GAME_NAMES = {g["game"] for g in GAMES_CATALOG}


def _row(r: Rating, rank: int, display_name: str | None = None) -> dict:
    return {
        "rank": rank,
        "agent_id": str(r.agent_id),
        "display_name": display_name,
        "elo": r.elo,
        "provisional": r.provisional,
        "games_played": r.games_played,
        "wins": r.wins,
        "losses": r.losses,
        "draws": r.draws,
        "last_change": r.last_change,
    }


@router.get("/{game}")
async def leaderboard(
    game: str,
    limit: int = Query(50, ge=1, le=200),
    # default True: anyone who has finished a game appears, ranked by Elo;
    # pass false to hide provisional (<10 games) players from the board
    include_provisional: bool = Query(True),
    _rate: None = Depends(client_rate_limited("leaderboard_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if game not in _GAME_NAMES:
        raise HTTPException(404, "unknown_game")
    q = (
        select(Rating, Agent.display_name)
        .join(Agent, Agent.id == Rating.agent_id)
        .where(Rating.game == game, Rating.games_played > 0)
    )
    if not include_provisional:
        q = q.where(Rating.provisional.is_(False))
    q = q.order_by(Rating.elo.desc(), Rating.updated_at.asc(), Rating.agent_id.asc()).limit(limit)
    rows = list((await session.execute(q)).all())
    return {
        "game": game,
        "count": len(rows),
        "entries": [_row(r, i + 1, name) for i, (r, name) in enumerate(rows)],
    }


@router.get("/{game}/rank/{agent_id}")
async def agent_rank(
    game: str,
    agent_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("leaderboard_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return a single agent's standing in a game (rank among eligible rows)."""
    if game not in _GAME_NAMES:
        raise HTTPException(404, "unknown_game")
    rating = await session.scalar(
        select(Rating).where(
            Rating.game == game,
            Rating.agent_id == agent_id,
            Rating.games_played > 0,
        )
    )
    if rating is None:
        raise HTTPException(404, "no_rating")
    better = await session.scalar(
        select(func.count())
        .select_from(Rating)
        .where(
            Rating.game == game,
            Rating.games_played > 0,
            or_(
                Rating.elo > rating.elo,
                and_(
                    Rating.elo == rating.elo,
                    or_(
                        Rating.updated_at < rating.updated_at,
                        and_(
                            Rating.updated_at == rating.updated_at,
                            Rating.agent_id < rating.agent_id,
                        ),
                    ),
                ),
            ),
        )
    )
    agent = await session.get(Agent, agent_id)
    return {
        "game": game,
        "agent_id": str(agent_id),
        "rank": better + 1,
        **{
            key: value
            for key, value in _row(rating, 0, agent.display_name if agent else None).items()
            if key != "rank"
        },
    }
