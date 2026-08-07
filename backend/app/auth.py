from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Any


class ApiKeyASGI:
    """Protect a mounted ASGI app with the same DSG API key used by REST routes."""

    def __init__(self, app: Callable[..., Awaitable[Any]], expected_key: str | None):
        self.app = app
        self.expected_key = expected_key

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or self.expected_key is None:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        provided = headers.get("x-api-key")
        authorization = headers.get("authorization", "")
        if provided is None and authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()

        if provided is None or not hmac.compare_digest(provided, self.expected_key):
            body = json.dumps({"detail": "Missing or invalid API key"}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
