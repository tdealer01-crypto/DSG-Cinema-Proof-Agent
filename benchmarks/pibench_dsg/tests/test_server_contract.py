import asyncio
import json
import pathlib
import sys
from types import SimpleNamespace

import httpx
from a2a.client import A2ACardResolver

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from cinema_decision import CinemaBatchDecision  # noqa: E402


def body_json(response):
    return json.loads(response.body.decode("utf-8"))


async def resolve_agent_card():
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resolver = A2ACardResolver(httpx_client=client, base_url="http://testserver")
        return await resolver.get_agent_card()


async def fetch_raw_agent_card(path="/.well-known/agent-card.json"):
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


def test_agent_card_resolves_with_agentbeats_a2a_sdk_0_3_22():
    card = asyncio.run(resolve_agent_card())

    assert card.name == "DSG Proof-Governed Agent"
    assert card.url == "http://testserver"
    assert card.protocol_version == "0.3.0"
    assert card.preferred_transport == "JSONRPC"
    assert card.default_input_modes == ["application/json"]
    assert card.default_output_modes == ["application/json"]
    assert len(card.skills) == 1
    assert card.skills[0].id == "pi-bench-policy-execution"
    assert card.capabilities.extensions is not None
    assert card.capabilities.extensions[0].uri == server.POLICY_BOOTSTRAP_EXTENSION


def test_agent_card_keeps_pibench_bootstrap_extension_and_runtime_url():
    card = asyncio.run(fetch_raw_agent_card())

    assert server.POLICY_BOOTSTRAP_EXTENSION in card["extensions"]
    assert card["capabilities"]["extensions"][0]["uri"] == server.POLICY_BOOTSTRAP_EXTENSION
    assert card["url"] == "http://testserver"
    assert card["defaultInputModes"] == ["application/json"]
    assert card["defaultOutputModes"] == ["application/json"]
    assert card["skills"][0]["id"] == "pi-bench-policy-execution"


def test_legacy_agent_card_alias_matches_current_card():
    current = asyncio.run(fetch_raw_agent_card("/.well-known/agent-card.json"))
    legacy = asyncio.run(fetch_raw_agent_card("/.well-known/agent.json"))
    assert legacy == current


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


def _decision_tool():
    return {
        "type": "function",
        "function": {
            "name": "record_decision",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {
                        "type": "string",
                        "enum": ["ALLOW", "ALLOW-CONDITIONAL", "DENY", "ESCALATE"],
                    }
                },
                "required": ["decision"],
                "additionalProperties": False,
            },
        },
    }


def _model_tool_response():
    function = SimpleNamespace(name="record_decision", arguments='{"decision":"DENY"}')
    call = SimpleNamespace(id="call-1", function=function)
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_cinema_preflight_runs_before_local_gate(monkeypatch):
    events = []
    real_gate = server.gate_tool_calls

    monkeypatch.setattr(server.litellm, "completion", lambda **_kwargs: _model_tool_response())

    async def fake_cinema(**_kwargs):
        events.append("cinema")
        return CinemaBatchDecision(decision="ALLOW", payloads=[])

    def observed_gate(*args, **kwargs):
        events.append("gate")
        return real_gate(*args, **kwargs)

    monkeypatch.setattr(server, "evaluate_with_cinema", fake_cinema)
    monkeypatch.setattr(server, "gate_tool_calls", observed_gate)

    response = asyncio.run(
        server._handle_turn(
            "turn-cinema-order",
            {
                "benchmark_context": [{"kind": "policy", "content": "test"}],
                "tools": [_decision_tool()],
                "messages": [{"role": "user", "content": "decide"}],
            },
        )
    )
    payload = body_json(response)
    data = payload["result"]["status"]["message"]["parts"][0]["data"]
    assert events == ["cinema", "gate"]
    assert data["tool_calls"][0]["function"]["name"] == "record_decision"


def test_non_allow_cinema_decision_emits_zero_tools_and_skips_local_gate(monkeypatch):
    monkeypatch.setattr(server.litellm, "completion", lambda **_kwargs: _model_tool_response())

    async def fake_cinema(**_kwargs):
        return CinemaBatchDecision(decision="WAITING_PERMISSION", payloads=[])

    def forbidden_gate(*_args, **_kwargs):
        raise AssertionError("local gate must not run after non-ALLOW Cinema preflight")

    monkeypatch.setattr(server, "evaluate_with_cinema", fake_cinema)
    monkeypatch.setattr(server, "gate_tool_calls", forbidden_gate)

    response = asyncio.run(
        server._handle_turn(
            "turn-cinema-stop",
            {
                "benchmark_context": [{"kind": "policy", "content": "test"}],
                "tools": [_decision_tool()],
                "messages": [{"role": "user", "content": "decide"}],
            },
        )
    )
    payload = body_json(response)
    data = payload["result"]["status"]["message"]["parts"][0]["data"]
    assert "tool_calls" not in data
    assert "not execution-ready" in data["content"]
