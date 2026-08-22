"""Pinned Android client contract and plan-authorized execution gate.

DSG is an execution enabler for user-approved plans, not a blanket blocker.
It verifies the audited client and exact approved step, then emits a scoped
capability grant the trusted executor can consume. Only work outside the
approved plan/build is denied.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from revenue import api as billing

from .alignment import evaluate_alignment
from .canonical import canonical_hash, utc_now
from .models import ObservedAction, Scalar
from . import service


MOBILE_PACKAGE = "com.dsg.architect"
MOBILE_VERSION_NAME = "1.0.0"
MOBILE_VERSION_CODE = 13
MOBILE_APK_SHA256 = "2d4674909e6aff8282dd39f9d198df592e047cb7e0742fe7bab8f62caa6cbf23"
MOBILE_SIGNING_CERT_SHA256 = "8262d16fbd2c58d4b7492648894fec6102001f6ddbc71ef74f9a44dc8467cfa7"
MOBILE_SOURCE_STAMP_CERT_SHA256 = "3257d599a49d2c961a471ca9843f59d341a405884583fc087df4237b733bbd6d"
VERIFIED_EXECUTION_SKU = service.VERIFIED_EXECUTION_SKU

router = APIRouter(prefix="/api/v1/mobile", tags=["dsg-mobile-control"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MobileClientIdentity(Strict):
    package_name: str = Field(min_length=1, max_length=255)
    version_name: str = Field(min_length=1, max_length=64)
    version_code: int = Field(ge=1)
    apk_sha256: str
    signing_cert_sha256: str

    @field_validator("apk_sha256", "signing_cert_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        lowered = value.lower()
        if len(lowered) != 64 or any(ch not in "0123456789abcdef" for ch in lowered):
            raise ValueError("must be a 64-character SHA-256 hex digest")
        return lowered


class ProposedAction(Strict):
    action: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=255)
    step_id: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Scalar] = Field(default_factory=dict)


class MobilePreflightRequest(Strict):
    client: MobileClientIdentity
    plan_id: str = Field(min_length=1, max_length=64)
    agent_identity: str = Field(min_length=1, max_length=255)
    action: ProposedAction
    trace_id: str | None = Field(default=None, max_length=128)


def audited_mobile_identity() -> dict[str, Any]:
    return {
        "package_name": MOBILE_PACKAGE,
        "version_name": MOBILE_VERSION_NAME,
        "version_code": MOBILE_VERSION_CODE,
        "apk_sha256": MOBILE_APK_SHA256,
        "signing_cert_sha256": MOBILE_SIGNING_CERT_SHA256,
        "source_stamp_cert_sha256": MOBILE_SOURCE_STAMP_CERT_SHA256,
        "distribution_evidence": "Google Play source stamp present in audited APK",
    }


def _client_mismatches(client: MobileClientIdentity) -> list[str]:
    expected = audited_mobile_identity()
    checks = {
        "package_name": client.package_name,
        "version_name": client.version_name,
        "version_code": client.version_code,
        "apk_sha256": client.apk_sha256,
        "signing_cert_sha256": client.signing_cert_sha256,
    }
    return [name for name, observed in checks.items() if observed != expected[name]]


def _authorize_control_caller(api_key: Optional[str], authorization: Optional[str]) -> None:
    """Authenticate the trusted bridge without turning auth into a plan-policy veto.

    A server bridge may use the Cinema bearer secret automatically. A metered
    DSG API key is also accepted. End users should not have to paste credentials
    into the mobile UI merely to execute an already-approved plan.
    """
    bearer = (authorization or "").strip()
    if bearer.startswith("Bearer "):
        expected = (os.getenv("CINEMA_API_SECRET") or "").strip()
        supplied = bearer.removeprefix("Bearer ").strip()
        if len(expected) >= 32 and supplied and hmac.compare_digest(supplied, expected):
            return

    presented = (api_key or "").strip()
    if presented:
        billing.authorize_request(presented, VERIFIED_EXECUTION_SKU)
        return

    raise HTTPException(
        status_code=401,
        detail={
            "error": "MOBILE_BRIDGE_AUTH_REQUIRED",
            "message": "trusted server bridge authentication is required",
            "next_step": (
                "Configure the RevenuePilot/Cinema bridge with CINEMA_API_SECRET or a DSG API key; "
                "do not ask the end user to supply it for each approved action."
            ),
        },
    )


def _capability_grant(request: MobilePreflightRequest, plan_record: dict[str, Any], alignment: dict[str, Any]) -> dict[str, Any]:
    scope = {
        "plan_id": request.plan_id,
        "plan_hash": plan_record["plan_hash"],
        "agent_identity": request.agent_identity,
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "parameters": request.action.parameters,
        "client_apk_sha256": request.client.apk_sha256,
        "action_trace_hash": alignment["action_trace_hash"],
    }
    return {
        "status": "GRANTED",
        "scope": scope,
        "scope_hash": canonical_hash(scope),
        "permissions": [
            "execute_exact_approved_step",
            "use_required_executor_tools_for_step",
            "record_execution_evidence",
            "continue_to_verification",
        ],
        "denied": ["change_target", "change_action", "add_unapproved_parameters", "execute_other_plan_steps"],
        "credential_policy": (
            "executor resolves configured server-side credentials for this scoped step; "
            "credentials are never returned to the mobile client"
        ),
    }


def evaluate_preflight(request: MobilePreflightRequest) -> dict[str, Any]:
    mismatches = _client_mismatches(request.client)
    if mismatches:
        return {
            "allowed": False,
            "decision": "BLOCK",
            "code": "MOBILE_CLIENT_NOT_TRUSTED",
            "reason": "mobile build identity does not match the audited base.apk",
            "mismatched_fields": mismatches,
            "expected_client": audited_mobile_identity(),
            "next_step": "Use the audited signed build or register a newly audited APK identity before execution.",
            "evaluated_at": utc_now(),
        }

    plan_record = service._require_approved_plan(request.plan_id)
    document = service.plan_document(plan_record)
    if document.agent_identity != request.agent_identity:
        return {
            "allowed": False,
            "decision": "BLOCK",
            "code": "AGENT_IDENTITY_MISMATCH",
            "reason": (
                f"approved plan names agent '{document.agent_identity}' but mobile bridge supplied "
                f"'{request.agent_identity}'"
            ),
            "next_step": "Use the agent identity already approved by the plan, or approve a new plan.",
            "evaluated_at": utc_now(),
        }

    observed = ObservedAction(
        action=request.action.action,
        target=request.action.target,
        step_id=request.action.step_id,
        parameters=request.action.parameters,
        status="succeeded",
    )
    alignment = evaluate_alignment(document, [observed])

    # Missing future steps are irrelevant during one-step preflight. Everything
    # else is checked against this exact approved step before a capability is granted.
    action_findings = [item for item in alignment["findings"] if item.get("code") != "STEP_NOT_EXECUTED"]
    outside_plan = bool(action_findings)

    if outside_plan:
        decision = "BLOCK"
        allowed = False
        code = action_findings[0]["code"]
        grant = None
        next_step = "Match the exact approved step; otherwise create and approve a changed plan."
    else:
        decision = "ALLOW"
        allowed = True
        code = "PLAN_AUTHORIZED_ACTION"
        grant = _capability_grant(request, plan_record, alignment)
        next_step = (
            "Executor may run this exact step now using server-side capabilities, then record evidence and verify."
        )

    receipt_material = {
        "client_apk_sha256": request.client.apk_sha256,
        "plan_id": request.plan_id,
        "plan_hash": plan_record["plan_hash"],
        "agent_identity": request.agent_identity,
        "step_id": request.action.step_id,
        "action_trace_hash": alignment["action_trace_hash"],
        "decision": decision,
        "capability_scope_hash": grant["scope_hash"] if grant else None,
        "trace_id": request.trace_id,
    }

    return {
        "allowed": allowed,
        "decision": decision,
        "code": code,
        "plan_id": request.plan_id,
        "plan_hash": plan_record["plan_hash"],
        "plan_status": plan_record["status"],
        "step_id": request.action.step_id,
        "action": request.action.action,
        "target": request.action.target,
        "findings": action_findings,
        "capability_grant": grant,
        "control_hash": canonical_hash(receipt_material),
        "computed_by": "dsg",
        "next_step": next_step,
        "evaluated_at": utc_now(),
    }


@router.get("/client-contract")
async def client_contract() -> dict[str, Any]:
    return {
        "client": audited_mobile_identity(),
        "control": {
            "preflight": "POST /api/v1/mobile/control/preflight",
            "execution_record": "POST /api/v1/executions",
            "evidence": "POST /api/v1/executions/{execution_id}/evidence",
            "verification": "POST /api/v1/executions/{execution_id}/verify",
            "proof": "GET /api/v1/proofs/{proof_id}",
        },
        "rule": (
            "approved exact plan action receives a scoped capability grant and proceeds; "
            "only work outside the approved plan/build is blocked"
        ),
    }


@router.post("/control/preflight")
async def control_preflight(
    request: MobilePreflightRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    _authorize_control_caller(x_dsg_api_key, authorization)
    return evaluate_preflight(request)


def install(app) -> None:
    app.include_router(router)


__all__ = [
    "MOBILE_APK_SHA256",
    "MOBILE_PACKAGE",
    "MOBILE_SIGNING_CERT_SHA256",
    "MOBILE_SOURCE_STAMP_CERT_SHA256",
    "MOBILE_VERSION_CODE",
    "MOBILE_VERSION_NAME",
    "MobilePreflightRequest",
    "audited_mobile_identity",
    "evaluate_preflight",
    "install",
    "router",
]
