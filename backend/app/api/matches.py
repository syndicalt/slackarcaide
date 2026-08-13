"""Game catalog, match lifecycle, action, notation, and replay endpoints.

Action submission is agent-authenticated, validated by the engine host, and
replayed deterministically from the persisted action ledger.
"""

import base64
import binascii
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent, get_optional_agent
from app.db import get_session
from app.engine.base import IllegalMove
from app.engine.match_manager import manager
from app.engine.registry import GAMES_CATALOG, REGISTRY
from app.models import ActionLogEntry, Agent, Match, MatchParticipant
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


def _history_cursor(match: Match) -> str:
    ended_at = match.ended_at or match.created_at
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=UTC)
    payload = json.dumps(
        {"ended_at": ended_at.astimezone(UTC).isoformat(), "id": str(match.id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_history_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
        ended_at = datetime.fromisoformat(payload["ended_at"])
        match_id = uuid.UUID(payload["id"])
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=UTC)
        return ended_at, match_id
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(422, "invalid_history_cursor") from exc


def _history_detail(match: Match, agent_id: uuid.UUID | None) -> dict:
    result = match.result or {}
    winner_agents = {str(value) for value in result.get("winner_agents", [])}
    outcome = None
    if agent_id is not None:
        if str(agent_id) in winner_agents:
            outcome = "win"
        elif winner_agents:
            outcome = "loss"
        else:
            outcome = "draw"
    return {
        "id": str(match.id),
        "game_type": match.game_type,
        "mode": match.mode,
        "status": match.status,
        "players": match.players,
        "tick_or_move_count": match.tick_or_move_count,
        "started_at": match.started_at,
        "ended_at": match.ended_at,
        "created_at": match.created_at,
        "outcome": outcome,
        "final_summary": result.get("final_summary"),
        "winner_seats": result.get("winner_seats", []),
        "replay_url": f"/matches/{match.id}/replay",
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


@router.get("/matches/history")
async def match_history(
    game: str | None = Query(None, max_length=32),
    agent_id: uuid.UUID | None = Query(None),
    before: str | None = Query(None, max_length=256),
    limit: int = Query(24, ge=1, le=100),
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cursor-paginated completed games, globally or for one agent."""

    if game is not None and game not in REGISTRY:
        raise HTTPException(404, "unknown_game")
    query = select(Match).where(Match.status == "finished", Match.ended_at.is_not(None))
    if agent_id is not None:
        query = query.join(MatchParticipant).where(MatchParticipant.agent_id == agent_id)
    if game is not None:
        query = query.where(Match.game_type == game)
    if before is not None:
        ended_at, match_id = _decode_history_cursor(before)
        query = query.where(
            or_(
                Match.ended_at < ended_at,
                and_(Match.ended_at == ended_at, Match.id < match_id),
            )
        )
    rows = list(
        (
            await session.scalars(
                query.order_by(Match.ended_at.desc(), Match.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    page = rows[:limit]
    return {
        "matches": [_history_detail(match, agent_id) for match in page],
        "next_cursor": _history_cursor(page[-1]) if len(rows) > limit else None,
    }


@router.get("/matches/{match_id}/pgn")
async def match_pgn(
    match_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """PGN export of a finished chess-variant match."""
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
    viewer: Agent | None = Depends(get_optional_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")
    return manager.observation(
        match,
        viewer_agent_id=str(viewer.id) if viewer is not None else None,
    )


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

    collect(
        {
            "tick": 0,
            "render": engine.get_render_data(),
            "summary": engine.summary(),
            "terminal": False,
            "kind": "initial",
        }
    )

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
                        "terminal": engine.is_terminal(),
                        "kind": "terminal" if engine.is_terminal() else "action",
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
                    "terminal": engine.is_terminal(),
                    "kind": "terminal" if engine.is_terminal() else "action",
                }
            )

    result = match.result or {}
    terminal_render = result.get("final_render")
    replay_render = engine.get_render_data()
    if terminal_render is not None and replay_render != terminal_render:
        collect(
            {
                "tick": total,
                "render": terminal_render,
                "summary": result.get("final_summary") or engine.summary(),
                "terminal": True,
                "terminal_reason": "external_adjudication",
                "kind": "terminal",
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
