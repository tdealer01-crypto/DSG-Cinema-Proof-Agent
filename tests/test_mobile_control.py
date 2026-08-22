"""Tests for the audited Android client contract and plan-authorized preflight gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import cinema_main
from api_v1.mobile_control import (
    MOBILE_APK_SHA256,
    MOBILE_PACKAGE,
    MOBILE_SIGNING_CERT_SHA256,
    MOBILE_VERSION_CODE,
    MOBILE_VERSION_NAME,
    MobilePreflightRequest,
    evaluate_preflight,
)
from api_v1.models import ApprovePlanRequest, PlanDocument
from api_v1 import service
from api_v1.store import RecordStore, reset_store

client = TestClient(cinema_main.app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DSG_REVENUE_ENFORCE", raising=False)
    reset_store(RecordStore(str(tmp_path / "mobile-control-store.json")))
    yield
    reset_store(RecordStore(None))


def identity(**overrides):
    value = {
        "package_name": MOBILE_PACKAGE,
        "version_name": MOBILE_VERSION_NAME,
        "version_code": MOBILE_VERSION_CODE,
        "apk_sha256": MOBILE_APK_SHA256,
        "signing_cert_sha256": MOBILE_SIGNING_CERT_SHA256,
    }
    value.update(overrides)
    return value


def approved_plan():
    created = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Mobile deploy through approved DSG plan",
                "agent_identity": "dsg-mobile-bridge",
                "channel": "api",
                "steps": [
                    {
                        "step_id": "deploy",
                        "action": "deploy_product",
                        "target": "revenuepilot/production",
                        "parameters": {"environment": "production"},
                    },
                    {
                        "step_id": "verify",
                        "action": "verify_proof",
                        "target": "dsg-cinema",
                        "optional": True,
                    },
                ],
            }
        )
    )
    return service.approve_plan(
        created["plan_id"],
        ApprovePlanRequest(
            approver="mobile-owner",
            plan_hash=created["plan_hash"],
            approval_note="approved test plan",
        ),
    )


def request_for(plan_id: str, **action_overrides):
    action = {
        "step_id": "deploy",
        "action": "deploy_product",
        "target": "revenuepilot/production",
        "parameters": {"environment": "production"},
    }
    action.update(action_overrides)
    return MobilePreflightRequest.model_validate(
        {
            "client": identity(),
            "plan_id": plan_id,
            "agent_identity": "dsg-mobile-bridge",
            "action": action,
            "trace_id": "mobile-test-1",
        }
    )


def test_client_contract_exposes_exact_audited_apk_fingerprint():
    response = client.get("/api/v1/mobile/client-contract")
    assert response.status_code == 200
    body = response.json()
    assert body["client"]["package_name"] == "com.dsg.architect"
    assert body["client"]["version_code"] == 13
    assert body["client"]["apk_sha256"] == MOBILE_APK_SHA256
    assert body["client"]["signing_cert_sha256"] == MOBILE_SIGNING_CERT_SHA256


def test_preflight_allows_exact_action_and_grants_capability():
    plan = approved_plan()
    result = evaluate_preflight(request_for(plan["plan_id"]))
    assert result["allowed"] is True
    assert result["decision"] == "ALLOW"
    assert result["code"] == "PLAN_AUTHORIZED_ACTION"
    assert result["capability_grant"]["status"] == "GRANTED"
    assert "execute_exact_approved_step" in result["capability_grant"]["permissions"]
    assert result["capability_grant"]["scope"]["step_id"] == "deploy"
    assert len(result["capability_grant"]["scope_hash"]) == 64
    assert len(result["control_hash"]) == 64


def test_preflight_blocks_out_of_plan_target():
    plan = approved_plan()
    result = evaluate_preflight(
        request_for(plan["plan_id"], target="unapproved/production")
    )
    assert result["allowed"] is False
    assert result["decision"] == "BLOCK"
    assert result["code"] == "OUT_OF_PLAN_ACTION"
    assert result["capability_grant"] is None


def test_preflight_blocks_undeclared_parameters_as_outside_plan():
    plan = approved_plan()
    result = evaluate_preflight(
        request_for(
            plan["plan_id"],
            parameters={"environment": "production", "force": True},
        )
    )
    assert result["allowed"] is False
    assert result["decision"] == "BLOCK"
    assert result["code"] == "UNDECLARED_PARAMETER"
    assert result["capability_grant"] is None


def test_preflight_blocks_a_different_apk_build():
    plan = approved_plan()
    original = request_for(plan["plan_id"])
    request = original.model_copy(
        update={"client": original.client.model_copy(update={"apk_sha256": "0" * 64})}
    )
    result = evaluate_preflight(request)
    assert result["allowed"] is False
    assert result["decision"] == "BLOCK"
    assert result["code"] == "MOBILE_CLIENT_NOT_TRUSTED"
    assert "apk_sha256" in result["mismatched_fields"]


def test_http_preflight_requires_trusted_bridge_auth_not_user_reapproval():
    plan = approved_plan()
    response = client.post(
        "/api/v1/mobile/control/preflight",
        json=request_for(plan["plan_id"]).model_dump(mode="json"),
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "MOBILE_BRIDGE_AUTH_REQUIRED"
