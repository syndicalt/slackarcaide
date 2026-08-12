"""Aggregates feature routers onto the app. This is the single integration point so
feature agents can author routers in isolation; only this module is edited to register them."""

from fastapi import FastAPI

from app.api import agents, guide, leaderboards, matches, messages, ws


def register_routers(app: FastAPI) -> None:
    app.include_router(agents.router)
    app.include_router(agents.auth_router)
    app.include_router(guide.router)
    app.include_router(leaderboards.router)
    app.include_router(matches.router)
    app.include_router(messages.router)
    app.include_router(ws.router)
