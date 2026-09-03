from __future__ import annotations

import asyncio

from api_v1 import dashboard_chat


def test_mcp_receive_includes_agent_replies(monkeypatch):
    monkeypatch.setattr(
        dashboard_chat,
        "_mcp_account",
        lambda: ("dsg_live_test", "acct-chat", "chat-agent"),
    )
    monkeypatch.setattr(
        dashboard_chat,
        "_read",
        lambda _account_id: {
            "seq": 3,
            "messages": [
                {"seq": 1, "role": "user", "text": "hello"},
                {"seq": 2, "role": "agent", "text": "reply"},
                {"seq": 3, "role": "system", "text": "status"},
            ],
        },
    )

    result = asyncio.run(dashboard_chat._mcp_receive(dashboard_chat.ChatReceiveArgs(after_seq=0, limit=30)))

    assert [item["role"] for item in result["messages"]] == ["user", "agent", "system"]
    assert result["last_seq"] == 3


def test_mcp_receive_respects_after_seq_for_agent_replies(monkeypatch):
    monkeypatch.setattr(
        dashboard_chat,
        "_mcp_account",
        lambda: ("dsg_live_test", "acct-chat", "chat-agent"),
    )
    monkeypatch.setattr(
        dashboard_chat,
        "_read",
        lambda _account_id: {
            "seq": 2,
            "messages": [
                {"seq": 1, "role": "user", "text": "hello"},
                {"seq": 2, "role": "agent", "text": "reply"},
            ],
        },
    )

    result = asyncio.run(dashboard_chat._mcp_receive(dashboard_chat.ChatReceiveArgs(after_seq=1, limit=30)))

    assert result["messages"] == [{"seq": 2, "role": "agent", "text": "reply"}]
    assert result["last_seq"] == 2
