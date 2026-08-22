"""Pinned Android adapter for the unified DSG decision core.

This module owns only mobile-specific client identity and trusted bridge auth.
Plan approval semantics, ALLOW/WAITING_PERMISSION/BLOCK, and capability grants
come from `decision_core`. Capability availability is resolved by the trusted
server-side broker; the mobile client cannot self-assert that a credential or
tool is available.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import Field, field_validator

from revenue import api as billing

from .capability_broker import CapabilityRequirement, resolve_capabilities
from .canonical import utc_now
from .decision_core import CorePreflightRequest, evaluate_plan_authorization
from .models import ObservedAction, Scalar, Strict
from . import service

MOBILE_PACKAGE = "com.dsg.architect"
MOBILE_VERSION_NAME = "1.0.0"
MOBILE_VERSION_CODE = 13
MOBILE_APK_SHA256 = "2d4674909e6aff8282dd39f9d198df592e047cb7e0742fe7bab8f62caa6cbf23"
MOBILE_SIGNING_CERT_SHA256 = "8262d16fbd2c58d4b7492648894fec6102001f6ddbc71ef74f9a44dc8467cfa7"
MOBILE_SOURCE_STAMP_CERT_SHA256 = "3257d599a49d2c961a471ca9843f59d341a405884583fc087df4237b733bbd6d"
VERIFIED_EXECUTION_SKU = service.VERIFIED_EXECUTION_SKU

router = APIRouter(prefix="/api/v1/mobile", tags=["dsg-mobile-control"])


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
    required_capabilities: list[CapabilityRequirement] = Field(default_factory=list, max_length=32)
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
    """Authenticate the trusted bridge without creating another policy gate."""
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
                "do not ask the end user to re-authorize each approved plan step."
            ),
        },
    )


def evaluate_preflight(request: MobilePreflightRequest) -> dict[str, Any]:
    mismatches = _client_mismatches(request.client)
    if mismatches:
        return {
            "allowed": False,
            "execution_ready": False,
            "decision": "BLOCK",
            "code": "MOBILE_CLIENT_NOT_TRUSTED",
            "reason": "mobile build identity does not match the audited base.apk",
            "mismatched_fields": mismatches,
            "expected_client": audited_mobile_identity(),
            "capability_grant": None,
            "computed_by": "dsg-decision-core-adapter",
            "next_step": "Use the audited signed build or register a newly audited APK identity.",
            "evaluated_at": utc_now(),
        }

    plan_record = service._require_approved_plan(request.plan_id)
    document = service.plan_document(plan_record)
    observed = ObservedAction(
        action=request.action.action,
        target=request.action.target,
        step_id=request.action.step_id,
        parameters=request.action.parameters,
        status="succeeded",
    )
    resolved = resolve_capabilities(request.required_capabilities)
    core_request = CorePreflightRequest(
        plan_id=plan_record["plan_id"],
        plan_hash=plan_record["plan_hash"],
        plan_status=plan_record["status"],
        approved_agent_identity=document.agent_identity,
        agent_identity=request.agent_identity,
        action=observed,
        capability_needs=resolved,
        channel="mobile",
        trace_id=request.trace_id,
        client_context={
            "package_name": request.client.package_name,
            "version_code": request.client.version_code,
            "apk_sha256": request.client.apk_sha256,
            "signing_cert_sha256": request.client.signing_cert_sha256,
        },
    )
    result = evaluate_plan_authorization(request=core_request, plan_document=document)
    result["capability_resolution"] = {
        "source": "server-side-dsg-capability-broker",
        "requested": [item.capability for item in request.required_capabilities],
        "caller_can_assert_availability": False,
        "secrets_exposed": False,
    }
    return result


@router.get("/client-contract")
async def client_contract() -> dict[str, Any]:
    return {
        "client": audited_mobile_identity(),
        "decision_core": "/api/v1/control/contract",
        "control": {
            "preflight": "POST /api/v1/mobile/control/preflight",
            "execution_record": "POST /api/v1/executions",
            "evidence": "POST /api/v1/executions/{execution_id}/evidence",
            "verification": "POST /api/v1/executions/{execution_id}/verify",
            "proof": "GET /api/v1/proofs/{proof_id}",
        },
        "rule": (
            "mobile identity is checked here; all plan authorization and server-side capability "
            "decisions are delegated to the unified DSG core"
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
