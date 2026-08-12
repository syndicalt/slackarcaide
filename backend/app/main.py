"""FastAPI app factory + lifespan. Routers are wired in after feature modules exist."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_db, recover_interrupted_matches
from app.redis import close_redis


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
    async with app.state.mcp_session_manager.run():
        yield
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agent Arcade", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        code = detail if isinstance(detail, str) else detail.get("code", "http_error")
        message = detail if isinstance(detail, str) else detail.get("message", str(detail))
        return _error(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "Request validation failed", exc.errors())

    @app.get("/health")
    async def health():
        return {"status": "ok"}

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
        # Host validation is handled by the outer app/ingress
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.state.mcp_session_manager = mcp_server.session_manager
    app.mount("/mcp", mcp_app)

    return app


app = create_app()
