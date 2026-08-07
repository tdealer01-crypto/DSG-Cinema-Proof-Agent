from __future__ import annotations

import asyncio

from app.auth import ApiKeyASGI


def test_mounted_mcp_auth_rejects_missing_key() -> None:
    called = False

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    wrapper = ApiKeyASGI(inner, "secret")
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(
        wrapper(
            {"type": "http", "method": "POST", "headers": [], "path": "/mcp"},
            receive,
            send,
        )
    )

    assert called is False
    assert sent[0]["status"] == 401


def test_mounted_mcp_auth_accepts_bearer() -> None:
    called = False

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    wrapper = ApiKeyASGI(inner, "secret")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        return None

    asyncio.run(
        wrapper(
            {
                "type": "http",
                "method": "POST",
                "headers": [(b"authorization", b"Bearer secret")],
                "path": "/mcp",
            },
            receive,
            send,
        )
    )

    assert called is True
