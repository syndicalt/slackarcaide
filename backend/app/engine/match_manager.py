"""Authoritative in-process match runtime and durable finish pipeline.

Each running match owns one engine instance. A per-match asyncio loop task
drives it: realtime games advance on a fixed tick; turn-based games advance on
buffered legal moves (or clock timeout). All game-state mutation happens inside
the owning loop task — API requests only enqueue actions and read observations,
so there is no cross-thread write race on engine state.

Redis pub/sub (`match:{id}`) is transport only; the engine is authoritative.
ORM persistence (action ledger at finish, match result, ratings) uses a fresh
session so background loop work never shares request sessions.
"""

import asyncio
import logging
import random
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.engine.base import BaseGame, IllegalMove
from app.engine.registry import GAMES_CATALOG, REGISTRY, normalize_game_config
from app.models import ActionLogEntry, Agent, Match
from app.realtime.publisher import publish
from app.services.notation import build_pgn
from app.services.ratings import update_ratings

logger = logging.getLogger(__name__)

DEFAULT_MAX_PLAYERS = 2
CLOCK_RESOLUTION_S = 0.1  # turn-based clock granularity
MAX_SPECTATOR_FPS = 30


def _now() -> datetime:
    return datetime.now(UTC)


def _catalog(game_type: str) -> dict | None:
    return next((g for g in GAMES_CATALOG if g["game"] == game_type), None)


def _players_required(config: dict) -> int:
    req = config.get("players_required")
    return int(req) if req else int(config.get("max_players", DEFAULT_MAX_PLAYERS))


def _seats_left(match: Match) -> int:
    return max(0, _players_required(match.config) - len(match.players))


def _lobby_payload(match: Match, action: str) -> dict:
    return {
        "type": "table",
        "action": action,
        "match": {
            "id": str(match.id),
            "game_type": match.game_type,
            "mode": match.mode,
            "status": match.status,
            "players": match.players,
            "players_required": _players_required(match.config),
            "seats_left": _seats_left(match),
        },
    }


async def _publish_lobby(match: Match, action: str) -> None:
    """Notify lobby subscribers when a table changes or leaves the open set."""
    terminal_actions = {"closed", "started"}
    if match.status != "lobby" and action not in terminal_actions:
        return
    if action not in terminal_actions and _seats_left(match) <= 0:
        return
    await publish("lobby", _lobby_payload(match, action))


