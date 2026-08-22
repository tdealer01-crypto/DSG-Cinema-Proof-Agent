"""Cross-channel tests: REST and MCP must use the same DSG decision core."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import service
from api_v1.models import ApprovePlanRequest, PlanDocument
from api_v1.store import RecordStore, reset_store

client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
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


def payload(plan_id: str, *, available: bool):
    return {
        "plan_id": plan_id,
        "agent_identity": "dsg-executor",
        "action": {
            "step_id": "deploy",
            "action": "deploy_product",
            "target": "production/app",
            "parameters": {"environment": "production"},
        },
        "capability_needs": [
            {
                "capability": "production_deploy_credential",
                "available": available,
                "source": "server-secret-store",
            }
        ],
        "channel": "test",
        "trace_id": "cross-channel-1",
    }


def test_rest_contract_exposes_single_core_semantics():
    response = client.get("/api/v1/control/contract")
    assert response.status_code == 200
    body = response.json()
    assert body["core"] == "dsg-decision-core"
    assert "WAITING_PERMISSION" in body["decisions"]
    assert "Missing tools or credentials are provisioning" in body["invariant"]


def test_rest_approved_action_with_missing_capability_is_not_blocked():
    plan = approved_plan()
    response = client.post("/api/v1/control/preflight", json=payload(plan["plan_id"], available=False))
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "WAITING_PERMISSION"
    assert body["allowed"] is True
    assert body["execution_ready"] is False
    assert body["computed_by"] == "dsg-decision-core"


def test_mcp_uses_same_waiting_permission_decision():
    plan = approved_plan()
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "dsg_preflight_action",
            "arguments": payload(plan["plan_id"], available=False),
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


def test_mcp_lists_unified_preflight_tool():
    response = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert "dsg_preflight_action" in names
