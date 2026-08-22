"""Preflight authorizes execution; recording preserves observed reality for audit."""

from __future__ import annotations

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
    reset_store(RecordStore(str(tmp_path / "execution-boundary.json")))
    yield
    reset_store(RecordStore(None))


def approved_plan():
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Authorized production deployment",
                "agent_identity": "dsg-executor",
                "channel": "api",
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


def execution_payload(plan_id: str, *, target: str = "production/app"):
    return {
        "plan_id": plan_id,
        "agent_identity": "dsg-executor",
        "environment": "production",
        "channel": "api",
        "trace_id": "trace-boundary-1",
        "actions": [
            {
                "step_id": "deploy",
                "action": "deploy_product",
                "target": target,
                "parameters": {"environment": "production"},
                "status": "succeeded",
            }
        ],
    }


def execution_count() -> int:
    return int(service.store_summary()["records"].get("executions", 0))


def test_rest_records_exact_approved_trace_as_aligned_audit_evidence():
    plan = approved_plan()
    response = client.post("/api/v1/executions", json=execution_payload(plan["plan_id"]))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["alignment_preview"]["plan_aligned"] is True
    stored = service.read_execution(body["execution_id"])
    assert stored["plan_id"] == plan["plan_id"]
    assert execution_count() == 1


def test_rest_preserves_out_of_plan_trace_for_audit_without_calling_it_aligned():
    plan = approved_plan()
    response = client.post(
        "/api/v1/executions",
        json=execution_payload(plan["plan_id"], target="unapproved/app"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["alignment_preview"]["plan_aligned"] is False
    assert any(
        item["code"] == "OUT_OF_PLAN_ACTION"
        for item in body["alignment_preview"]["findings"]
    )
    assert execution_count() == 1


def test_mcp_preserves_same_violation_trace_for_audit():
    plan = approved_plan()
    message = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "dsg_record_execution",
            "arguments": execution_payload(plan["plan_id"], target="unapproved/app"),
        },
    }
    response = client.post("/api/v1/mcp", json=message)
    assert response.status_code == 200
    tool = response.json()["result"]
    assert tool["isError"] is False
    body = tool["structuredContent"]
    assert body["alignment_preview"]["plan_aligned"] is False
    assert execution_count() == 1


def test_draft_plan_preflight_returns_canonical_block_not_transport_409():
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Not approved yet",
                "agent_identity": "dsg-executor",
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
    response = client.post(
        "/api/v1/control/preflight",
        json={
            "plan_id": created["plan_id"],
            "agent_identity": "dsg-executor",
            "action": {
                "step_id": "deploy",
                "action": "deploy_product",
                "target": "production/app",
                "parameters": {"environment": "production"},
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["code"] == "PLAN_NOT_APPROVED"
    assert body["computed_by"] == "dsg-decision-core"
