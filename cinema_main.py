#!/usr/bin/env python3
"""Server-side Cinema adapter for the deterministic Z3 verifier.

The Cinema client credential and the Z3 backend credential are intentionally
separate. Neither credential is returned to clients or written to logs.

Marketplace requests use constrained endpoints that never accept arbitrary
solver programs. Cinema deterministically maps bounded business context to a
3-variable ALLOW/REVIEW/BLOCK QUBO and asks the server-side Z3 verifier to
prove the global optimum.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import api_v1
from api_v1.verifier import decision_qubo
from logging_config import get_logger, initialize_sentry, logger
from middleware import ErrorHandlingMiddleware, RequestTrackingMiddleware
from metrics import router as metrics_router
from error_monitoring import router as error_monitoring_router
from marketplace_verification import (
    POLICY_VERSION,
    RECEIPT_VERSION,
    VerificationRequest,
    context_hash as verification_context_hash,
    target_decision as verification_target_decision,
)
from revenue import api as billing

# Initialize logging and Sentry
initialize_sentry()
logger.info("Cinema API starting", extra={"extra_data": {"version": "1.3.0"}})

app = FastAPI(title="DSG Cinema Proof Agent", version="1.3.0")

# Add middleware (order matters - error handling outermost)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestTrackingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.stripe.com",
        "https://dashboard-test.stripe.com",
        "https://dsgoneverifiedweb.z1.web.core.windows.net",
        "https://dsg-one-verified-execution.onrender.com",
    ],
    allow_origin_regex=r"https://[a-z0-9-]+\.z[0-9]+\.web\.core\.windows\.net",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-DSG-API-Key", "Authorization"],
)

# Include routers
app.include_router(billing.router)
app.include_router(metrics_router)
app.include_router(error_monitoring_router)

# The v1 verification flow (plans, alignment, constraints, executions, evidence,
# proofs, MCP). It shares this adapter's Z3 transport and billing gate, and it
# never accepts a verdict from the caller.
api_v1.install(app)

VERIFIED_EXECUTION_SKU = "verified_execution"
STRIPE_DECISION_SKU = "stripe_policy_decision"


class ConfigurationError(RuntimeError):
    pass


class StripeVerifyRequest(BaseModel):
    stripe_account_id: str = Field(min_length=6, max_length=255)
    object_type: Literal["charge", "payment_intent", "payout", "refund"]
    object_id: str = Field(min_length=4, max_length=255)
    amount_cents: int | None = Field(default=None, ge=0, le=100_000_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    stripe_status: str | None = Field(default=None, max_length=64)
    risk_level: Literal["low", "medium", "high", "critical"] | None = None


def _required_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if len(value) < 32:
        raise ConfigurationError(f"{name} is missing or too short")
    return value


def _backend_url() -> str:
    value = os.getenv("DSG_BACKEND_BASE_URL", "").strip().rstrip("/")
    if not value.startswith("https://"):
        raise ConfigurationError("DSG_BACKEND_BASE_URL must use HTTPS")
    return value


def _authorize(authorization: str | None) -> None:
    try:
        expected = _required_secret("CINEMA_API_SECRET")
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid bearer token")


def _proof_failure(message: str, code: str = billing.VERIFICATION_NOT_PROVED) -> HTTPException:
    """A 502 that tells the caller what to do, not just that something failed."""
    return HTTPException(
        status_code=502,
        detail={
            "error": code,
            "message": message,
            "remediation": billing.remediation_for(code).to_dict(),
        },
    )


def _validate_exact_proof(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise _proof_failure("Z3 returned non-object JSON")
    if body.get("verified") is not True:
        raise _proof_failure("Z3 proof is not verified")
    if body.get("verification") != "VERIFIED_GLOBAL_OPTIMUM":
        raise _proof_failure("Z3 did not prove global optimality")

    proof_hash = body.get("proof_hash")
    request_hash = body.get("request_hash")
    if not isinstance(proof_hash, str) or len(proof_hash) != 64:
        raise _proof_failure("Z3 proof_hash is invalid")
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        raise _proof_failure("Z3 request_hash is invalid")
    return body


async def z3_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    try:
        base_url = _backend_url()
        backend_secret = _required_secret("DSG_BACKEND_API_KEY")
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {backend_secret}",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=False) as client:
            response = await client.request(
                method,
                f"{base_url}{path}",
                headers=headers,
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise _proof_failure(
            "Z3 backend request failed",
            billing.BACKEND_UNAVAILABLE,
        ) from exc

    try:
        body: Any = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _stripe_prefix(object_type: str) -> str:
    return {
        "charge": "ch_",
        "payment_intent": "pi_",
        "payout": "po_",
        "refund": "re_",
    }[object_type]


def _stripe_risk_score(request: StripeVerifyRequest) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if request.amount_cents is None:
        score += 35
        reasons.append("amount unavailable")
    elif request.amount_cents >= 5_000_000:
        score += 45
        reasons.append("amount at or above 50,000 currency units")
    elif request.amount_cents >= 1_000_000:
        score += 30
        reasons.append("amount at or above 10,000 currency units")
    elif request.amount_cents >= 100_000:
        score += 10
        reasons.append("amount at or above 1,000 currency units")

    if request.object_type == "payout":
        score += 20
        reasons.append("payout operation")
    elif request.object_type == "refund":
        score += 10
        reasons.append("refund operation")

    if request.currency and request.currency.lower() not in {"usd", "thb"}:
        score += 5
        reasons.append("non-default currency")

    if request.stripe_status and request.stripe_status.lower() in {
        "failed",
        "canceled",
        "requires_action",
        "requires_payment_method",
        "unpaid",
    }:
        score += 25
        reasons.append(f"Stripe status {request.stripe_status.lower()}")

    if request.risk_level:
        risk_weight = {
            "low": 0,
            "medium": 20,
            "high": 45,
            "critical": 80,
        }[request.risk_level]
        score += risk_weight
        if risk_weight:
            reasons.append(f"risk level {request.risk_level}")

    return min(score, 100), reasons


def _risk_label(score: int) -> Literal["low", "medium", "high", "critical"]:
    if score >= 70:
        return "critical"
    if score >= 40:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _target_decision(score: int) -> Literal["ALLOW", "REVIEW", "BLOCK"]:
    if score >= 70:
        return "BLOCK"
    if score >= 20:
        return "REVIEW"
    return "ALLOW"


def _decision_qubo(target: str) -> tuple[list[int], list[list[int]]]:
    """The shared ALLOW/REVIEW/BLOCK encoding, owned by api_v1.verifier.

    One encoding for every route in this service: a receipt from /verify/evaluate
    and a receipt from /api/v1 name the same decision problem.
    """
    return decision_qubo(target)


def _decision_from_witness(witness: Any) -> Literal["ALLOW", "REVIEW", "BLOCK"]:
    if witness == [1, 0, 0]:
        return "ALLOW"
    if witness == [0, 1, 0]:
        return "REVIEW"
    if witness == [0, 0, 1]:
        return "BLOCK"
    raise HTTPException(status_code=502, detail="Z3 returned an invalid decision witness")


def _stripe_context_hash(request: StripeVerifyRequest, risk_score: int) -> str:
    canonical = {
        "stripe_account_id": request.stripe_account_id,
        "object_type": request.object_type,
        "object_id": request.object_id,
        "amount_cents": request.amount_cents,
        "currency": request.currency.lower() if request.currency else None,
        "stripe_status": request.stripe_status.lower() if request.stripe_status else None,
        "risk_level": request.risk_level,
        "risk_score": risk_score,
        "policy_version": "cinema-stripe-z3-1.0.0",
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


PROTOTYPE_PATH = Path(__file__).resolve().parent / "web" / "dsg-one-3d" / "index.html"
CUSTOMER_DASHBOARD_PATH = Path(__file__).resolve().parent / "web" / "customer-dashboard" / "index.html"


@app.get("/app", include_in_schema=False)
async def prototype_console() -> FileResponse:
    """Serve the DSG ONE console from the API's own origin.

    Same origin means the console needs no CORS grant and no configured base URL,
    so what it displays always comes from the deployment it is served by.
    """
    if not PROTOTYPE_PATH.exists():
        raise HTTPException(status_code=404, detail="the console bundle is not present in this image")
    return FileResponse(
        PROTOTYPE_PATH,
        media_type="text/html",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/dashboard-assets/{asset_name}", include_in_schema=False)
async def customer_dashboard_asset(asset_name: str) -> FileResponse:
    allowed = {
        "dashboard.css": "text/css",
        "dashboard.js": "application/javascript",
    }
    if asset_name not in allowed:
        raise HTTPException(status_code=404, detail="dashboard asset not found")
    asset_path = CUSTOMER_DASHBOARD_PATH.parent / asset_name
    return FileResponse(
        asset_path,
        media_type=allowed[asset_name],
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/dashboard", include_in_schema=False)
async def customer_dashboard() -> FileResponse:
    if not CUSTOMER_DASHBOARD_PATH.exists():
        raise HTTPException(status_code=404, detail="the customer dashboard bundle is not present")
    return FileResponse(
        CUSTOMER_DASHBOARD_PATH,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        },
    )


@app.get("/health")
async def health() -> JSONResponse:
    try:
        _backend_url()
        _required_secret("DSG_BACKEND_API_KEY")
        _required_secret("CINEMA_API_SECRET")
        status_code, body = await z3_request("GET", "/ready")
    except (ConfigurationError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        logger.warning(
            "Health check failed",
            extra={"extra_data": {"error": detail}},
        )
        return JSONResponse(
            status_code=503,
            content={"status": "blocked", "backend": "unavailable", "detail": detail},
        )

    if status_code != 200 or not isinstance(body, dict) or body.get("status") != "ready":
        logger.warning(
            "Backend not ready",
            extra={"extra_data": {"status_code": status_code}},
        )
        return JSONResponse(
            status_code=503,
            content={"status": "blocked", "backend": "not_ready"},
        )
    logger.info("Health check passed")
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "backend": "ready"},
    )


@app.post("/solve")
async def solve(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)

    status_code, proof = await z3_request("POST", "/solve", payload)
    if status_code != 200:
        raise _proof_failure(
            f"Z3 solve failed with HTTP {status_code}",
            billing.BACKEND_UNAVAILABLE,
        )

    verified_proof = _validate_exact_proof(proof)
    return {
        "cinema_status": "VERIFIED",
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": verified_proof["proof_hash"],
        "request_hash": verified_proof["request_hash"],
        "z3_proof": verified_proof,
    }


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"check": name, "status": status, "detail": detail}


@app.get("/support/diagnose")
async def support_diagnose(
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Tell a caller exactly why verification is not working for them right now.

    The route answers the support question directly instead of leaving a user to
    infer it from an HTTP status: it reports which checks pass, which one blocks,
    and the single next action that resolves it. It requires no credential, and
    it never reveals whether a specific unknown key exists beyond pass or fail.
    """
    checks: list[dict[str, str]] = []
    blocking: str | None = None

    # 1. Deployment configuration.
    try:
        _backend_url()
        _required_secret("DSG_BACKEND_API_KEY")
        checks.append(
            _check("service_configuration", "pass", "Backend URL and credential are configured")
        )
    except ConfigurationError as exc:
        checks.append(_check("service_configuration", "fail", str(exc)))
        blocking = billing.CONFIGURATION_INCOMPLETE

    # 2. Verification backend reachability.
    if blocking is None:
        try:
            status_code, body = await z3_request("GET", "/ready")
            ready = status_code == 200 and isinstance(body, dict) and body.get("status") == "ready"
        except HTTPException as exc:
            ready = False
            body = exc.detail
        if ready:
            checks.append(_check("verification_backend", "pass", "Exact Z3 verifier is ready"))
        else:
            checks.append(_check("verification_backend", "fail", "Z3 verifier is not ready"))
            blocking = billing.BACKEND_UNAVAILABLE
    else:
        checks.append(
            _check("verification_backend", "skip", "Not checked while configuration is incomplete")
        )

    # 3. Caller identity and entitlement.
    entitlement = billing.diagnose_entitlement(x_dsg_api_key, VERIFIED_EXECUTION_SKU)
    checks.extend(entitlement["checks"])
    if blocking is None and entitlement["blocking"] is not None:
        blocking = entitlement["blocking"]

    if blocking is None:
        status = "READY"
    elif blocking in {
        billing.CONFIGURATION_INCOMPLETE,
        billing.BACKEND_UNAVAILABLE,
        billing.BILLING_STORAGE_NOT_READY,
    }:
        status = "SERVICE_UNAVAILABLE"
    else:
        status = "ACTION_REQUIRED"

    return {
        "status": status,
        "checks": checks,
        "remediation": billing.remediation_for(blocking or "OK").to_dict(),
        "billing": entitlement["billing"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/onboarding/status")
async def onboarding_status(
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    account = billing.get_engine().accounts.authenticate((x_dsg_api_key or "").strip())
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="a valid X-DSG-API-Key header is required",
        )

    try:
        status_code, backend = await z3_request("GET", "/ready")
        backend_connected = (
            status_code == 200
            and isinstance(backend, dict)
            and backend.get("status") == "ready"
        )
    except HTTPException:
        backend_connected = False

    try:
        first_proof_completed = any(
            entry.account_id == account.account_id
            and entry.sku == VERIFIED_EXECUTION_SKU
            for entry in billing.get_engine().ledger.entries()
        )
    except (OSError, ValueError):
        raise HTTPException(
            status_code=503,
            detail="onboarding proof history is unavailable",
        )

    durable_steps = {
        "account_activated": account.activation_ref is not None,
        "api_key_authenticated": True,
        "first_proof_completed": first_proof_completed,
    }
    steps = {
        **durable_steps,
        "backend_connected": backend_connected,
    }
    progress = round(sum(durable_steps.values()) / len(durable_steps) * 100)

    if not durable_steps["account_activated"]:
        status = "ACTION_REQUIRED"
        current_step = "ACTIVATE_ACCOUNT"
        next_action = {"method": "POST", "endpoint": "/billing/activate"}
    elif not first_proof_completed:
        status = "ACTION_REQUIRED"
        current_step = "RUN_FIRST_PROOF"
        next_action = {"method": "POST", "endpoint": "/onboarding/first-proof"}
    elif not backend_connected:
        status = "SERVICE_UNAVAILABLE"
        current_step = "COMPLETE"
        next_action = {"method": "GET", "endpoint": "/support/diagnose"}
    else:
        status = "READY"
        current_step = "COMPLETE"
        next_action = None

    return {
        "status": status,
        "current_step": current_step,
        "progress": progress,
        "steps": steps,
        "next_action": next_action,
        "account": account.public_view(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/onboarding/first-proof")
async def onboarding_first_proof(
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Run one bounded, non-mutating proof through the production verification path."""
    account = billing.get_engine().accounts.authenticate((x_dsg_api_key or "").strip())
    if account is None:
        raise HTTPException(status_code=401, detail="missing or invalid DSG API key")
    fixture_hash = hashlib.sha256(b"dsg-one-guided-first-proof-v1").hexdigest()
    request = VerificationRequest(
        execution_id=f"onboarding-{account.account_id}",
        trace_id="guided-first-proof-v1",
        channel="api",
        agent_identity="dsg-one-onboarding",
        approved_plan_hash=fixture_hash,
        proposed_action_hash=fixture_hash,
        authorized=True,
        plan_aligned=True,
        constraints_pass=True,
        execution_succeeded=True,
        replay_match=True,
        evidence_complete=True,
        cost_microunits=0,
    )
    return await verify_evaluate(request, x_dsg_api_key)


@app.post("/verify/evaluate")
async def verify_evaluate(
    request: VerificationRequest,
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Create a deterministic Verified Execution receipt for any marketplace.

    The endpoint accepts only bounded verification facts, never an arbitrary
    QUBO. Cinema derives the fixed 3-variable ALLOW/REVIEW/BLOCK problem and
    requires an exact Z3 global-optimum proof before returning a receipt.

    Entitlement is checked before any solver work, and the receipt is metered
    only after Z3 has proved the global optimum.
    """
    logger.info(
        "Verification request received",
        extra={
            "extra_data": {
                "channel": request.channel,
                "execution_id": request.execution_id,
            }
        },
    )

    authorization = billing.authorize_request(x_dsg_api_key, VERIFIED_EXECUTION_SKU)
    target, factors = verification_target_decision(request)
    linear, quadratic = _decision_qubo(target)
    context_hash = verification_context_hash(request)

    solver_payload = {
        "request_id": f"verify-{context_hash[:24]}",
        "preset_name": "verified-execution-v1",
        "problem_type": "qubo",
        "linear": linear,
        "quadratic": quadratic,
        "proveOptimality": True,
        "z3TimeoutMs": 30000,
    }

    status_code, proof = await z3_request("POST", "/solve", solver_payload)
    if status_code != 200:
        logger.error(
            "Z3 solve failed",
            extra={
                "extra_data": {
                    "status_code": status_code,
                    "channel": request.channel,
                }
            },
        )
        raise _proof_failure(
            f"Z3 solve failed with HTTP {status_code}",
            billing.BACKEND_UNAVAILABLE,
        )

    verified_proof = _validate_exact_proof(proof)
    decision = _decision_from_witness(verified_proof.get("witness"))
    if decision != target:
        logger.error(
            "Z3 decision mismatch",
            extra={
                "extra_data": {
                    "target": target,
                    "decision": decision,
                    "channel": request.channel,
                }
            },
        )
        raise HTTPException(status_code=502, detail="Z3 decision does not match deterministic policy target")

    logger.info(
        "Verification successful",
        extra={
            "extra_data": {
                "channel": request.channel,
                "decision": decision,
                "proof_hash": verified_proof["proof_hash"][:16],
            }
        },
    )

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "policy_version": POLICY_VERSION,
        "execution_id": request.execution_id,
        "trace_id": request.trace_id,
        "channel": request.channel,
        "decision": decision,
        "reason": "; ".join(factors),
        "authorized_action_completion": bool(
            request.authorized
            and request.plan_aligned
            and request.constraints_pass
            and request.execution_succeeded
        ),
        "out_of_plan_rejection": bool(not request.authorized or not request.plan_aligned),
        "z3_constraint_correctness": bool(request.constraints_pass and verified_proof.get("verified") is True),
        "replay_match": request.replay_match,
        "evidence_completeness": 1.0 if request.evidence_complete else 0.0,
        "cost_microunits": request.cost_microunits,
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": verified_proof["proof_hash"],
        "request_hash": verified_proof["request_hash"],
        "context_hash": context_hash,
        "witness": verified_proof["witness"],
        "energy_exact": verified_proof.get("energy_exact"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    billing_block = await billing.meter(
        authorization,
        sku=VERIFIED_EXECUTION_SKU,
        receipt=receipt,
        channel=request.channel,
    )
    if billing_block is not None:
        receipt["billing"] = billing_block
    return receipt


@app.post("/stripe/evaluate")
async def stripe_evaluate(
    request: StripeVerifyRequest,
    x_dsg_api_key: str | None = Header(default=None, alias="X-DSG-API-Key"),
) -> dict[str, Any]:
    """Verify a Stripe-context policy decision with an exact Z3 proof.

    This route intentionally accepts no arbitrary QUBO or solver program. The
    backend derives a fixed-size decision QUBO itself, keeping public compute
    bounded and the Z3 credential server-side.
    """
    logger.info(
        "Stripe verification request received",
        extra={
            "extra_data": {
                "stripe_account_id": request.stripe_account_id[:10],  # Partial for security
                "object_type": request.object_type,
            }
        },
    )

    authorization = billing.authorize_request(x_dsg_api_key, STRIPE_DECISION_SKU)
    if not request.stripe_account_id.startswith("acct_"):
        logger.warning(
            "Invalid Stripe account ID",
            extra={"extra_data": {"error": "invalid_account_id"}},
        )
        raise HTTPException(status_code=400, detail="invalid stripe_account_id")
    if not request.object_id.startswith(_stripe_prefix(request.object_type)):
        logger.warning(
            "Object ID mismatch",
            extra={"extra_data": {"error": "object_type_mismatch"}},
        )
        raise HTTPException(status_code=400, detail="object_id does not match object_type")

    score, factors = _stripe_risk_score(request)
    target = _target_decision(score)
    linear, quadratic = _decision_qubo(target)
    context_hash = _stripe_context_hash(request, score)

    solver_payload = {
        "request_id": f"stripe-{context_hash[:24]}",
        "preset_name": "stripe-policy-decision-v1",
        "problem_type": "qubo",
        "linear": linear,
        "quadratic": quadratic,
        "proveOptimality": True,
        "z3TimeoutMs": 30000,
    }

    status_code, proof = await z3_request("POST", "/solve", solver_payload)
    if status_code != 200:
        logger.error(
            "Stripe Z3 solve failed",
            extra={
                "extra_data": {
                    "status_code": status_code,
                    "risk_score": score,
                }
            },
        )
        raise _proof_failure(
            f"Z3 solve failed with HTTP {status_code}",
            billing.BACKEND_UNAVAILABLE,
        )

    verified_proof = _validate_exact_proof(proof)
    decision = _decision_from_witness(verified_proof.get("witness"))
    if decision != target:
        logger.error(
            "Stripe Z3 decision mismatch",
            extra={
                "extra_data": {
                    "target": target,
                    "decision": decision,
                    "risk_score": score,
                }
            },
        )
        raise HTTPException(status_code=502, detail="Z3 decision does not match deterministic policy target")

    logger.info(
        "Stripe verification successful",
        extra={
            "extra_data": {
                "decision": decision,
                "risk_score": score,
                "risk_level": _risk_label(score),
            }
        },
    )

    if factors:
        reason = "; ".join(factors)
    else:
        reason = "No elevated risk factors detected"

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "decision": decision,
        "reason": reason,
        "risk_score": score,
        "risk_level": _risk_label(score),
        "policy_version": "cinema-stripe-z3-1.0.0",
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": verified_proof["proof_hash"],
        "request_hash": verified_proof["request_hash"],
        "context_hash": context_hash,
        "witness": verified_proof["witness"],
        "energy_exact": verified_proof.get("energy_exact"),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    billing_block = await billing.meter(
        authorization,
        sku=STRIPE_DECISION_SKU,
        receipt=receipt,
        channel="stripe",
    )
    if billing_block is not None:
        receipt["billing"] = billing_block
    return receipt
