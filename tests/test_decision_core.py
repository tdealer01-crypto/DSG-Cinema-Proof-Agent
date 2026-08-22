"""Contract tests for the unified DSG decision core."""

from __future__ import annotations

from api_v1.decision_core import CapabilityNeed, CorePreflightRequest, evaluate_plan_authorization
from api_v1.models import ObservedAction, PlanDocument
from api_v1.alignment import plan_hash


PLAN = PlanDocument.model_validate(
    {
        "title": "Deploy approved production release",
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


def request(*, action=None, capability_needs=None, agent="dsg-executor"):
    return CorePreflightRequest(
        plan_id="plan_test",
        plan_hash=plan_hash(PLAN),
        plan_status="APPROVED",
        approved_agent_identity="dsg-executor",
        agent_identity=agent,
        action=action
        or ObservedAction(
            step_id="deploy",
            action="deploy_product",
            target="production/app",
            parameters={"environment": "production"},
        ),
        capability_needs=capability_needs or [],
        channel="test",
        trace_id="trace-1",
    )


def test_approved_exact_action_is_allowed_and_granted():
    result = evaluate_plan_authorization(request=request(), plan_document=PLAN)
    assert result["decision"] == "ALLOW"
    assert result["allowed"] is True
    assert result["execution_ready"] is True
    assert result["capability_grant"]["status"] == "GRANTED"
    assert result["computed_by"] == "dsg-decision-core"


def test_missing_server_capability_waits_without_policy_block():
    result = evaluate_plan_authorization(
        request=request(
            capability_needs=[
                CapabilityNeed(
                    capability="azure_deploy_credential",
                    available=False,
                    source="server-secret-store",
                    remediation="resolve configured workload identity",
                )
            ]
        ),
        plan_document=PLAN,
    )
    assert result["decision"] == "WAITING_PERMISSION"
    assert result["allowed"] is True
    assert result["execution_ready"] is False
    assert result["capability_grant"]["status"] == "GRANTED"
    assert result["pending_capabilities"][0]["capability"] == "azure_deploy_credential"


def test_wrong_target_is_blocked_as_outside_plan():
    result = evaluate_plan_authorization(
        request=request(
            action=ObservedAction(
                step_id="deploy",
                action="deploy_product",
                target="unapproved/app",
                parameters={"environment": "production"},
            )
        ),
        plan_document=PLAN,
    )
    assert result["decision"] == "BLOCK"
    assert result["allowed"] is False
    assert result["capability_grant"] is None
    assert result["code"] == "OUT_OF_PLAN_ACTION"


def test_undeclared_parameter_is_blocked_as_changed_plan_scope():
    result = evaluate_plan_authorization(
        request=request(
            action=ObservedAction(
                step_id="deploy",
                action="deploy_product",
                target="production/app",
                parameters={"environment": "production", "force": True},
            )
        ),
        plan_document=PLAN,
    )
    assert result["decision"] == "BLOCK"
    assert result["code"] == "UNDECLARED_PARAMETER"


def test_wrong_agent_is_blocked():
    result = evaluate_plan_authorization(request=request(agent="other-agent"), plan_document=PLAN)
    assert result["decision"] == "BLOCK"
    assert result["code"] == "AGENT_IDENTITY_MISMATCH"
