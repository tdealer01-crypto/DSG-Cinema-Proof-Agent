"""Cross-channel tests: REST, MCP and DSG Live must use one decision core."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import service
from api_v1.live_monitor import LiveStartRequest, create_live_session
from api_v1.models import ApprovePlanRequest, PlanDocument
from api_v1.store import RecordStore, get_store, reset_store

client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    reset_store(RecordStore(str(tmp_path / "decision-channels.json")))
    yield
    reset_store(RecordStore(None))


def approved_plan():
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Cross-channel approved deploy",
                "agent_identity": "dsg-executor",
                "channel": "mcp",
                "steps": [
                    {
                        "step_id": "deploy",
                        "action": "deploy_product",
                        "target": "production/app",
                        "parameters": {"environment": "production"},
                    }
                ],
            }
        )
    )
    return service.approve_plan(
        created["plan_id"],
        ApprovePlanRequest(approver="owner", plan_hash=created["plan_hash"]),
    )


def payload(plan_id: str):
    return {
        "plan_id": plan_id,
        "agent_identity": "dsg-executor",
        "action": {
            "step_id": "deploy",
            "action": "deploy_product",
            "target": "production/app",
            "parameters": {"environment": "production"},
        },
        "required_capabilities": [{"capability": "stripe_api"}],
        "channel": "test",
        "trace_id": "cross-channel-1",
    }


def live_token() -> str:
    session = create_live_session(LiveStartRequest(display_name="Cross-channel Live", ttl_seconds=3600))
    return session["live_session_token"]


def test_rest_contract_exposes_single_core_semantics():
    response = client.get("/api/v1/control/contract")
    assert response.status_code == 200
    body = response.json()
    assert body["core"] == "dsg-decision-core"
    assert "WAITING_PERMISSION" in body["decisions"]
    assert "Missing tools or credentials are provisioning" in body["invariant"]
    assert body["capabilities"]["caller_can_assert_availability"] is False


def test_rest_approved_action_with_missing_server_capability_is_not_blocked():
    plan = approved_plan()
    response = client.post("/api/v1/control/preflight", json=payload(plan["plan_id"]))
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "WAITING_PERMISSION"
    assert body["allowed"] is True
    assert body["execution_ready"] is False
    assert body["computed_by"] == "dsg-decision-core"
    assert body["capability_resolution"]["caller_can_assert_availability"] is False


def test_rest_becomes_allow_when_server_capability_exists(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_server_only_value")
    plan = approved_plan()
    response = client.post("/api/v1/control/preflight", json=payload(plan["plan_id"]))
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "ALLOW"
    assert body["allowed"] is True
    assert body["execution_ready"] is True
    assert body["capability_grant"]["status"] == "GRANTED"
    assert "sk_test_server_only_value" not in response.text


def test_mcp_uses_same_waiting_permission_decision():
    plan = approved_plan()
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "dsg_preflight_action",
            "arguments": payload(plan["plan_id"]),
        },
    }
    response = client.post("/api/v1/mcp", json=message)
    assert response.status_code == 200
    tool_result = response.json()["result"]
    body = tool_result["structuredContent"]
    assert body["decision"] == "WAITING_PERMISSION"
    assert body["allowed"] is True
    assert body["execution_ready"] is False
    assert body["computed_by"] == "dsg-decision-core"


def test_live_observe_uses_same_block_decision_without_stopping_customer_runtime():
    plan = approved_plan()
    token = live_token()
    request = payload(plan["plan_id"])
    request["required_capabilities"] = []
    request["action"]["target"] = "production/not-approved"

    response = client.post(
        "/live/api/check",
        headers={"X-DSG-Live-Token": token},
        json=request,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["allowed"] is False
    assert body["computed_by"] == "dsg-decision-core"
    assert body["live"]["mode"] == "OBSERVE"
    assert body["live"]["governance_status"] == "OUTSIDE_PLAN"
    assert body["live"]["execution_instruction"] == "CONTINUE"
    assert body["live"]["enforcement_applied"] is False

    event = get_store().list_records("live_events")[0]
    assert event["decision"] == "BLOCK"
    assert "parameters" not in event
    assert len(event["parameters_hash"]) == 64


def test_live_enforce_keeps_same_block_decision_and_changes_only_effect():
    plan = approved_plan()
    token = live_token()
    changed = client.post(
        "/live/api/mode",
        headers={"X-DSG-Live-Token": token},
        json={"mode": "enforce"},
    )
    assert changed.status_code == 200
    assert changed.json()["session"]["mode"] == "ENFORCE"

    request = payload(plan["plan_id"])
    request["required_capabilities"] = []
    request["action"]["target"] = "production/not-approved"
    response = client.post(
        "/live/api/check",
        headers={"X-DSG-Live-Token": token},
        json=request,
    )
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["computed_by"] == "dsg-decision-core"
    assert body["live"]["governance_status"] == "OUTSIDE_PLAN"
    assert body["live"]["execution_instruction"] == "STOP"
    assert body["live"]["effect"] == "BLOCKED_BY_DSG"
    assert body["live"]["enforcement_applied"] is True


def test_live_session_token_is_hashed_and_not_persisted_plaintext():
    token = live_token()
    record = get_store().list_records("live_sessions")[0]
    assert token not in json.dumps(record, sort_keys=True)
    assert record["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_mcp_lists_unified_preflight_and_live_tools():
    response = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert "dsg_preflight_action" in names
    assert "dsg_live_start" in names
    assert "dsg_live_check_action" in names
    assert "dsg_live_status" in names
    assert "dsg_live_set_mode" not in names
