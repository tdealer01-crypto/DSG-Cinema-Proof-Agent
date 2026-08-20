#!/usr/bin/env python3
"""Server-side Cinema adapter for the deterministic Z3 verifier.

The Cinema client credential and the Z3 backend credential are intentionally
separate. Neither credential is returned to clients or written to logs.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="DSG Cinema Proof Agent", version="1.0.0")


class ConfigurationError(RuntimeError):
    pass


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
