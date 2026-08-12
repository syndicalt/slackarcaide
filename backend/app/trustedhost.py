"""Trusted Host enforcement with orchestrator-safe health endpoints."""

from __future__ import annotations

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

_HEALTH_PATHS = frozenset({"/health", "/ready"})


class ApplicationTrustedHostMiddleware:
    """Skip Host validation only for non-sensitive deployment health probes."""

    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        self.trusted_app = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") in _HEALTH_PATHS:
            await self.app(scope, receive, send)
            return
        await self.trusted_app(scope, receive, send)
