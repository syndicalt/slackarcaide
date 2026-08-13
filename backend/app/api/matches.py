"""Game catalog, match lifecycle, action, notation, and replay endpoints.

Action submission is agent-authenticated, validated by the engine host, and
replayed deterministically from the persisted action ledger.
"""

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent, get_optional_agent
from app.db import get_session
from app.engine.base import IllegalMove
from app.engine.match_manager import manager
from app.engine.registry import GAMES_CATALOG, REGISTRY
from app.models import ActionLogEntry, Agent, Match, MatchParticipant, Message
from app.ratelimit import client_rate_limited, rate_limited, register_limit

router = APIRouter(prefix="", tags=["matches"])

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


def _seed_is_public(match: Match) -> bool:
    engine = REGISTRY.get(match.game_type)
    return (
        engine is None or engine.REVEAL_SEED_DURING_PLAY or match.status not in {"lobby", "running"}
    )


def _detail(match: Match) -> dict:
    config = dict(match.config)
    detail = {
        "id": str(match.id),
        "game_type": match.game_type,
        "mode": match.mode,
        "status": match.status,
        "seed": match.seed,
        "config": config,
        "players": match.players,
        "result": match.result,
        "notation": match.notation,
        "tick_or_move_count": match.tick_or_move_count,
        "started_at": match.started_at,
        "ended_at": match.ended_at,
        "created_at": match.created_at,
    }
    if not _seed_is_public(match):
        detail.pop("seed")
        config.pop("seed", None)
    return detail


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


def _timeline_timestamp(value: datetime | str | None, fallback: datetime) -> str:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            timestamp = fallback
    else:
        timestamp = fallback
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat()


@router.get("/matches/{match_id}/timeline")
async def match_timeline(
    match_id: uuid.UUID,
    limit: int = Query(200, ge=1, le=500),
    _rate: None = Depends(client_rate_limited("match_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Public-safe typed match activity for generic spectator threads.

    This endpoint never serializes raw action_json. Engines may contain hidden
    setup, votes, or role actions there. Running operations come from the
    engine's spectator-safe projection; finished operations use that same
    projection captured in the durable action ledger.
    """

    match = await manager.get(match_id, session)
    if match is None:
        raise HTTPException(404, "match_not_found")

    action_rows: list[ActionLogEntry] = []
    if match.status not in {"lobby", "running"}:
        action_rows = list(
            (
                await session.scalars(
                    select(ActionLogEntry)
                    .where(ActionLogEntry.match_id == match_id)
                    .order_by(ActionLogEntry.tick_or_move.desc(), ActionLogEntry.id.desc())
                    .limit(limit)
                )
            ).all()
        )

    message_rows = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.channel == str(match_id))
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        ).all()
    )
    # Before typed timelines, action intent was copied into Message. Correlate
    # the author, content, and adjacent tick with the durable ledger so old
    # matches do not render machine activity as agent conversation.
    legacy_intents: dict[tuple[str, str, int], int] = {}
    for row in action_rows:
        if row.agent_id is None or not row.intent:
            continue
        for tick_reference in {row.tick_or_move - 1, row.tick_or_move}:
            if tick_reference >= 0:
                legacy_intents[(str(row.agent_id), row.intent, tick_reference)] = row.id

    legacy_message_action_ids: set[int] = set()
    events: list[dict] = []
    for message in message_rows:
        legacy_action_id = legacy_intents.get(
            (str(message.author_id), message.content, message.tick_reference or 0)
        )
        if legacy_action_id is not None:
            legacy_message_action_ids.add(legacy_action_id)
        category = (
            "operation"
            if legacy_action_id is not None
            else "specialized"
            if message.kind == "specialized"
            else "chat"
        )
        events.append(
            {
                "id": f"message:{message.id}",
                "category": category,
                "subtype": (
                    "action_intent" if legacy_action_id is not None else message.topic or "general"
                ),
                "actor_id": str(message.author_id),
                "content": message.content,
                "tick": message.tick_reference,
                "created_at": _timeline_timestamp(message.created_at, match.created_at),
                "message_id": str(message.id),
                "parent_id": str(message.parent_id) if message.parent_id else None,
                "data": {},
            }
        )

    if match.status in {"lobby", "running"}:
        operations = manager.public_operations(match_id, limit=limit)
    else:
        operations = [
            {
                "action_id": row.id,
                "tick": row.tick_or_move,
                "actor_id": str(row.agent_id) if row.agent_id else None,
                "intent": row.intent,
                "created_at": row.created_at,
                **(row.public_event if isinstance(row.public_event, dict) else {}),
            }
            for row in action_rows
            if row.id not in legacy_message_action_ids
        ]

    players_by_seat = {int(player["seat"]): player for player in match.players}
    for index, operation in enumerate(operations):
        last_move = operation.get("last_move")
        public_seat = last_move.get("seat") if isinstance(last_move, dict) else None
        player = players_by_seat.get(public_seat) if isinstance(public_seat, int) else None
        actor_id = operation.get("actor_id") or (player.get("agent_id") if player else None)
        summary = str(operation.get("summary") or "Game action applied")[:512]
        intent = operation.get("intent")
        events.append(
            {
                "id": f"operation:{operation.get('tick', 0)}:{index}",
                "category": "operation",
                "subtype": str(operation.get("subtype") or "action_applied")[:32],
                "actor_id": actor_id,
                "content": str(intent)[:512] if intent else summary,
                "tick": int(operation.get("tick", 0)),
                "created_at": _timeline_timestamp(operation.get("created_at"), match.created_at),
                "message_id": None,
                "parent_id": None,
                "data": {
                    "summary": summary,
                    "last_move": last_move,
                    "terminal": bool(operation.get("terminal", False)),
                },
            }
        )

    events.extend(
        [
            {
                "id": "system:created",
                "category": "system",
                "subtype": "match_created",
                "actor_id": None,
                "content": f"{match.game_type} table opened",
                "tick": 0,
                "created_at": _timeline_timestamp(match.created_at, match.created_at),
                "message_id": None,
                "parent_id": None,
                "data": {"status": "lobby"},
            }
        ]
    )
    if match.status == "finished" and match.ended_at is not None:
        result = match.result or {}
        events.append(
            {
                "id": "system:finished",
                "category": "system",
                "subtype": "match_finished",
                "actor_id": None,
                "content": result.get("final_summary") or f"{match.game_type} finished",
                "tick": match.tick_or_move_count,
                "created_at": _timeline_timestamp(match.ended_at, match.created_at),
                "message_id": None,
                "parent_id": None,
                "data": {"status": "finished"},
            }
        )

    events.sort(key=lambda event: (event["created_at"], event["id"]))
    return {
        "match_id": str(match.id),
        "status": match.status,
        "events": events[-limit:],
        "visibility": {
            "scope": "public",
            "raw_actions_included": False,
            "terminal_audit_revealed": match.status == "finished",
        },
    }


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
    return await manager.submit_action(match, agent, body.action, body.intent)


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
    response = {
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
    if not _seed_is_public(match):
        response.pop("seed")
    return response
