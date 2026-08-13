"""Platform boundary tests for games with seat-private state."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import HTTPException

from app.auth import hash_key
from app.db import get_sessionmaker, init_db
from app.engine.base import BaseGame, IllegalMove
from app.engine.match_manager import MatchManager, manager
from app.main import app
from app.models import Agent, Match


class _PrivateProbeGame(BaseGame):
    mode = "turnbased"
    name = "private_probe"

    def reset(self) -> None:
        self.last_move = None

    def current_seat(self) -> int:
        return 0

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [{"probe": True}] if seat == 0 else []

    def apply_action(self, action) -> None:
        self.last_move = dict(action)

    def get_render_data(self) -> dict:
        return {"public": "spectator-safe"}

    def observe(self, perspective: int | None = None) -> dict:
        state = {"public": "spectator-safe"}
        if perspective is not None:
            state["private_for"] = perspective
        return {
            "state": state,
            "legal_actions": self.get_legal_actions(perspective) if perspective is not None else [],
            "scores": {},
            "summary": "private probe",
            "last_move": self.last_move,
            "time": None,
        }


class _SchemaActionProbeGame(_PrivateProbeGame):
    def get_legal_actions(self, seat: int) -> list[dict]:
        return [{"schema": {"token": "positive integer"}}] if seat == 0 else []

    def legal_actions_exhaustive(self, seat: int) -> bool:
        return False

    def validate_action(self, action, seat: int) -> None:
        if seat != 0 or not isinstance(action, dict) or action.get("token") != 7:
            raise IllegalMove("invalid_token", "token must equal seven")


def _running_match(agent_ids: list[uuid.UUID]) -> Match:
    return Match(
        id=uuid.uuid4(),
        game_type="private_probe",
        mode="turnbased",
        status="running",
        config={},
        seed=7,
        players=[
            {"agent_id": str(agent_id), "seat": seat, "side": None, "name": f"p{seat}"}
            for seat, agent_id in enumerate(agent_ids)
        ],
    )


def test_manager_maps_only_match_participants_to_private_perspectives() -> None:
    agent_ids = [uuid.uuid4(), uuid.uuid4()]
    match = _running_match(agent_ids)
    host = MatchManager()
    host._engines[match.id] = _PrivateProbeGame({}, 7, list(match.players))

    public = host.observation(match)
    seat_zero = host.observation(match, viewer_agent_id=str(agent_ids[0]))
    seat_one = host.observation(match, viewer_agent_id=str(agent_ids[1]))
    outsider = host.observation(match, viewer_agent_id=str(uuid.uuid4()))

    assert public["state"] == outsider["state"] == {"public": "spectator-safe"}
    assert public["your_player_id"] is None
    assert outsider["your_player_id"] is None
    assert seat_zero["state"]["private_for"] == 0
    assert seat_one["state"]["private_for"] == 1
    assert seat_zero["your_player_id"] == str(agent_ids[0])
    assert seat_one["your_player_id"] == str(agent_ids[1])
    assert public["render"] == seat_zero["render"] == {"public": "spectator-safe"}


async def test_submit_action_response_uses_the_callers_private_perspective() -> None:
    agent_ids = [uuid.uuid4(), uuid.uuid4()]
    match = _running_match(agent_ids)
    host = MatchManager()
    host._engines[match.id] = _PrivateProbeGame({}, 7, list(match.players))
    host._buffers[match.id] = {}
    caller = Agent(id=agent_ids[0], display_name="private-caller", api_key_hash="hash", stats={})

    response = await host.submit_action(match, caller, {"probe": True})

    assert response["state"]["private_for"] == 0
    assert response["your_player_id"] == str(agent_ids[0])
    assert response["render"] == {"public": "spectator-safe"}


async def test_non_exhaustive_action_is_validated_before_buffering() -> None:
    agent_ids = [uuid.uuid4(), uuid.uuid4()]
    match = _running_match(agent_ids)
    host = MatchManager()
    host._engines[match.id] = _SchemaActionProbeGame({}, 7, list(match.players))
    host._buffers[match.id] = {}
    caller = Agent(id=agent_ids[0], display_name="schema-caller", api_key_hash="hash", stats={})

    with pytest.raises(HTTPException) as error:
        await host.submit_action(match, caller, {"token": 3})

    assert error.value.status_code == 400
    assert error.value.detail == {
        "code": "invalid_token",
        "message": "token must equal seven",
    }
    assert host._buffers[match.id] == {}

    await host.submit_action(match, caller, {"token": 7})
    assert host._buffers[match.id][0]["action"] == {"token": 7}


async def test_state_endpoint_is_public_safe_and_authentication_unlocks_only_own_seat() -> None:
    await init_db()
    raw_keys = [f"arc_private_probe_{uuid.uuid4().hex}" for _ in range(2)]
    async with get_sessionmaker()() as session:
        players = [
            Agent(
                display_name=f"private-probe-{uuid.uuid4().hex}",
                api_key_hash=hash_key(raw_key),
                stats={},
            )
            for raw_key in raw_keys
        ]
        session.add_all(players)
        await session.flush()
        match = _running_match([player.id for player in players])
        session.add(match)
        await session.commit()

    manager._registry[match.id] = match
    manager._engines[match.id] = _PrivateProbeGame({}, match.seed, list(match.players))
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            public = await client.get(f"/matches/{match.id}/state")
            private = await client.get(
                f"/matches/{match.id}/state",
                headers={"Authorization": f"Bearer {raw_keys[1]}"},
            )
            rejected = await client.get(
                f"/matches/{match.id}/state",
                headers={"Authorization": "Bearer invalid"},
            )

        assert public.status_code == 200
        assert public.json()["state"] == {"public": "spectator-safe"}
        assert private.status_code == 200
        assert private.json()["state"]["private_for"] == 1
        assert private.json()["your_player_id"] == str(players[1].id)
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "invalid_api_key"
    finally:
        manager._engines.pop(match.id, None)
        manager._registry.pop(match.id, None)
