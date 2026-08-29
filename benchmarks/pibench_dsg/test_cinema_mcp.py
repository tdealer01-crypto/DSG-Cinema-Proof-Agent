from __future__ import annotations

import pytest

import cinema_mcp


@pytest.mark.asyncio
async def test_cinema_tools_uses_tools_list(monkeypatch):
    seen = {}

    async def fake(method, params=None):
        seen["method"] = method
        seen["params"] = params
        return {"tools": []}

    monkeypatch.setattr(cinema_mcp, "call_cinema_mcp", fake)
    result = await cinema_mcp.cinema_tools()
    assert result == {"tools": []}
    assert seen == {"method": "tools/list", "params": None}


@pytest.mark.asyncio
async def test_cinema_status_calls_dsg_status(monkeypatch):
    seen = {}

    async def fake(method, params=None):
        seen["method"] = method
        seen["params"] = params
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(cinema_mcp, "call_cinema_mcp", fake)
    result = await cinema_mcp.cinema_status()
    assert result["content"][0]["text"] == "ok"
    assert seen["method"] == "tools/call"
    assert seen["params"] == {"name": "dsg_status", "arguments": {}}
