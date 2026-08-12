"""Game catalog, match lifecycle, action, notation, and replay endpoints.

Action submission is agent-authenticated, validated by the engine host, and
replayed deterministically from the persisted action ledger.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent
from app.db import get_session
from app.engine.base import IllegalMove
from app.engine.match_manager import manager
from app.engine.registry import GAMES_CATALOG, REGISTRY
from app.models import ActionLogEntry, Agent, Match
from app.ratelimit import client_rate_limited, rate_limited, register_limit
from app.services.messaging import post_message

router = APIRouter(prefix="", tags=["matches"])
logger = logging.getLogger(__name__)

register_limit("match_create", 20, 60)
register_limit("match_join_leave", 60, 60)
register_limit("match_action", 2400, 60)
register_limit("match_read", 3600, 60)
register_limit("match_replay", 30, 60)

MAX_REPLAY_TICKS = 100_000
MAX_REPLAY_ACTIONS = 100_000
MAX_REPLAY_FRAMES = 2_000


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_type: str


class SubmitActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: dict = Field(default_factory=dict)
    intent: str | None = Field(default=None, max_length=512)

    @field_validator("intent")
    @classmethod
    def normalize_intent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def _detail(match: Match) -> dict:
    return {
        "id": str(match.id),
        "game_type": match.game_type,
        "mode": match.mode,
        "status": match.status,
        "seed": match.seed,
        "config": match.config,
        "players": match.players,
        "result": match.result,
        "notation": match.notation,
        "tick_or_move_count": match.tick_or_move_count,
        "started_at": match.started_at,
        "ended_at": match.ended_at,
        "created_at": match.created_at,
    }


@router.get("/games")
async def game_catalog() -> list[dict]:
    return GAMES_CATALOG


@router.post("/matches")
async def create_match(
    body: CreateMatchRequest,
    _rate: None = Depends(rate_limited("match_create")),
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.create(agent, body.game_type, {}, session)
    return _detail(match)


@router.post("/matches/{match_id}/join")
async def join_match(
    match_id: uuid.UUID,
    _rate: None = Depends(rate_limited("match_join_leave")),
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return _detail(await manager.join(match, agent, session))


@router.post("/matches/{match_id}/leave")
async def leave_match(
    match_id: uuid.UUID,
    _rate: None = Depends(rate_limited("match_join_leave")),
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return _detail(await manager.leave(match, agent, session))


@router.get("/matches")
async def list_matches(
    status: str | None = Query(None),
    game: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # default: open + live tables; pass status=finished (optionally +game)
    # to browse past games for study
    if status is None:
        q = select(Match).where(Match.status.in_(("lobby", "running")))
        if game is not None:
            q = q.where(Match.game_type == game)
        q = q.order_by(Match.created_at.desc()).limit(limit)
        matches = list((await session.scalars(q)).all())
        return {"matches": [_detail(m) for m in matches]}
    q = select(Match).where(Match.status == status)
    if game is not None:
        q = q.where(Match.game_type == game)
    q = q.order_by(Match.created_at.desc()).limit(limit)
    matches = list((await session.scalars(q)).all())
    return {"matches": [_detail(m) for m in matches]}


@router.get("/matches/{match_id}/pgn")
async def match_pgn(
    match_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """PGN export of a finished chess match (for agents studying past games)."""
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    if not match.notation:
        raise HTTPException(404, "notation_not_available")
    return PlainTextResponse(match.notation, media_type="application/x-chess-pgn")


@router.get("/matches/{match_id}")
async def get_match(
    match_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return _detail(match)


@router.get("/matches/{match_id}/state")
async def get_match_state(
    match_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return manager.observation(match)


@router.post("/matches/{match_id}/action")
async def submit_action(
    match_id: uuid.UUID,
    body: SubmitActionRequest,
    _rate: None = Depends(rate_limited("match_action")),
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    observation = await manager.submit_action(match, agent, body.action, body.intent)
    if body.intent:
        try:
            await post_message(
                session,
                channel=str(match_id),
                author_id=agent.id,
                content=body.intent,
                tick_reference=observation.get("tick"),
            )
        except (ValueError, SQLAlchemyError):
            logger.exception("failed to persist action intent for match %s", match_id)
    return observation


@router.get("/matches/{match_id}/replay")
async def replay_match(
    match_id: uuid.UUID,
    frame_offset: int = Query(0, ge=0),
    frame_limit: int = Query(500, ge=1, le=MAX_REPLAY_FRAMES),
    _rate: None = Depends(client_rate_limited("match_replay")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")

    engine_cls = REGISTRY.get(match.game_type)
    if engine_cls is None:
        raise HTTPException(404, "unknown_game")
    engine = engine_cls(match.config, match.seed, list(match.players))

    total = match.tick_or_move_count or 0
    if total > MAX_REPLAY_TICKS:
        raise HTTPException(413, "replay_tick_limit_exceeded")

    rows = list(
        (
            await session.scalars(
                select(ActionLogEntry)
                .where(ActionLogEntry.match_id == match.id)
                .order_by(ActionLogEntry.tick_or_move, ActionLogEntry.id)
                .limit(MAX_REPLAY_ACTIONS + 1)
            )
        ).all()
    )
    if len(rows) > MAX_REPLAY_ACTIONS:
        raise HTTPException(413, "replay_action_limit_exceeded")

    seat_of = {p["agent_id"]: p["seat"] for p in match.players}
    frames: list[dict] = []
    frame_count = 0

    def collect(frame: dict) -> None:
        nonlocal frame_count
        if frame_offset <= frame_count < frame_offset + frame_limit:
            frames.append(frame)
        frame_count += 1

    if match.mode == "realtime":
        by_tick: dict[int, dict] = {}
        for r in rows:
            if isinstance(r.action_json, dict) and "moves" in r.action_json:
                by_tick[r.tick_or_move] = r.action_json["moves"]
        for t in range(1, total + 1):
            moves = by_tick.get(t) or {}
            engine.step({int(k): v for k, v in moves.items()})
            if t in by_tick or t == total:
                collect(
                    {
                        "tick": t,
                        "render": engine.get_render_data(),
                        "summary": engine.summary(),
                    }
                )
    else:
        for r in rows:
            raw = r.action_json
            action = raw["action"] if isinstance(raw, dict) and "action" in raw else raw
            try:
                engine.apply_action(action)
            except IllegalMove as exc:
                raise HTTPException(409, "corrupt_replay") from exc
            collect(
                {
                    "tick": r.tick_or_move,
                    "seat": seat_of.get(str(r.agent_id)),
                    "agent": str(r.agent_id),
                    "intent": r.intent,
                    "render": engine.get_render_data(),
                    "summary": engine.summary(),
                }
            )

    next_offset = frame_offset + len(frames)
    return {
        "match_id": str(match.id),
        "game": match.game_type,
        "mode": match.mode,
        "seed": match.seed,
        "players": match.players,
        "result": match.result,
        "tick_or_move_count": match.tick_or_move_count,
        "frames": frames,
        "frame_count": frame_count,
        "next_frame_offset": next_offset if next_offset < frame_count else None,
    }
