"""Low-cardinality Prometheus metrics for HTTP and public WebSockets."""

from __future__ import annotations

import secrets
import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Message, Receive, Scope, Send

from app.config import get_settings

HTTP_REQUESTS = Counter(
    "slackarcaide_http_requests_total",
    "Completed HTTP requests",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "slackarcaide_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)
WEBSOCKET_CONNECTIONS = Gauge(
    "slackarcaide_websocket_connections",
    "Accepted public spectator WebSocket connections",
)


class HttpMetricsMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        status = 500
        started_at = time.perf_counter()

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            route = scope.get("route")
            route_label = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(method, route_label, str(status)).inc()
            HTTP_DURATION.labels(method, route_label).observe(time.perf_counter() - started_at)


async def prometheus_metrics(request: Request) -> Response:
    token = get_settings().metrics_bearer_token
    if token:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not secrets.compare_digest(
            authorization[7:], token
        ):
            return JSONResponse(status_code=401, content={"error": "metrics_unauthorized"})
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
