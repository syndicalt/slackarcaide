"""Matches API — game catalog + match lifecycle + actions + replay (spec §11-§13).

Action submission is agent-authenticated, validated by the engine host, and
replayed deterministically from the persisted action ledger.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent
from app.db import get_session
from app.engine.base import IllegalMove
from app.engine.match_manager import manager
from app.engine.registry import GAMES_CATALOG, REGISTRY
from app.models import ActionLogEntry, Agent, Match
from app.services.messaging import post_message

router = APIRouter(prefix="", tags=["matches"])


class CreateMatchRequest(BaseModel):
    game_type: str
    mode: str = "realtime"
    config: dict = {}


class SubmitActionRequest(BaseModel):
    action: dict = Field(default_factory=dict)
    intent: str | None = Field(default=None, max_length=512)


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
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.create(agent, body.game_type, body.mode, body.config, session)
    return _detail(match)


@router.post("/matches/{match_id}/join")
async def join_match(
    match_id: uuid.UUID,
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
    session: AsyncSession = Depends(get_session),
) -> dict:
    # default: open + live tables; pass status=finished (optionally +game)
    # to browse past games for study
    if status is None:
        lobby = await manager.list_open(session)
        result = await session.scalars(select(Match).where(Match.status == "running"))
        running = list(result.all())
        for m in [*lobby, *running]:
            manager._register(m)  # ensure engine access for running matches
        return {"matches": [_detail(m) for m in [*lobby, *running]]}
    q = select(Match).where(Match.status == status)
    if game is not None:
        q = q.where(Match.game_type == game)
    q = q.order_by(Match.created_at.desc()).limit(limit)
    matches = list((await session.scalars(q)).all())
    return {"matches": [_detail(m) for m in matches]}


@router.get("/matches/{match_id}/pgn")
async def match_pgn(
    match_id: uuid.UUID, session: AsyncSession = Depends(get_session)
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
    match_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return _detail(match)


@router.get("/matches/{match_id}/state")
async def get_match_state(
    match_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return manager.observation(match)


@router.post("/matches/{match_id}/action")
async def submit_action(
    match_id: uuid.UUID,
    body: SubmitActionRequest,
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
        except Exception:
            pass  # intent is cosmetic; never fail the action because of it
    return observation


@router.get("/matches/{match_id}/replay")
async def replay_match(
    match_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")

    engine_cls = REGISTRY.get(match.game_type)
    if engine_cls is None:
        raise HTTPException(404, "unknown_game")
    engine = engine_cls(match.config, match.seed, list(match.players))

    rows = list(
        (
            await session.scalars(
                select(ActionLogEntry)
                .where(ActionLogEntry.match_id == match.id)
                .order_by(ActionLogEntry.tick_or_move, ActionLogEntry.id)
            )
        ).all()
    )

    seat_of = {p["agent_id"]: p["seat"] for p in match.players}
    frames: list[dict] = []

    if match.mode == "realtime":
        total = match.tick_or_move_count or 0
        by_tick: dict[int, dict] = {}
        for r in rows:
            if isinstance(r.action_json, dict) and "moves" in r.action_json:
                by_tick[r.tick_or_move] = r.action_json["moves"]
        for t in range(1, total + 1):
            moves = by_tick.get(t) or {}
            engine.step({int(k): v for k, v in moves.items()})
            if t in by_tick or t == total:
                frames.append(
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
            except IllegalMove:
                continue
            frames.append(
                {
                    "tick": r.tick_or_move,
                    "seat": seat_of.get(str(r.agent_id)),
                    "agent": str(r.agent_id),
                    "intent": r.intent,
                    "render": engine.get_render_data(),
                    "summary": engine.summary(),
                }
            )

    return {
        "match_id": str(match.id),
        "game": match.game_type,
        "mode": match.mode,
        "seed": match.seed,
        "players": match.players,
        "result": match.result,
        "tick_or_move_count": match.tick_or_move_count,
        "frames": frames,
    }
