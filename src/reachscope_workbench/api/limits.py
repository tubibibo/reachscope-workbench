"""Bound request bodies before multipart decoding or JSON parsing consumes them."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLarge(Exception):
    pass


class RequestBudgetMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        budget = (257 * 1024 * 1024) if scope.get("path") == "/api/uploads" else 128 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = budget + 1
        if length > budget or length < 0:
            await self.reject(scope, receive, send)
            return
        consumed = 0
        started = False
        exceeded = False

        async def limited_receive() -> Message:
            nonlocal consumed, exceeded
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > budget:
                    exceeded = True
                    raise BodyTooLarge
            return message

        async def watched_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                # Some request parsers turn receive exceptions into a generic
                # 400. Preserve the actual budget failure before headers escape.
                if exceeded:
                    raise BodyTooLarge
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, watched_send)
        except BodyTooLarge:
            if started:
                raise
            await self.reject(scope, receive, send)

    @staticmethod
    async def reject(scope: Scope, receive: Receive, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id", "")
        response = JSONResponse({"error": {"code": "REQUEST_LIMIT", "message": "请求体超过允许的大小",
                                           "request_id": request_id, "retryable": False}},
                                status_code=413)
        await response(scope, receive, send)
