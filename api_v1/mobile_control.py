"""Pinned Android client contract and fail-closed preflight control gate.

This module does not trust a mobile caller to assert that an action is safe.
It pins the audited APK identity and recomputes whether one proposed action is
inside an already-approved DSG plan before the downstream executor proceeds.

The binary itself belongs in a release/workflow artifact, not the source tree.
This source records the exact SHA-256 and signing certificate observed in the
audited base.apk so a backend can reject a different build deterministically.
"""

from __future__ import annotations

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


def _require_metered_caller(api_key: Optional[str]) -> None:
    presented = (api_key or "").strip()
    if not presented:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "MOBILE_CONTROL_AUTH_REQUIRED",
                "message": "X-DSG-API-Key is required for mobile control preflight",
                "next_step": "Call this endpoint from the trusted RevenuePilot/server bridge with a valid DSG API key.",
            },
        )
    billing.authorize_request(presented, VERIFIED_EXECUTION_SKU)


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
            "next_step": "Run under the approved agent identity or approve a new plan for this agent.",
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

    # Missing later plan steps are expected during a one-step preflight. Only
    # findings attached to the proposed action can deny this action now.
    action_findings = [
        item for item in alignment["findings"] if item.get("code") != "STEP_NOT_EXECUTED"
    ]
    blocking = [item for item in action_findings if item.get("severity") == "block"]
    review = [item for item in action_findings if item.get("severity") == "review"]

    if blocking:
        decision = "BLOCK"
        allowed = False
        code = blocking[0]["code"]
        next_step = "Change the proposed action to exactly match an approved plan step."
    elif review:
        decision = "REVIEW"
        allowed = False
        code = review[0]["code"]
        next_step = "Remove undeclared parameters or approve a new plan that explicitly includes them."
    else:
        decision = "ALLOW"
        allowed = True
        code = "PLAN_AUTHORIZED_ACTION"
        next_step = "Execute this exact action, then submit the observed execution and evidence to DSG."

    receipt_material = {
        "client_apk_sha256": request.client.apk_sha256,
        "plan_id": request.plan_id,
        "plan_hash": plan_record["plan_hash"],
        "agent_identity": request.agent_identity,
        "step_id": request.action.step_id,
        "action_trace_hash": alignment["action_trace_hash"],
        "decision": decision,
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
        "rule": "approved plan actions may proceed; unapproved build/action/parameters fail closed",
    }


@router.post("/control/preflight")
async def control_preflight(
    request: MobilePreflightRequest,
    x_dsg_api_key: Optional[str] = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    _require_metered_caller(x_dsg_api_key)
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
