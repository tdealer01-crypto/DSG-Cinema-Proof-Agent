from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1 import service
from api_v1.models import (
    ApprovePlanRequest,
    EvidenceArtifact,
    EvidenceSubmission,
    ExecutionCreate,
    ObservedAction,
    PlanDocument,
)
from api_v1.store import RecordStore, get_store, reset_store
from revenue import api as billing


ROOT = Path(__file__).resolve().parents[1]
client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_live_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_LEDGER_STORE", raising=False)
    monkeypatch.delenv("DSG_REVENUE_ACCOUNT_STORE", raising=False)
    monkeypatch.delenv("DSG_V1_STORE_PATH", raising=False)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    reset_store(RecordStore(str(tmp_path / "live-records.json")))
    billing.reset_engine()
    yield
    reset_store(RecordStore(None))
    billing.reset_engine()


def approved_plan() -> dict:
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Live customer deployment",
                "agent_identity": "customer-agent",
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


def start_session() -> tuple[str, dict]:
    response = client.post(
        "/api/v1/live/sessions",
        json={"display_name": "Customer Agent Live", "ttl_seconds": 3600},
    )
    assert response.status_code == 200
    body = response.json()
    return body["live_session_token"], body


def action_payload(plan_id: str, *, target: str = "production/app", trace_id: str = "live-trace-1") -> dict:
    return {
        "plan_id": plan_id,
        "agent_identity": "customer-agent",
        "action": {
            "step_id": "deploy",
            "action": "deploy_product",
            "target": target,
            "parameters": {"environment": "production"},
        },
        "required_capabilities": [],
        "channel": "mcp",
        "trace_id": trace_id,
    }


def test_live_session_defaults_to_observe_and_persists_only_token_hash():
    token, body = start_session()

    assert body["session"]["mode"] == "OBSERVE"
    assert body["monitor_url"].startswith(
        "https://dsg-cinema-production.nicetree-a005fe99.westus3.azurecontainerapps.io/live.html#"
    )
    assert body["monitor_url"].endswith(token)

    records = get_store().list_records("live_sessions")
    assert len(records) == 1
    serialized = json.dumps(records[0], sort_keys=True)
    assert token not in serialized
    assert records[0]["token_hash"] == hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_observe_keeps_outside_plan_classification_but_does_not_stop_customer_runtime():
    plan = approved_plan()
    token, _ = start_session()

    response = client.post(
        "/api/v1/live/check",
        headers={"X-DSG-Live-Token": token},
        json=action_payload(plan["plan_id"], target="production/other"),
    )
    assert response.status_code == 200
    body = response.json()

    assert body["decision"] == "BLOCK"
    assert body["allowed"] is False
    assert body["live"]["mode"] == "OBSERVE"
    assert body["live"]["governance_status"] == "OUTSIDE_PLAN"
    assert body["live"]["execution_instruction"] == "CONTINUE"
    assert body["live"]["effect"] == "NOT_STOPPED_OBSERVE"
    assert body["live"]["enforcement_applied"] is False

    event = get_store().list_records("live_events")[0]
    assert event["governance_status"] == "OUTSIDE_PLAN"
    assert event["execution_instruction"] == "CONTINUE"
    assert "parameters" not in event
    assert len(event["parameters_hash"]) == 64


def test_enforce_switch_turns_same_outside_plan_result_into_stop_effect():
    plan = approved_plan()
    token, _ = start_session()

    mode = client.post(
        "/api/v1/live/mode",
        headers={"X-DSG-Live-Token": token},
        json={"mode": "enforce"},
    )
    assert mode.status_code == 200
    assert mode.json()["session"]["mode"] == "ENFORCE"

    response = client.post(
        "/api/v1/live/check",
        headers={"X-DSG-Live-Token": token},
        json=action_payload(plan["plan_id"], target="production/other", trace_id="live-enforce-1"),
    )
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["live"]["governance_status"] == "OUTSIDE_PLAN"
    assert body["live"]["execution_instruction"] == "STOP"
    assert body["live"]["effect"] == "BLOCKED_BY_DSG"
    assert body["live"]["enforcement_applied"] is True


def test_missing_capability_remains_waiting_permission_and_observe_does_not_relabel_it_block():
    plan = approved_plan()
    token, _ = start_session()
    payload = action_payload(plan["plan_id"], trace_id="live-capability-1")
    payload["required_capabilities"] = [{"capability": "stripe_api"}]

    response = client.post(
        "/api/v1/live/check",
        headers={"X-DSG-Live-Token": token},
        json=payload,
    )
    body = response.json()

    assert body["decision"] == "WAITING_PERMISSION"
    assert body["allowed"] is True
    assert body["execution_ready"] is False
    assert body["live"]["governance_status"] == "MISSING_PERMISSION"
    assert body["live"]["execution_instruction"] == "CONTINUE"


