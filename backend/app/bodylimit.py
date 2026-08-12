"""ASGI request-body limit enforced while bytes are received."""

from __future__ import annotations

from collections import deque

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 64 * 1024
_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class RequestBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_bytes = int(content_length)
            except ValueError:
                await self._reject(scope, send, "invalid_content_length")
                return
            if declared_bytes < 0:
                await self._reject(scope, send, "invalid_content_length")
                return
            if declared_bytes > self.max_bytes:
                await self._reject(scope, send, "request_body_too_large")
                return

        messages: deque[Message] = deque()
        received_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    await self._reject(scope, send, "request_body_too_large")
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def replay_receive() -> Message:
            if messages:
                return messages.popleft()
            return await _empty_receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send, code: str) -> None:
        response = JSONResponse(
            status_code=413 if code == "request_body_too_large" else 400,
            content={"error": {"code": code, "message": code}},
        )
        await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}
