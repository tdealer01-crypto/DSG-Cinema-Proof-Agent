from __future__ import annotations

import json

import pytest

from api_v1 import mcp


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def test_activecampaign_list_users_is_exposed():
    assert "activecampaign_list_users" in mcp.tool_names()
    tool = next(tool for tool in mcp.TOOLS if tool.name == "activecampaign_list_users")
    definition = tool.definition()
    assert definition["inputSchema"]["properties"]["limit"]["maximum"] == 100
    assert "token" not in json.dumps(definition).lower()


@pytest.mark.asyncio
async def test_activecampaign_list_users_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("ACTIVECAMPAIGN_API_URL", raising=False)
    monkeypatch.delenv("ACTIVECAMPAIGN_API_TOKEN", raising=False)

    response = await mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "activecampaign_list_users",
                "arguments": {"limit": 20, "offset": 0},
            },
        }
    )
    payload = _body(response)["result"]["structuredContent"]
    assert payload["state"] == "PENDING_CONFIGURATION"
    assert payload["users"] == []
    assert "ACTIVECAMPAIGN_API_TOKEN" in payload["detail"]
