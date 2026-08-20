#!/usr/bin/env python3
"""Deterministic Z3 verification service for DSG ONE.

QUBO contract:
- linear: [c0, c1, ...]
- quadratic: [[i, j, coefficient], ...]
- binary variables x_i in {0,1}
- objective: sum(c_i*x_i) + sum(q_ij*x_i*x_j)

For QUBO requests the service finds a minimum candidate and then performs an
independent lower-bound check. The result is only marked VERIFIED_GLOBAL_OPTIMUM
when the verifier proves that no assignment has lower energy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from z3 import And, Bool, If, Not, Optimize, Or, RealVal, Solver, get_version_string, is_true, sat, unsat

Z3_TIMEOUT_MS = int(os.getenv("Z3_TIMEOUT_MS", "30000"))
Z3_SEED = int(os.getenv("Z3_DETERMINISTIC_SEED", "42"))
SHARED_SECRET = os.getenv("DSG_SOLVER_SHARED_SECRET")

# Accepted only while a deployment is rotating the shared credential. Cinema and
# Z3 are updated in separate steps, so without this the requests in flight
# between those two steps would fail authorization against a secret that is
# correct but one revision old. The deployment clears it once Cinema is on the
# new value.
PREVIOUS_SECRET = (os.getenv("DSG_SOLVER_PREVIOUS_SECRET") or "").strip() or None

app = FastAPI(title="DSG ONE Z3 Verification Service", version="2.0.0")


class SolveRequest(BaseModel):
    request_id: str
    preset_name: str = "default"
    problem_type: Literal["qubo", "sat", "QUBO", "SAT"]
    linear: Optional[list[Decimal]] = None
    quadratic: Optional[list[tuple[int, int, Decimal]]] = None
    witness: Optional[list[int]] = None
    clauses: Optional[list[list[int]]] = None
    proveOptimality: bool = True
    z3TimeoutMs: int = Z3_TIMEOUT_MS


class SolveResponse(BaseModel):
    request_id: str
    z3_status: str
    verification: str
    verified: bool
    witness: Optional[list[int]] = None
    energy: Optional[float] = None
    energy_exact: Optional[str] = None
    proof_hash: str
    request_hash: str
    compute_ms: int
    timestamp: str
    audit: dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def z3_decimal(value: Decimal):
    return RealVal(decimal_string(value))


def accepted_secrets() -> list[str]:
    """Credentials this instance honours, newest first.

    Normalisation happens here rather than only at load time so a blank value
    can never widen authorization, however the setting was supplied.
    """
    secrets = []
    current = (SHARED_SECRET or "").strip()
    if current:
        secrets.append(current)
    previous = (PREVIOUS_SECRET or "").strip()
    if previous and previous != current:
        secrets.append(previous)
    return secrets


def token_is_accepted(token: str) -> bool:
    """Constant-time membership test across every accepted credential.

    Every candidate is compared even after a match so the response time cannot
    reveal which credential matched or how many are configured.
    """
    matched = False
    for candidate in accepted_secrets():
        matched |= hmac.compare_digest(token, candidate)
    return matched


def require_auth(authorization: Optional[str]) -> None:
    if not SHARED_SECRET:
        raise HTTPException(status_code=503, detail="solver secret is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer authorization required")
    token = authorization[7:].strip()
    if not token or not token_is_accepted(token):
        raise HTTPException(status_code=403, detail="invalid bearer token")


def canonical_request(req: SolveRequest) -> dict:
    return {
        "request_id": req.request_id,
        "preset_name": req.preset_name,
        "problem_type": req.problem_type.lower(),
        "linear": [decimal_string(v) for v in (req.linear or [])],
        "quadratic": [
            [i, j, decimal_string(coefficient)]
            for i, j, coefficient in (req.quadratic or [])
        ],
        "witness": req.witness,
        "clauses": req.clauses,
        "proveOptimality": req.proveOptimality,
        "z3TimeoutMs": req.z3TimeoutMs,
        "seed": Z3_SEED,
    }


def sha256_json(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_qubo_objective(
    linear: list[Decimal],
    quadratic: list[tuple[int, int, Decimal]],
    variables,
):
    objective = RealVal("0")
    for i, coefficient in enumerate(linear):
        objective = objective + If(variables[i], z3_decimal(coefficient), RealVal("0"))
    for i, j, coefficient in quadratic:
        objective = objective + If(
            And(variables[i], variables[j]),
            z3_decimal(coefficient),
            RealVal("0"),
        )
    return objective


def validate_qubo(
    linear: Optional[list[Decimal]],
    quadratic: Optional[list[tuple[int, int, Decimal]]],
) -> None:
    if linear is None or not linear:
        raise HTTPException(
            status_code=422,
            detail="QUBO linear must contain at least one coefficient",
        )
    n = len(linear)
    for i, j, _ in quadratic or []:
        if i < 0 or j < 0 or i >= n or j >= n:
            raise HTTPException(
                status_code=422,
                detail=f"quadratic index out of range: [{i}, {j}]",
            )
        if i > j:
            raise HTTPException(
                status_code=422,
                detail=f"quadratic term must use i <= j: [{i}, {j}]",
            )


def energy_decimal(
    linear: list[Decimal],
    quadratic: list[tuple[int, int, Decimal]],
    witness: list[int],
) -> Decimal:
    total = Decimal("0")
    for i, coefficient in enumerate(linear):
        total += coefficient * witness[i]
    for i, j, coefficient in quadratic:
        total += coefficient * witness[i] * witness[j]
    return total


def solve_qubo_exact(
    linear: list[Decimal],
    quadratic: list[tuple[int, int, Decimal]],
    timeout_ms: int,
    candidate_witness: Optional[list[int]] = None,
):
    validate_qubo(linear, quadratic)
    n = len(linear)

    if candidate_witness is not None:
        if len(candidate_witness) != n or any(
            bit not in (0, 1) for bit in candidate_witness
        ):
            raise HTTPException(
                status_code=422,
                detail="witness must contain exactly one binary value per QUBO variable",
            )
        witness = list(candidate_witness)
    else:
        variables = [Bool(f"x_{i}") for i in range(n)]
        objective = build_qubo_objective(linear, quadratic, variables)
        optimizer = Optimize()
        optimizer.set(timeout=timeout_ms, priority="lex")
        optimizer.minimize(objective)

        # Deterministic tie-break: lexicographically smallest binary witness.
        tie_break = sum(
            If(variables[i], 1 << (n - i - 1), 0)
            for i in range(n)
        )
        optimizer.minimize(tie_break)

        status = optimizer.check()
        if status != sat:
            return {
                "z3_status": "TIMEOUT" if str(status) == "unknown" else "ERROR",
                "verification": "NOT_VERIFIED",
                "verified": False,
                "witness": None,
                "energy": None,
                "energy_exact": None,
            }

        model = optimizer.model()
        witness = [
            1 if is_true(model.eval(v, model_completion=True)) else 0
            for v in variables
        ]

    candidate_energy = energy_decimal(linear, quadratic, witness)
    candidate_exact = decimal_string(candidate_energy)

    # Independent proof obligation: a better assignment must not exist.
    verifier_vars = [Bool(f"verify_x_{i}") for i in range(n)]
    verifier_objective = build_qubo_objective(
        linear,
        quadratic,
        verifier_vars,
    )
    verifier = Solver()
    verifier.set(timeout=timeout_ms)
    verifier.add(verifier_objective < z3_decimal(candidate_energy))
    lower_status = verifier.check()

    if lower_status == unsat:
        verification = "VERIFIED_GLOBAL_OPTIMUM"
        verified = True
    elif lower_status == sat:
        verification = "COUNTEREXAMPLE_FOUND"
        verified = False
    else:
        verification = "VERIFICATION_TIMEOUT"
        verified = False

    return {
        "z3_status": "SAT",
        "verification": verification,
        "verified": verified,
        "witness": witness,
        "energy": float(candidate_energy),
        "energy_exact": candidate_exact,
    }


def solve_sat_deterministic(clauses: list[list[int]], timeout_ms: int):
    max_var = 0
    for clause in clauses:
        if not clause:
            return {
                "z3_status": "UNSAT",
                "verification": "UNSATISFIABLE",
                "verified": True,
                "witness": None,
                "energy": None,
                "energy_exact": None,
            }
        max_var = max(max_var, max(abs(literal) for literal in clause))

    if max_var == 0:
        return {
            "z3_status": "SAT",
            "verification": "SATISFIABLE",
            "verified": True,
            "witness": [],
            "energy": None,
            "energy_exact": None,
        }

    variables = {i: Bool(f"sat_x_{i}") for i in range(1, max_var + 1)}
    solver = Solver()
    solver.set(timeout=timeout_ms)
    for clause in clauses:
        solver.add(
            Or(
                [
                    variables[abs(lit)]
                    if lit > 0
                    else Not(variables[-lit])
                    for lit in clause
                ]
            )
        )

    status = solver.check()
    if status == unsat:
        return {
            "z3_status": "UNSAT",
            "verification": "UNSATISFIABLE",
            "verified": True,
            "witness": None,
            "energy": None,
            "energy_exact": None,
        }
    if status != sat:
        return {
            "z3_status": "TIMEOUT",
            "verification": "NOT_VERIFIED",
            "verified": False,
            "witness": None,
            "energy": None,
            "energy_exact": None,
        }

    # Deterministically choose the lexicographically smallest satisfying witness.
    for i in range(1, max_var + 1):
        solver.push()
        solver.add(Not(variables[i]))
        trial = solver.check()
        solver.pop()
        if trial == sat:
            solver.add(Not(variables[i]))
        elif trial == unsat:
            solver.add(variables[i])
        else:
            return {
                "z3_status": "TIMEOUT",
                "verification": "NOT_VERIFIED",
                "verified": False,
                "witness": None,
                "energy": None,
                "energy_exact": None,
            }

    if solver.check() != sat:
        return {
            "z3_status": "ERROR",
            "verification": "NOT_VERIFIED",
            "verified": False,
            "witness": None,
            "energy": None,
            "energy_exact": None,
        }

    model = solver.model()
    witness = [
        1 if is_true(model.eval(variables[i], model_completion=True)) else 0
        for i in range(1, max_var + 1)
    ]
    return {
        "z3_status": "SAT",
        "verification": "SATISFIABLE",
        "verified": True,
        "witness": witness,
        "energy": None,
        "energy_exact": None,
    }


@app.get("/health")
def health():
    return {
        "status": "alive",
        "service": "dsg-z3-verifier",
        "version": app.version,
        "z3_version": get_version_string(),
    }


@app.get("/ready")
def ready():
    if not SHARED_SECRET:
        raise HTTPException(
            status_code=503,
            detail="solver secret is not configured",
        )
    return {"status": "ready", "service": "dsg-z3-verifier"}


@app.get("/metrics")
def metrics():
    return {
        "service": "dsg-z3-verifier",
        "version": app.version,
        "z3_version": get_version_string(),
        "deterministic": True,
        "seed": Z3_SEED,
        "timeout_ms": Z3_TIMEOUT_MS,
        "secret_configured": bool(SHARED_SECRET),
        "rotation_in_progress": len(accepted_secrets()) > 1,
    }


@app.post("/solve", response_model=SolveResponse)
def solve(req: SolveRequest, authorization: Optional[str] = Header(None)):
    started = time.monotonic()
    require_auth(authorization)

    if req.z3TimeoutMs <= 0 or req.z3TimeoutMs > 120000:
        raise HTTPException(
            status_code=422,
            detail="z3TimeoutMs must be between 1 and 120000",
        )

    problem_type = req.problem_type.lower()
    if problem_type == "qubo":
        result = solve_qubo_exact(
            req.linear or [],
            req.quadratic or [],
            req.z3TimeoutMs,
            req.witness,
        )
    else:
        if req.clauses is None:
            raise HTTPException(status_code=422, detail="SAT clauses are required")
        result = solve_sat_deterministic(req.clauses, req.z3TimeoutMs)

    request_payload = canonical_request(req)
    request_hash = sha256_json(request_payload)
    proof_payload = {
        "request_hash": request_hash,
        "z3_status": result["z3_status"],
        "verification": result["verification"],
        "verified": result["verified"],
        "witness": result["witness"],
        "energy_exact": result["energy_exact"],
        "z3_version": get_version_string(),
        "seed": Z3_SEED,
    }
    proof_hash = sha256_json(proof_payload)
    timestamp = utc_now()
    compute_ms = int((time.monotonic() - started) * 1000)
    event_hash = sha256_json(
        {
            "proof_hash": proof_hash,
            "timestamp": timestamp,
            "request_id": req.request_id,
        }
    )

    return SolveResponse(
        request_id=req.request_id,
        z3_status=result["z3_status"],
        verification=result["verification"],
        verified=result["verified"],
        witness=result["witness"],
        energy=result["energy"],
        energy_exact=result["energy_exact"],
        proof_hash=proof_hash,
        request_hash=request_hash,
        compute_ms=compute_ms,
        timestamp=timestamp,
        audit={
            "event_hash": event_hash,
            "preset_name": req.preset_name,
            "z3_status": result["z3_status"],
            "verification": result["verification"],
        },
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
