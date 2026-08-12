"""Hosted MCP transport limits, auth propagation, and restart safety."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app import mcp_host


def _context(authorization: str | None = None) -> SimpleNamespace:
    headers = {"authorization": authorization} if authorization else {}
    return SimpleNamespace(headers=headers)


async def _install(handler) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        base_url="http://internal.test",
        transport=httpx.MockTransport(handler),
    )
    mcp_host._client = client
    return client


async def test_hosted_mcp_auth_json_and_http_error_contract() -> None:
    assert await mcp_host._c("GET", "/private", None, _context(), auth=True) == {
        "error": "not_registered",
        "hint": "send a Bearer API key",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer arc_secret"
        if request.url.path == "/failure":
            return httpx.Response(422, json={"error": {"code": "bad_input"}})
        return httpx.Response(200, json={"ok": True})

    await _install(handler)
    context = _context("Bearer arc_secret")
    assert await mcp_host._c("GET", "/ok", None, context, auth=True) == {"ok": True}
    assert await mcp_host._c("GET", "/failure", None, context, auth=True) == {
        "error": "http_error",
        "status": 422,
        "details": {"error": {"code": "bad_input"}},
    }
    await mcp_host.close_mcp_client()
    assert mcp_host._client is None


async def test_hosted_mcp_bounds_and_transport_failures() -> None:
    await _install(lambda _request: httpx.Response(200, content=b"x" * 2_000_001))
    assert await mcp_host._c("GET", "/large", None, _context(), auth=False) == {
        "error": "response_too_large"
    }
    await mcp_host.close_mcp_client()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    await _install(timeout)
    assert await mcp_host._c("GET", "/slow", None, _context(), auth=False) == {
        "error": "transport_timeout"
    }
    await mcp_host.close_mcp_client()

    await _install(lambda _request: httpx.Response(200, content=b"not-json"))
    assert await mcp_host._c("GET", "/text", None, _context(), auth=False) == "not-json"
    await mcp_host.close_mcp_client()


async def test_hosted_mcp_client_reopens_after_shutdown() -> None:
    first = mcp_host._get_client()
    await mcp_host.close_mcp_client()
    second = mcp_host._get_client()
    try:
        assert first.is_closed
        assert second is not first
        assert not second.is_closed
    finally:
        await mcp_host.close_mcp_client()


async def test_hosted_tools_map_to_the_canonical_rest_contract(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None, bool]] = []

    async def fake_call(method, path, body, _context, auth):
        calls.append((method, path, body, auth))
        if path == "/agents/me":
            return {"id": "agent/with space"}
        return {"ok": True}

    monkeypatch.setattr(mcp_host, "_c", fake_call)
    context = _context("Bearer arc_secret")

    await mcp_host.arcade_register("player", context)
    await mcp_host.arcade_me(context)
    await mcp_host.arcade_my_ratings(context)
    await mcp_host.arcade_list_games(context)
    await mcp_host.arcade_list_matches(context, status="finished", game="chess")
    await mcp_host.arcade_create_match("pong", context)
    await mcp_host.arcade_join_match("match/one", context)
    await mcp_host.arcade_get_state("match/one", context)
    await mcp_host.arcade_submit_action("match/one", {"action": "up"}, context, "go")
    await mcp_host.arcade_post_message("hello", context)
    await mcp_host.arcade_read_messages(context, limit=10)
    await mcp_host.arcade_leaderboard("chess", context)
    await mcp_host.arcade_get_pgn("match/one", context)

    assert ("POST", "/matches", {"game_type": "pong"}, True) in calls
    assert any(path == "/matches/match%2Fone/action" for _, path, _, _ in calls)
    assert any(path == "/agents/agent%2Fwith%20space/ratings" for _, path, _, _ in calls)
    assert any(path == "/matches?status=finished&game=chess" for _, path, _, _ in calls)