def test_live_token_isolation_rejects_unknown_session_capability():
    plan = approved_plan()
    token, _ = start_session()

    response = client.post(
        "/api/v1/live/check",
        headers={"X-DSG-Live-Token": token},
        json=action_payload(plan["plan_id"]),
    )
    assert response.status_code == 200

    invalid = client.get(
        "/api/v1/live/events",
        headers={"X-DSG-Live-Token": "x" * 43},
    )
    assert invalid.status_code == 401
    assert "invalid DSG Live session token" in invalid.text


def test_live_evidence_and_replay_are_recomputed_from_stored_execution_not_caller_claims():
    plan = approved_plan()
    token, _ = start_session()
    trace_id = "live-evidence-1"
    payload = action_payload(plan["plan_id"], trace_id=trace_id)

    checked = client.post(
        "/api/v1/live/check",
        headers={"X-DSG-Live-Token": token},
        json=payload,
    )
    assert checked.status_code == 200
    assert checked.json()["live"]["governance_status"] == "PASS"

    before = client.get(
        "/api/v1/live/events",
        headers={"X-DSG-Live-Token": token},
    ).json()["latest"]
    assert before["evidence"]["status"] == "UNVERIFIED"
    assert before["evidence"]["evidence"] == "PENDING"
    assert before["evidence"]["replay"] == "NOT_VERIFIED"
    assert before["evidence"]["proof"] == "PENDING"

    evidence_content = '{"deployment":"ok"}'
    digest = hashlib.sha256(evidence_content.encode("utf-8")).hexdigest()
    action = ObservedAction.model_validate(
        {
            **payload["action"],
            "status": "succeeded",
            "output_sha256": digest,
        }
    )
    execution = service.record_execution(
        ExecutionCreate(
            plan_id=plan["plan_id"],
            agent_identity="customer-agent",
            environment="production",
            channel="mcp",
            actions=[action],
            trace_id=trace_id,
        )
    )
    service.submit_evidence(
        execution["execution_id"],
        EvidenceSubmission(
            artifacts=[
                EvidenceArtifact(
                    artifact_id="deploy-output",
                    source="customer-runtime",
                    step_id="deploy",
                    content=evidence_content,
                )
            ]
        ),
    )

    after = client.get(
        "/api/v1/live/events",
        headers={"X-DSG-Live-Token": token},
    ).json()["latest"]
    assert after["evidence"]["execution_id"] == execution["execution_id"]
    assert after["evidence"]["status"] == "UNVERIFIED"  # no Z3 proof receipt yet
    assert after["evidence"]["evidence"] == "VERIFIED"
    assert after["evidence"]["evidence_completeness"] == 1.0
    assert after["evidence"]["replay"] == "REPLAY_VERIFIED"
    assert after["evidence"]["actions_checked"] == 1
    assert after["evidence"]["actions_matched"] == 1
    assert after["evidence"]["proof"] == "PENDING"


def test_mcp_exposes_live_start_check_status_but_not_agent_mode_switch():
    listed = client.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert listed.status_code == 200
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {"dsg_live_start", "dsg_live_check_action", "dsg_live_status"} <= names
    assert "dsg_live_set_mode" not in names


def test_live_openapi_contract_and_monitor_have_five_panels_with_no_execution_replay():
    schema = client.get("/openapi.json").json()
    assert "/api/v1/live/sessions" in schema["paths"]
    assert "/api/v1/live/check" in schema["paths"]
    assert "/api/v1/live/events" in schema["paths"]
    assert "/api/v1/live/mode" in schema["paths"]

    page = client.get("/live.html")
    assert page.status_code == 200
    text = page.text
    labels = ["1 · LIVE ACTION", "2 · PLAN CHECK", "3 · DSG EFFECT", "4 · WHY", "5 · EVIDENCE"]
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "Replay is verification-only and never re-executes the action" in text
    assert "Re-run production" not in text
    assert "Execution Replay" not in text
    assert (ROOT / "api_v1" / "live.html").is_file()


def test_live_contract_states_replay_verification_only():
    response = client.get("/api/v1/live/contract")
    assert response.status_code == 200
    body = response.json()
    assert body["default_mode"] == "OBSERVE"
    assert body["panels"] == ["LIVE ACTION", "PLAN CHECK", "DSG EFFECT", "WHY", "EVIDENCE"]
    assert "never re-executes" in body["replay"]
