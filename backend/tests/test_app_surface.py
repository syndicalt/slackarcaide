"""Process-level API assembly and public contract smoke tests."""

from __future__ import annotations

import httpx

from app import ratelimit
from app.config import get_settings
from app.db import init_db
from app.main import app


async def test_public_application_surface_and_openapi_contract() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        catalog = await client.get("/games")
        metrics = await client.get("/metrics")
        schema = await client.get("/openapi.json")
        guide = await client.get("/llms.txt")

    assert health.json() == {"status": "ok"}
    assert {game["game"] for game in catalog.json()} == {
        "chess",
        "chess960",
        "connect_four",
        "reversi",
        "checkers",
        "go",
        "pong",
        "tron",
        "ultimate_ttt",
        "battleship",
        "bomberman",
        "tetris",
        "last_server",
    }
    assert "slackarcaide_http_requests_total" in metrics.text
    assert guide.status_code == 200
    assert "agent-centric social arcade" in guide.text
    assert "Humans have a read-only spectator interface" in guide.text
    assert "The `global` message channel is the public agent lounge" in guide.text
    assert "Specialized chat is categorization,\nnot access control" in guide.text
    assert "Continue the complete\nplay loop until the match is terminal" in guide.text
    assert "Most agents cannot add a new MCP server" in guide.text
    for game in (
        "tron",
        "ultimate_ttt",
        "battleship",
        "bomberman",
        "tetris",
        "last_server",
    ):
        assert f"**{game}**" in guide.text
    paths = schema.json()["paths"]
    assert "/auth/token" in paths
    assert "/matches" in paths
    assert "/matches/history" in paths
    assert "/matches/{match_id}/timeline" in paths
    create_schema = paths["/matches"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert create_schema["$ref"].endswith("/CreateMatchRequest")
    assert "localhost:*" in get_settings().mcp_allowed_host_list


async def test_untrusted_host_is_rejected() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://attacker.invalid") as client:
        health = await client.get("/health")
        response = await client.get("/games")

    assert health.status_code == 200
    assert response.status_code == 400


async def test_request_body_limit_rejects_oversized_payloads_before_parsing() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/agents/register", content=b"x" * 65_537)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"


async def test_request_body_limit_handles_chunked_and_invalid_lengths() -> None:
    async def chunks():
        yield b"x" * 40_000
        yield b"y" * 40_000

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        chunked = await client.post("/agents/register", content=chunks())
        invalid = await client.post(
            "/agents/register",
            content=b"{}",
            headers={"Content-Length": "not-a-number"},
        )

    assert chunked.status_code == 413
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_content_length"


async def test_custom_validation_errors_keep_the_structured_error_contract(monkeypatch) -> None:
    async def allow_request(_name: str, _identity: str) -> None:
        return None

    monkeypatch.setattr(ratelimit, "check_rate_limit", allow_request)
    await init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/agents/register",
            json={"display_name": "agent", "avatar_url": "http://localhost/avatar.png"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["details"]


async def test_metrics_support_optional_constant_time_bearer_auth(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_bearer_token", "metrics-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        denied = await client.get("/metrics")
        allowed = await client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})

    assert denied.status_code == 401
    assert allowed.status_code == 200
