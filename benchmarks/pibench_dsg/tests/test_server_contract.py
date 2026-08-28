import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


def test_agent_card_advertises_pibench_bootstrap_without_fake_public_url():
    original = server._card_url
    try:
        server._card_url = ""
        card = body_json(asyncio.run(server.agent_card()))
    finally:
        server._card_url = original

    assert server.POLICY_BOOTSTRAP_EXTENSION in card["extensions"]
    assert card["capabilities"]["message"] is True
    assert card["url"] == ""


def test_system_prompt_preserves_benchmark_context_metadata():
    prompt = server._build_system_prompt(
        [
            {
                "kind": "policy",
                "content": "Require dual approval.",
                "metadata": {"domain": "finance", "priority": "critical"},
            }
        ],
        [],
    )
    assert "Require dual approval." in prompt
    assert "domain=finance" in prompt
    assert "priority=critical" in prompt


def test_bootstrap_returns_context_id_and_caches_exact_context_hashes():
    server._sessions.clear()
    context = [{"kind": "policy", "content": "Test policy"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "record_decision",
                "parameters": {"type": "object"},
            },
        }
    ]
    response = server._handle_bootstrap(
        "contract-bootstrap",
        {
            "bootstrap": True,
            "run_id": "contract",
            "benchmark_context": context,
            "tools": tools,
        },
    )
    payload = body_json(response)
    data = payload["result"]["status"]["message"]["parts"][0]["data"]
    assert data["bootstrapped"] is True
    context_id = data["context_id"]
    cached = server._sessions[context_id]
    assert cached["context_hash"] == server.sha256_json(context)
    assert cached["toolset_hash"] == server.sha256_json(tools)


def test_jsonrpc_success_shape_matches_pibench_status_message_contract():
    payload = body_json(
        server._jsonrpc_success(
            "contract-result",
            {
                "kind": "data",
                "data": {
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "record_decision",
                                "arguments": '{"decision":"DENY"}',
                            },
                        }
                    ]
                },
            },
        )
    )
    parts = payload["result"]["status"]["message"]["parts"]
    assert parts[0]["kind"] == "data"
    assert parts[0]["data"]["tool_calls"][0]["function"]["name"] == "record_decision"