class MatchManager:
    """Authoritative registry + engine host. Module-level `manager` singleton."""

    def __init__(self) -> None:
        self._registry: dict[uuid.UUID, Match] = {}
        self._engines: dict[uuid.UUID, BaseGame] = {}
        # One pending turn action or the latest realtime input per seat.
        self._buffers: dict[uuid.UUID, dict[int, dict]] = {}
        self._ledgers: dict[uuid.UUID, list[dict]] = {}  # action log collected at run
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._lifecycle_locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._last_publish_at: dict[uuid.UUID, float] = {}

    # ---- registration helpers -------------------------------------------------

    def _register(self, match: Match) -> None:
        self._registry[match.id] = match

    async def _managed(self, match: Match, session: AsyncSession) -> Match:
        merged = await session.merge(match)
        self._registry[merged.id] = merged
        return merged

    # ---- lifecycle ------------------------------------------------------------

    async def create(
        self,
        agent: Agent,
        game_type: str,
        config: dict,
        session: AsyncSession,
    ) -> Match:
        cat = _catalog(game_type)
        if cat is None or game_type not in REGISTRY:
            raise HTTPException(404, "unknown_game")
        raw_config = dict(config or {})
        if cat["elo_ranked"] and raw_config.get("ranked", True):
            # custom start positions would allow trivial Elo farming (e.g.
            # starting one move from mate); ranked games always start standard
            raw_config.pop("start_fen", None)
        try:
            config = normalize_game_config(game_type, raw_config)
        except ValidationError as exc:
            raise HTTPException(422, "invalid_game_config") from exc
        if cat["elo_ranked"] and config.get("ranked", True):
            config.pop("start_fen", None)
        seed = config.get("seed")
        match = Match(
            game_type=game_type,
            mode=cat["mode"],
            status="lobby",
            config=config,
            seed=int(seed) if seed is not None else random.getrandbits(31),
            players=[
                {"agent_id": str(agent.id), "seat": 0, "side": None, "name": agent.display_name}
            ],
        )
        session.add(match)
        await session.commit()
        self._register(match)
        self._lifecycle_locks.setdefault(match.id, asyncio.Lock())
        # Start immediately only when the catalog's required seat count is met.
        if len(match.players) >= _players_required(match.config):
            await self.start(match, session)
        await _publish_lobby(match, "open")
        return match

    async def join(self, match: Match, agent: Agent, session: AsyncSession) -> Match:
        lock = self._lifecycle_locks.setdefault(match.id, asyncio.Lock())
        async with lock:
            m = await session.scalar(select(Match).where(Match.id == match.id).with_for_update())
            if m is None:
                raise HTTPException(404, "match_not_found")
            if m.status != "lobby" or m.id in self._tasks:
                raise HTTPException(409, "match_not_open")
            if any(p["agent_id"] == str(agent.id) for p in m.players):
                raise HTTPException(409, "already_joined")
            if len(m.players) >= _players_required(m.config):
                raise HTTPException(409, "match_full")
            m.players = [
                *m.players,
                {
                    "agent_id": str(agent.id),
                    "seat": len(m.players),
                    "side": None,
                    "name": agent.display_name,
                },
            ]
            await session.commit()
            self._register(m)
            if len(m.players) >= _players_required(m.config):
                await self.start(m, session)
        await _publish_lobby(m, "started" if m.status == "running" else "join")
        return m

    async def leave(self, match: Match, agent: Agent, session: AsyncSession) -> Match:
        lock = self._lifecycle_locks.setdefault(match.id, asyncio.Lock())
        async with lock:
            m = await session.scalar(select(Match).where(Match.id == match.id).with_for_update())
            if m is None:
                raise HTTPException(404, "match_not_found")
            if m.status != "lobby" or m.id in self._tasks:
                raise HTTPException(409, "match_not_open")
            if not any(p["agent_id"] == str(agent.id) for p in m.players):
                raise HTTPException(409, "not_joined")
            remaining = [p for p in m.players if p["agent_id"] != str(agent.id)]
            m.players = [{**player, "seat": seat} for seat, player in enumerate(remaining)]
            await session.commit()
            self._register(m)
            if not m.players:
                await self._close_empty_lobby(m, session)
                return m
        await _publish_lobby(m, "leave")
        return m

    async def _close_empty_lobby(self, m: Match, session: AsyncSession) -> None:
        m.status = "closed"
        m.ended_at = _now()
        await session.commit()
        self._registry.pop(m.id, None)
        self._lifecycle_locks.pop(m.id, None)
        await _publish_lobby(m, "closed")

    async def start(self, match: Match, session: AsyncSession) -> Match:
        m = await self._managed(match, session)
        if m.id in self._tasks:
            return m
        engine_cls = REGISTRY[m.game_type]
        engine = engine_cls(m.config, m.seed, list(m.players))
        self._engines[m.id] = engine
        self._buffers[m.id] = {}
        self._ledgers[m.id] = []
        self._last_publish_at[m.id] = 0.0
        m.status = "running"
        m.started_at = _now()
        await session.commit()
        self._tasks[m.id] = asyncio.create_task(self._run_loop(m, engine))
        await publish(f"match:{m.id}", self.observation(m))
        return m

    # ---- engine host (single loop per match) ----------------------------------

    async def _run_loop(self, orm_match: Match, engine: BaseGame) -> None:
        """Drive the match until terminal. Real-time ticks; turn-based checks the
        clock and drains buffered legal moves. All engine mutation is here."""
        try:
            if engine.mode == "realtime":
                interval = 1.0 / max(1, int(engine.config.get("tick_rate", 30)))
                while not engine.is_terminal():
                    await asyncio.sleep(interval)
                    self._tick_realtime(orm_match.id, engine)
                    await self._maybe_publish(orm_match, engine)
            else:
                while not engine.is_terminal():
                    await asyncio.sleep(CLOCK_RESOLUTION_S)
                    seat = engine.current_seat()
                    remaining = engine.clock_ms(seat)
                    if remaining is not None and remaining <= 0:
                        engine.timeout_loss(seat)
                        break
                    if self._buffers.get(orm_match.id, {}).get(seat):
                        self._apply_turnbased(orm_match, engine)
                        await self._maybe_publish(orm_match, engine)
            await self._finish(orm_match, engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A match loop must never die silently: log loudly and mark the
            # match errored in the DB so it doesn't linger as "running" forever.
            logger.exception("match %s loop crashed; marking match errored", orm_match.id)
            await self._mark_errored(orm_match.id)
            self._finish_cleanup(orm_match.id)

    def _tick_realtime(self, match_id: uuid.UUID, engine: BaseGame) -> None:
        moves: dict[int, object] = {}
        buf = self._buffers.get(match_id, {})
        for seat, item in list(buf.items()):
            moves[seat] = item["action"]
        buf.clear()
        engine.step(moves)
        if moves:
            self._ledgers[match_id].append(
                {
                    "tick": engine.tick,
                    "moves": {str(seat): action for seat, action in moves.items()},
                }
            )

    def _apply_turnbased(self, orm_match: Match, engine: BaseGame) -> None:
        seat = engine.current_seat()
        buffer = self._buffers.get(orm_match.id, {})
        item = buffer.pop(seat, None)
        if item is None or engine.is_terminal():
            return
        if item["turn"] != getattr(engine, "move_count", 0):
            return
        try:
            engine.apply_action(item["action"])
        except IllegalMove:
            return  # rejected; keep waiting (endpoint already validated — defensive)
        # SAN for notation export, when a chess-variant engine provides it.
        san = None
        if isinstance(engine.last_move, dict):
            san = engine.last_move.get("san")
        self._ledgers[orm_match.id].append(
            {
                "tick": getattr(engine, "move_count", 0),
                "seat": seat,
                "agent_id": self._seat_agent(orm_match, seat),
                "action": item["action"],
                "intent": item.get("intent"),
                "san": san,
            }
        )

    async def _mark_errored(self, match_id: uuid.UUID) -> None:
        """Best-effort: record a crashed match as 'error' so it stops showing
        as a live game. Failures here are logged, never raised."""
        try:
            async with get_sessionmaker()() as session:
                m = await session.get(Match, match_id)
                if m is not None and m.status == "running":
                    m.status = "error"
                    m.ended_at = _now()
                    await session.commit()
                    self._registry.pop(match_id, None)
        except Exception:
            logger.exception("failed to mark match %s as errored", match_id)

    async def _maybe_publish(self, orm_match: Match, engine: BaseGame) -> None:
        # _finish publishes the committed terminal state; never emit a
        # terminal engine paired with a still-"running" ORM status here.
        if engine.is_terminal():
            return
        now = asyncio.get_running_loop().time()
        previous = self._last_publish_at.get(orm_match.id, 0.0)
        if now - previous < 1 / MAX_SPECTATOR_FPS:
            return
        self._last_publish_at[orm_match.id] = now
        await publish(f"match:{orm_match.id}", self.observation(orm_match))

    # ---- action submission ----------------------------------------------------

    async def submit_action(
        self,
        match: Match,
        agent: Agent,
        action: dict,
        intent: str | None = None,
    ) -> dict:
        """Validate + enqueue an action. Returns the latest observation.

        Real-time: buffered, applied on next tick (noop if absent).
        Turn-based: validated for turn + legality before buffering.
        """
        engine = self._engines.get(match.id)
        if engine is None:
            raise HTTPException(409, "match_not_running")
        if match.status != "running":
            raise HTTPException(409, "match_not_running")

        seat = next((p["seat"] for p in match.players if p["agent_id"] == str(agent.id)), None)
        if seat is None:
            raise HTTPException(403, "not_in_match")

        if engine.mode == "turnbased":
            if seat != engine.current_seat():
                raise HTTPException(409, "not_your_turn")
            legal = engine.get_legal_actions(seat)

            def _norm(x):
                # drop keys whose value is None so the client may echo a legal
                # action verbatim (chess emits "promotion": None) and still match.
                if isinstance(x, dict):
                    return {k: v for k, v in x.items() if v is not None}
                return x

            def _match(candidate):
                return _norm(candidate) == _norm(action)

            if engine.legal_actions_exhaustive(seat):
                if not any(_match(candidate) for candidate in legal):
                    raise HTTPException(status_code=400, detail=f"invalid_move: {action}")
            else:
                try:
                    engine.validate_action(action, seat)
                except IllegalMove as exc:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": exc.code, "message": exc.message},
                    ) from exc
            if seat in self._buffers[match.id]:
                raise HTTPException(409, "action_pending")
            self._buffers[match.id][seat] = {
                "action": action,
                "intent": intent,
                "turn": getattr(engine, "move_count", 0),
            }
        else:
            if action:
                self._buffers[match.id][seat] = {
                    "action": action,
                    "intent": intent,
                }
        return self.observation(match, viewer_agent_id=str(agent.id))

    # ---- reads ----------------------------------------------------------------

    async def get(self, match_id: uuid.UUID, session: AsyncSession) -> Match | None:
        if match_id in self._registry:
            return self._registry[match_id]
        match = await session.get(Match, match_id)
        # Only open lobbies need process-local lifecycle state. Caching every
        # historical match read would make the registry grow without bound.
        if match is not None and match.status == "lobby":
            self._register(match)
        return match

    def _seat_agent(self, match: Match, seat: int) -> str | None:
        for p in match.players:
            if p["seat"] == seat:
                return p["agent_id"]
        return None

    def observation(self, match: Match, viewer_agent_id: str | None = None) -> dict:
        perspective = next(
            (
                int(player["seat"])
                for player in match.players
                if viewer_agent_id is not None and player["agent_id"] == viewer_agent_id
            ),
            None,
        )
        engine = self._engines.get(match.id)
        if engine is None:
            result = match.result or {}
            return {
                "match_id": str(match.id),
                "game": match.game_type,
                "mode": match.mode,
                "tick": match.tick_or_move_count or 0,
                "status": match.status,
                "players": match.players,
                "your_player_id": viewer_agent_id if perspective is not None else None,
                "state": {},
                "legal_actions": [],
                "scores": result.get("scores", {}),
                "summary": result.get("final_summary") or f"Match in {match.status}",
                "last_move": None,
                "time": None,
                "render": result.get("final_render", {}),
            }
        obs = engine.observe(perspective=perspective)
        tick = getattr(engine, "tick", getattr(engine, "move_count", 0))
        return {
            "match_id": str(match.id),
            "game": match.game_type,
            "mode": match.mode,
            "tick": tick,
            "status": match.status,
            "players": match.players,
            "your_player_id": viewer_agent_id if perspective is not None else None,
            "state": obs.get("state", {}),
            "legal_actions": obs.get("legal_actions", []),
            "scores": obs.get("scores", {}),
            "summary": obs.get("summary", ""),
            "last_move": obs.get("last_move"),
            "time": obs.get("time"),
            "render": engine.get_render_data(),
        }

    # ---- finish / persistence -------------------------------------------------

    async def _finish(self, orm_match: Match, engine: BaseGame) -> None:
        winner_seats = engine.get_winner() or []
        winner_agents = [
            self._seat_agent(orm_match, s) for s in winner_seats if self._seat_agent(orm_match, s)
        ]
        draw = not winner_agents and engine.is_terminal()
        result = {
            "winner_seats": winner_seats,
            "winner_agents": winner_agents,
            "scores": engine.get_scores(),
            "reason": "draw" if draw else ("finished" if winner_agents else "ended"),
            # keep the terminal board so finished matches stay viewable after
            # the engine is evicted (observation() falls back to this)
            "final_render": engine.get_render_data(),
            "final_summary": engine.summary(),
        }

        lock = self._lifecycle_locks.setdefault(orm_match.id, asyncio.Lock())
        async with lock, get_sessionmaker()() as session:
            m = await session.scalar(
                select(Match).where(Match.id == orm_match.id).with_for_update()
            )
            if m is None or m.status == "finished":
                self._finish_cleanup(orm_match.id)
                return
            if m.status != "running":
                self._finish_cleanup(orm_match.id)
                return
            m.status = "finished"
            m.ended_at = _now()
            m.tick_or_move_count = getattr(engine, "tick", getattr(engine, "move_count", 0))
            m.result = result
            ledger = self._ledgers.get(orm_match.id, [])
            sans = [entry["san"] for entry in ledger if entry.get("san")]
            if sans:
                m.notation = build_pgn(
                    orm_match,
                    sans,
                    winner_seats,
                    initial_fen=getattr(engine, "pgn_initial_fen", None),
                    variant=getattr(engine, "pgn_variant", None),
                )
            for entry in ledger:
                moves = entry.get("moves")
                session.add(
                    ActionLogEntry(
                        match_id=orm_match.id,
                        tick_or_move=entry.get("tick", 0),
                        agent_id=(
                            uuid.UUID(entry["agent_id"])
                            if entry.get("agent_id") is not None
                            else None
                        ),
                        action_json=({"moves": moves} if moves is not None else entry["action"]),
                        intent=entry.get("intent"),
                    )
                )
            cat = _catalog(m.game_type)
            if (
                cat
                and cat.get("elo_ranked")
                and m.config.get("ranked", True)
                and len(m.players) == 2
            ):
                seat_ids = [
                    uuid.UUID(agent_id)
                    for seat in (0, 1)
                    if (agent_id := self._seat_agent(orm_match, seat)) is not None
                ]
                if len(seat_ids) == 2:
                    await update_ratings(
                        session,
                        m.game_type,
                        seat_ids,
                        winner_seats,
                        match_id=m.id,
                    )
            await session.commit()
            self._registry[orm_match.id] = m

        # publish the FINAL board state (with finished status from the committed
        # registry copy) before cleanup: cleanup runs inside the owning task, so
        # any await after it risks cancellation
        await publish(
            f"match:{orm_match.id}",
            self.observation(self._registry.get(orm_match.id, orm_match)),
        )
        self._finish_cleanup(orm_match.id)

    def _finish_cleanup(self, match_id: uuid.UUID) -> None:
        task = self._tasks.pop(match_id, None)
        # cleanup runs inside the owning loop task on natural finishes; never
        # self-cancel (it poisons the task's terminal state as CancelledError
        # and used to kill the final publish that awaited after this call)
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._engines.pop(match_id, None)
        self._buffers.pop(match_id, None)
        self._ledgers.pop(match_id, None)
        self._last_publish_at.pop(match_id, None)
        self._registry.pop(match_id, None)
        self._lifecycle_locks.pop(match_id, None)


# Module-level singleton: the authoritative in-process registry.
manager = MatchManager()
