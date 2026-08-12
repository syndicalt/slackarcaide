"""MatchManager — authoritative in-process match runtime (spec §9, §10, §13).

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
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.engine.base import BaseGame, IllegalMove
from app.engine.registry import GAMES_CATALOG, REGISTRY
from app.models import ActionLogEntry, Agent, Match
from app.realtime.publisher import publish
from app.services.notation import build_pgn
from app.services.ratings import update_ratings

logger = logging.getLogger(__name__)

DEFAULT_MAX_PLAYERS = 2
CLOCK_RESOLUTION_S = 0.1  # turn-based clock granularity


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    """Notify lobby subscribers whenever the open table set changes. 'open',
    'join' and 'leave' fire only while the table is still in the lobby with room
    for a competitor; 'closed' is the terminal event for an emptied lobby and is
    published regardless of the now-'closed' status."""
    if match.status != "lobby" and action != "closed":
        return
    if action != "closed" and _seats_left(match) <= 0:
        return
    await publish("lobby", _lobby_payload(match, action))


class MatchManager:
    """Authoritative registry + engine host. Module-level `manager` singleton."""

    def __init__(self) -> None:
        self._registry: dict[uuid.UUID, Match] = {}
        self._engines: dict[uuid.UUID, BaseGame] = {}
        self._buffers: dict[uuid.UUID, dict[int, list]] = {}
        self._ledgers: dict[uuid.UUID, list[dict]] = {}  # action log collected at run
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._finished_during_run: set[uuid.UUID] = set()

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
        mode: str,
        config: dict,
        session: AsyncSession,
    ) -> Match:
        cat = _catalog(game_type)
        if cat is None or game_type not in REGISTRY:
            raise HTTPException(404, "unknown_game")
        config = dict(config or {})
        config.setdefault("players_required", cat["players_before_start"])
        config.setdefault("max_players", cat["players_before_start"])
        if cat["elo_ranked"]:
            # custom start positions would allow trivial Elo farming (e.g.
            # starting one move from mate); ranked games always start standard
            config.pop("start_fen", None)
        seed = config.get("seed")
        match = Match(
            game_type=game_type,
            mode=cat["mode"],
            status="lobby",
            config=config,
            seed=int(seed) if seed is not None else random.getrandbits(31),
            players=[{"agent_id": str(agent.id), "seat": 0, "side": None,
                      "name": agent.display_name}],
        )
        session.add(match)
        await session.commit()
        self._register(match)
        # single-player matches (breakout/tetris/asteroids) must start without a
        # join; multi-player starts on the final join below.
        if len(match.players) >= _players_required(match.config):
            await self.start(match, session)
        await _publish_lobby(match, "open")
        return match

    async def join(self, match: Match, agent: Agent, session: AsyncSession) -> Match:
        m = await self._managed(match, session)
        if m.id in self._tasks:  # already starting/running
            raise HTTPException(409, "match_not_open")
        if any(p["agent_id"] == str(agent.id) for p in m.players):
            raise HTTPException(409, "already_joined")
        m.players = list(m.players) + [
            {"agent_id": str(agent.id), "seat": len(m.players), "side": None,
             "name": agent.display_name}
        ]
        await session.commit()
        # auto-start once enough players
        if len(m.players) >= _players_required(m.config):
            await self.start(m, session)
        await _publish_lobby(m, "join")
        return m

    async def leave(self, match: Match, agent: Agent, session: AsyncSession) -> Match:
        m = await self._managed(match, session)
        if m.status != "lobby" or m.id in self._tasks:
            raise HTTPException(409, "match_not_open")
        m.players = [p for p in m.players if p["agent_id"] != str(agent.id)]
        await session.commit()
        if not m.players:
            # a lobby with nobody in it is dead — close it so it stops
            # advertising for competitors instead of lingering as "lobby".
            await self._close_empty_lobby(m, session)
            return m
        await _publish_lobby(m, "leave")
        return m

    async def _close_empty_lobby(self, m: Match, session: AsyncSession) -> None:
        m.status = "closed"
        m.ended_at = _now()
        await session.commit()
        self._registry.pop(m.id, None)
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
                    # apply the oldest buffered legal move for the current seat
                    if self._buffers.get(orm_match.id, {}).get(seat):
                        self._apply_turnbased(orm_match, engine)
                        await self._maybe_publish(orm_match, engine)
                        continue
                    # clock timeout → current seat loses
                    remaining = engine.clock_ms(seat)
                    if remaining is not None and remaining <= 0:
                        engine.timeout_loss(seat)
                        break
            await self._finish(orm_match, engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A match loop must never die silently: log loudly and mark the
            # match errored in the DB so it doesn't linger as "running" forever.
            logger.exception("match %s loop crashed; marking match errored", orm_match.id)
            self._tasks.pop(orm_match.id, None)
            self._finished_during_run.add(orm_match.id)
            await self._mark_errored(orm_match.id)

    def _tick_realtime(self, match_id: uuid.UUID, engine: BaseGame) -> None:
        moves: dict[int, object] = {}
        buf = self._buffers.get(match_id, {})
        for seat, actions in list(buf.items()):
            if actions:
                # items are {"action": <move>, "intent": ...}; engines consume
                # the raw move payload, not the wrapper.
                moves[seat] = actions[-1]["action"]  # latest action this tick
                buf[seat].clear()
        if any(moves.values()):
            self._ledgers[match_id].append(
                {"tick": engine.tick, "moves": {str(k): v for k, v in moves.items()}}
            )
        try:
            engine.step(moves)
        except Exception:
            # Engine code runs on the event loop; a single bad tick (malformed
            # client input the engine didn't reject, engine bug) must not kill
            # the match. Log and skip the tick — determinism note: this makes
            # the affected tick a noop, so replay-after-crash is approximate.
            logger.exception("match %s engine.step failed; tick skipped", match_id)

    def _apply_turnbased(self, orm_match: Match, engine: BaseGame) -> None:
        seat = engine.current_seat()
        actions = self._buffers.get(orm_match.id, {}).get(seat, [])
        if not actions or engine.is_terminal():
            return
        item = actions.pop(0)
        try:
            engine.apply_action(item["action"])
        except IllegalMove:
            return  # rejected; keep waiting (endpoint already validated — defensive)
        # SAN for notation export, when the engine provides it (chess)
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
                    self._registry[match_id] = m
        except Exception:
            logger.exception("failed to mark match %s as errored", match_id)

    async def _maybe_publish(self, orm_match: Match, engine: BaseGame) -> None:
        # publish throttled per tick already; publish every tick for live feel
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

        seat = next(
            (p["seat"] for p in match.players if p["agent_id"] == str(agent.id)), None
        )
        if seat is None:
            raise HTTPException(403, "not_in_match")

        if engine.mode == "turnbased":
            if seat != engine.current_seat():
                raise HTTPException(409, "not_your_turn")
            legal = engine.get_legal_actions(seat)

            def _norm(x):
                # drop keys whose value is None so the client may echo a legal
                # action verbatim (engines emit e.g. chess "promotion": None,
                # checkers "moves": None) and still match.
                if isinstance(x, dict):
                    return {k: v for k, v in x.items() if v is not None}
                return x

            def _match(candidate):
                return _norm(candidate) == _norm(action)

            if legal and not any(_match(c) for c in legal):
                raise HTTPException(status_code=400, detail=f"invalid_move: {action}")
            self._buffers[match.id].setdefault(seat, []).append(
                {"action": action, "intent": intent}
            )
        else:
            if action:
                self._buffers[match.id].setdefault(seat, []).append(
                    {"action": action, "intent": intent}
                )
        return self.observation(match)

    # ---- reads ----------------------------------------------------------------

    async def get(self, match_id: uuid.UUID, session: AsyncSession) -> Match | None:
        if match_id in self._registry:
            return self._registry[match_id]
        match = await session.get(Match, match_id)
        if match is not None:
            self._register(match)
        return match

    async def list_open(self, session: AsyncSession) -> list[Match]:
        result = await session.scalars(select(Match).where(Match.status == "lobby"))
        matches = list(result.all())
        for m in matches:
            self._register(m)
        return matches

    def _seat_agent(self, match: Match, seat: int) -> str | None:
        for p in match.players:
            if p["seat"] == seat:
                return p["agent_id"]
        return None

    def observation(self, match: Match) -> dict:
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
                "your_player_id": None,
                "state": {},
                "legal_actions": [],
                "scores": result.get("scores", {}),
                "summary": result.get("final_summary") or f"Match in {match.status}",
                "last_move": None,
                "time": None,
                "render": result.get("final_render", {}),
            }
        obs = engine.observe()
        tick = getattr(engine, "tick", getattr(engine, "move_count", 0))
        return {
            "match_id": str(match.id),
            "game": match.game_type,
            "mode": match.mode,
            "tick": tick,
            "status": match.status,
            "players": match.players,
            "your_player_id": None,  # shared broadcast; per-seat via API if needed
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
        if orm_match.id in self._finished_during_run:
            self._finish_cleanup(orm_match.id)
            return
        self._finished_during_run.add(orm_match.id)

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

        async with get_sessionmaker()() as session:
            m = await session.get(Match, orm_match.id)
            if m is None:
                return
            m.status = "finished"
            m.ended_at = _now()
            m.tick_or_move_count = getattr(engine, "tick", getattr(engine, "move_count", 0))
            m.result = result
            # notation export (PGN) when the engine emitted SAN during play
            sans = [
                e["san"]
                for e in self._ledgers.get(orm_match.id, [])
                if e.get("san")
            ]
            if sans:
                m.notation = build_pgn(orm_match, sans, winner_seats)
            # flush the full action ledger for deterministic replay
            for entry in self._ledgers.get(orm_match.id, []):
                tick = entry.get("tick", 0)
                agent_id = entry.get("agent_id")
                if agent_id is None:
                    continue
                action_json = entry.get("action", entry.get("moves"))
                session.add(
                    ActionLogEntry(
                        match_id=orm_match.id,
                        tick_or_move=tick,
                        agent_id=uuid.UUID(agent_id),
                        action_json=action_json,
                        intent=entry.get("intent"),
                    )
                )
            await session.flush()
            # update ratings for head-to-head ranked games
            cat = _catalog(m.game_type)
            if cat and cat.get("elo_ranked") and len(m.players) == 2:
                seat_ids = [
                    uuid.UUID(s) if s else None for s in (self._seat_agent(orm_match, 0), self._seat_agent(orm_match, 1))
                ]
                if all(seat_ids):
                    await update_ratings(session, m.game_type, seat_ids, winner_seats)
            await session.commit()
            # replace the registry copy with the freshly-committed terminal state
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


# Module-level singleton: the authoritative in-process registry.
manager = MatchManager()
