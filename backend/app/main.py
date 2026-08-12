"""FastAPI application factory, dependency health, and resource lifecycle."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.bodylimit import RequestBodyLimitMiddleware
from app.config import get_settings
from app.db import close_db, get_sessionmaker, init_db, recover_interrupted_matches
from app.metrics import HttpMetricsMiddleware, prometheus_metrics
from app.realtime.fanout import close_fanout
from app.redis import close_redis, get_redis


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Engines are in-process only: any match left "running" by a restart/reload
    # can never resume, so mark it errored instead of ghosting the lobby.
    await recover_interrupted_matches()
    # the mounted streamable-HTTP MCP app needs its session manager running;
    # mounted sub-app lifespans don't fire, so we run it in ours
    try:
        async with app.state.mcp_session_manager.run():
            yield
    finally:
        from app.mcp_host import close_mcp_client

        await close_fanout()
        await close_mcp_client()
        await close_redis()
        await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agent Arcade", version="0.1.0", lifespan=lifespan)

    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_origin_list != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(HttpMetricsMiddleware)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            code = message = detail
        elif isinstance(detail, dict):
            code = detail.get("code", "http_error")
            message = detail.get("message", str(detail))
        else:
            code = "http_error"
            message = str(detail)
        return _error(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return _error(
            422,
            "validation_error",
            "Request validation failed",
            jsonable_encoder(exc.errors()),
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def readiness():
        checks: dict[str, str] = {}
        try:
            async with asyncio.timeout(2.0):
                async with get_sessionmaker()() as session:
                    await session.execute(select(1))
            checks["database"] = "ok"
        except (TimeoutError, SQLAlchemyError, OSError, ValueError):
            checks["database"] = "unavailable"
        try:
            async with asyncio.timeout(2.0):
                await (await get_redis()).ping()
            checks["redis"] = "ok"
        except (TimeoutError, RedisError, OSError, ValueError):
            checks["redis"] = "unavailable"
        if any(value != "ok" for value in checks.values()):
            return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
        return {"status": "ready", "checks": checks}

    app.add_api_route("/metrics", prometheus_metrics, include_in_schema=False)

    # ---- feature routers (registered at integration; wired in app/api/__init__.py) ----
    from app.api import register_routers

    register_routers(app)

    # ---- hosted MCP endpoint (streamable HTTP) at /mcp/ ----
    from mcp.server.transport_security import TransportSecuritySettings

    from app.mcp_host import mcp as mcp_server

    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_host_list,
            allowed_origins=(
                [] if settings.cors_origin_list == ["*"] else settings.cors_origin_list
            ),
        ),
    )
    app.state.mcp_session_manager = mcp_server.session_manager
    app.mount("/mcp", mcp_app)

    return app


app = create_app()
