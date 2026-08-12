"""WebSocket endpoint wiring the realtime hub onto the FastAPI app."""

from fastapi import APIRouter, WebSocket

from app.realtime import hub

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await hub.serve(websocket)
