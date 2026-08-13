"""Typed public match timelines must remain useful without leaking raw actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.api.matches import match_timeline
from app.db import get_sessionmaker, init_db
from app.engine.match_manager import manager
from app.models import ActionLogEntry, Agent, Match
from app.services import messaging


async def test_running_timeline_separates_chat_operations_and_specialized_topics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    await init_db()
    async with get_sessionmaker()() as session:
        agent = Agent(
            display_name=f"timeline-{uuid.uuid4().hex[:8]}",
            api_key_hash=f"timeline-hash-{uuid.uuid4().hex}",
            stats={},
        )
        session.add(agent)
        await session.flush()
        match = Match(
            game_type="last_server",
            mode="turnbased",
            status="running",
            config={},
            seed=7,
            players=[{"agent_id": str(agent.id), "seat": 0, "name": "Timeline"}],
            started_at=datetime.now(UTC),
        )
        session.add(match)
        await session.commit()

        await messaging.post_message(
            session,
            channel=str(match.id),
            author_id=agent.id,
            content="I distrust seat four.",
        )
        specialized = await messaging.post_message(
            session,
            channel=str(match.id),
            author_id=agent.id,
            content="Trust declaration: seat two.",
            kind="specialized",
            topic="trust-declaration",
            tick_reference=3,
        )
        assert specialized.kind == "specialized"

        manager._ledgers[match.id] = [
            {
                "tick": 4,
                "agent_id": str(agent.id),
                "action": {"mission": "sabotage"},
                "public_event": {
                    "subtype": "mission_action_submitted",
                    "summary": "A private mission action was submitted",
                    "intent": None,
                    "last_move": {"event": "mission_action_submitted", "submitted": 1},
                    "terminal": False,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            }
        ]
        try:
            timeline = await match_timeline(match.id, limit=100, _rate=None, session=session)
            categories = {event["category"] for event in timeline["events"]}
            assert {"chat", "specialized", "operation", "system"} <= categories
            assert any(
                event["subtype"] == "trust-declaration"
                for event in timeline["events"]
                if event["category"] == "specialized"
            )
            assert "sabotage" not in repr(timeline)
            assert any(
                event["actor_id"] == str(agent.id)
                for event in timeline["events"]
                if event["category"] == "operation"
            )
            assert timeline["visibility"] == {
                "scope": "public",
                "raw_actions_included": False,
                "terminal_audit_revealed": False,
            }
        finally:
            manager._ledgers.pop(match.id, None)


async def test_message_type_validation_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    await init_db()
    async with get_sessionmaker()() as session:
        agent = Agent(
            display_name=f"typed-{uuid.uuid4().hex[:8]}",
            api_key_hash=f"typed-hash-{uuid.uuid4().hex}",
            stats={},
        )
        session.add(agent)
        await session.commit()
        with pytest.raises(ValueError, match="chat_topic_not_allowed"):
            await messaging.post_message(
                session,
                channel="global",
                author_id=agent.id,
                content="misclassified",
                topic="trade",
            )
        with pytest.raises(ValueError, match="invalid_specialized_topic"):
            await messaging.post_message(
                session,
                channel="global",
                author_id=agent.id,
                content="missing topic",
                kind="specialized",
            )
        root = await messaging.post_message(
            session,
            channel="global",
            author_id=agent.id,
            content="General root",
        )
        with pytest.raises(ValueError, match="parent_message_type_mismatch"):
            await messaging.post_message(
                session,
                channel="global",
                author_id=agent.id,
                content="Mismatched reply",
                kind="specialized",
                topic="negotiation",
                parent_id=root.id,
            )


async def test_legacy_action_intent_is_not_rendered_as_general_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_publish(*_args, **_kwargs):
        return True

    monkeypatch.setattr(messaging, "publish", no_publish)
    await init_db()
    async with get_sessionmaker()() as session:
        agent = Agent(
            display_name=f"legacy-{uuid.uuid4().hex[:8]}",
            api_key_hash=f"legacy-hash-{uuid.uuid4().hex}",
            stats={},
        )
        session.add(agent)
        await session.flush()
        match = Match(
            game_type="chess",
            mode="turnbased",
            status="finished",
            config={},
            seed=11,
            players=[{"agent_id": str(agent.id), "seat": 0, "name": "Legacy"}],
            tick_or_move_count=1,
            result={"final_summary": "Finished"},
            ended_at=datetime.now(UTC),
        )
        session.add(match)
        await session.flush()
        session.add(
            ActionLogEntry(
                match_id=match.id,
                tick_or_move=1,
                agent_id=agent.id,
                action_json={"from": "e2", "to": "e4"},
                intent="Claiming the center.",
            )
        )
        await session.commit()
        await messaging.post_message(
            session,
            channel=str(match.id),
            author_id=agent.id,
            content="Claiming the center.",
            tick_reference=0,
        )
        await messaging.post_message(
            session,
            channel=str(match.id),
            author_id=agent.id,
            content="Actual conversation.",
            tick_reference=0,
        )

        timeline = await match_timeline(match.id, limit=100, _rate=None, session=session)
        by_content = {event["content"]: event for event in timeline["events"]}
        assert by_content["Claiming the center."]["category"] == "operation"
        assert by_content["Claiming the center."]["subtype"] == "action_intent"
        assert by_content["Actual conversation."]["category"] == "chat"
        assert repr(timeline).count("Claiming the center.") == 1
