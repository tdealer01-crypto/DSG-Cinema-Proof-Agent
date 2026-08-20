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
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from marketplace_verification import (
    POLICY_VERSION,
    RECEIPT_VERSION,
    VerificationRequest,
    context_hash as verification_context_hash,
    target_decision as verification_target_decision,
)

app = FastAPI(title="DSG Cinema Proof Agent", version="1.2.0")

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
    allow_headers=["Content-Type", "Accept"],
)


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


def _validate_exact_proof(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Z3 returned non-object JSON")
    if body.get("verified") is not True:
        raise HTTPException(status_code=502, detail="Z3 proof is not verified")
    if body.get("verification") != "VERIFIED_GLOBAL_OPTIMUM":
        raise HTTPException(status_code=502, detail="Z3 did not prove global optimality")

    proof_hash = body.get("proof_hash")
    request_hash = body.get("request_hash")
    if not isinstance(proof_hash, str) or len(proof_hash) != 64:
        raise HTTPException(status_code=502, detail="Z3 proof_hash is invalid")
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        raise HTTPException(status_code=502, detail="Z3 request_hash is invalid")
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
        raise HTTPException(status_code=502, detail="Z3 backend request failed") from exc

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
    # Three binary variables: [ALLOW, REVIEW, BLOCK].
    # A one-hot penalty keeps exactly one variable selected.
    penalty = 100
    costs = {
        "ALLOW": [0, 30, 60],
        "REVIEW": [40, 0, 40],
        "BLOCK": [60, 30, 0],
    }[target]
    linear = [cost - penalty for cost in costs]
    pair_penalty = 2 * penalty
    quadratic = [
        [0, 1, pair_penalty],
        [0, 2, pair_penalty],
        [1, 2, pair_penalty],
    ]
    return linear, quadratic


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


@app.get("/health")
async def health() -> JSONResponse:
    try:
        _backend_url()
        _required_secret("DSG_BACKEND_API_KEY")
        _required_secret("CINEMA_API_SECRET")
        status_code, body = await z3_request("GET", "/ready")
    except (ConfigurationError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return JSONResponse(
            status_code=503,
            content={"status": "blocked", "backend": "unavailable", "detail": detail},
        )

    if status_code != 200 or not isinstance(body, dict) or body.get("status") != "ready":
        return JSONResponse(
            status_code=503,
            content={"status": "blocked", "backend": "not_ready"},
        )
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
        raise HTTPException(status_code=502, detail=f"Z3 solve failed with HTTP {status_code}")

    verified_proof = _validate_exact_proof(proof)
    return {
        "cinema_status": "VERIFIED",
        "verified": True,
        "verification": "VERIFIED_GLOBAL_OPTIMUM",
        "proof_hash": verified_proof["proof_hash"],
        "request_hash": verified_proof["request_hash"],
        "z3_proof": verified_proof,
    }


@app.post("/verify/evaluate")
async def verify_evaluate(request: VerificationRequest) -> dict[str, Any]:
    """Create a deterministic Verified Execution receipt for any marketplace.

    The endpoint accepts only bounded verification facts, never an arbitrary
    QUBO. Cinema derives the fixed 3-variable ALLOW/REVIEW/BLOCK problem and
    requires an exact Z3 global-optimum proof before returning a receipt.
    """
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
        raise HTTPException(status_code=502, detail=f"Z3 solve failed with HTTP {status_code}")

    verified_proof = _validate_exact_proof(proof)
    decision = _decision_from_witness(verified_proof.get("witness"))
    if decision != target:
        raise HTTPException(status_code=502, detail="Z3 decision does not match deterministic policy target")

    return {
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


@app.post("/stripe/evaluate")
async def stripe_evaluate(request: StripeVerifyRequest) -> dict[str, Any]:
    """Verify a Stripe-context policy decision with an exact Z3 proof.

    This route intentionally accepts no arbitrary QUBO or solver program. The
    backend derives a fixed-size decision QUBO itself, keeping public compute
    bounded and the Z3 credential server-side.
    """
    if not request.stripe_account_id.startswith("acct_"):
        raise HTTPException(status_code=400, detail="invalid stripe_account_id")
    if not request.object_id.startswith(_stripe_prefix(request.object_type)):
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
        raise HTTPException(status_code=502, detail=f"Z3 solve failed with HTTP {status_code}")

    verified_proof = _validate_exact_proof(proof)
    decision = _decision_from_witness(verified_proof.get("witness"))
    if decision != target:
        raise HTTPException(status_code=502, detail="Z3 decision does not match deterministic policy target")

    if factors:
        reason = "; ".join(factors)
    else:
        reason = "No elevated risk factors detected"

    return {
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
