"""Native exact top-k proof for the DSG Z3 verifier.

The endpoint never accepts a caller verdict. It computes the deterministic
Decimal oracle, asks Z3 Optimize for the exact same optimum over Real values,
and then uses independent Solver instances to prove that neither a higher score
nor a better lexicographic ID tie-break exists.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from z3 import Bool, If, IntVal, Not, Optimize, RealVal, Solver, Sum, is_true, sat, unsat

DECIMAL_PATTERN = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
DECIMAL_RE = re.compile(DECIMAL_PATTERN)
EXP_RE = re.compile(r"[eE]([+-]?\d+)$")
MAX_RAW_LENGTH = 240
MAX_Z3_EXPONENT = 1000
MAX_CANDIDATES = 24
MAX_K = 12
Z3_SEED = int(os.getenv("Z3_DETERMINISTIC_SEED", "42"))
DEFAULT_TIMEOUT_MS = int(os.getenv("Z3_TIMEOUT_MS", "30000"))


class ExactCandidate(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    composite: str = Field(min_length=1, max_length=MAX_RAW_LENGTH, pattern=DECIMAL_PATTERN)


class ExactSelectRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    candidates: list[ExactCandidate] = Field(min_length=1, max_length=MAX_CANDIDATES)
    k: int = Field(default=12, ge=1, le=MAX_K)
    minComposite: str = Field(default="0", min_length=1, max_length=MAX_RAW_LENGTH, pattern=DECIMAL_PATTERN)
    z3TimeoutMs: int = Field(default=DEFAULT_TIMEOUT_MS, ge=1, le=120000)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _raw_exponent(raw: str) -> int:
    match = EXP_RE.search(raw)
    return int(match.group(1)) if match else 0


def _parse_decimal(raw: str, field: str) -> Decimal:
    if len(raw) > MAX_RAW_LENGTH or not DECIMAL_RE.fullmatch(raw):
        raise HTTPException(status_code=422, detail=f"invalid exact decimal: {field}")
    exponent = _raw_exponent(raw)
    if abs(exponent) > MAX_Z3_EXPONENT:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Z3_EXPONENT_LIMIT",
                "field": field,
                "max_abs_exponent": MAX_Z3_EXPONENT,
                "received_exponent": exponent,
            },
        )
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise HTTPException(status_code=422, detail=f"invalid exact decimal: {field}") from exc


def _sha256_json(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise_request(req: ExactSelectRequest):
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []
    decimals: list[Decimal] = []
    for index, candidate in enumerate(req.candidates):
        if candidate.id in seen:
            raise HTTPException(
                status_code=422,
                detail={"error": "DUPLICATE_CANDIDATE_ID", "id": candidate.id, "index": index},
            )
        seen.add(candidate.id)
        decimal_value = _parse_decimal(candidate.composite, f"candidate:{candidate.id}")
        candidates.append({"id": candidate.id, "composite": candidate.composite})
        decimals.append(decimal_value)
    minimum = _parse_decimal(req.minComposite, "minComposite")
    return candidates, decimals, minimum


def _oracle(candidates: list[dict[str, str]], decimals: list[Decimal], minimum: Decimal, k: int):
    eligible = [
        (candidate, decimal_value)
        for candidate, decimal_value in zip(candidates, decimals)
        if decimal_value >= minimum
    ]
    eligible.sort(key=lambda item: (-item[1], item[0]["id"]))
    return [item[0] for item in eligible[:k]], eligible


def _build_expressions(candidates, decimals, minimum, k):
    variables = [Bool(f"exact_selected_{i}") for i in range(len(candidates))]
    z3_scores = [RealVal(candidate["composite"]) for candidate in candidates]
    z3_minimum = RealVal(_decimal_string(minimum))
    count_expr = Sum([If(variable, 1, 0) for variable in variables])
    score_expr = Sum(
        [If(variable, score, RealVal("0")) for variable, score in zip(variables, z3_scores)]
    )
    id_order = sorted(range(len(candidates)), key=lambda index: candidates[index]["id"])
    rank = {candidate_index: position for position, candidate_index in enumerate(id_order)}
    weights = [1 << (len(candidates) - rank[index] - 1) for index in range(len(candidates))]
    tie_expr = Sum([If(variable, IntVal(weights[i]), IntVal(0)) for i, variable in enumerate(variables)])

    def add_base(solver) -> None:
        solver.add(count_expr == k)
        for index, (variable, decimal_value, score) in enumerate(zip(variables, decimals, z3_scores)):
            if decimal_value >= minimum:
                solver.add(score >= z3_minimum)
            else:
                solver.add(score < z3_minimum)
                solver.add(Not(variable))

    return variables, score_expr, tie_expr, weights, add_base


def install_exact_topk(app: FastAPI, require_auth: Callable[[Optional[str]], None]) -> None:
    @app.post("/exact-select")
    def exact_select(req: ExactSelectRequest, authorization: Optional[str] = Header(None)):
        started = time.monotonic()
        require_auth(authorization)
        candidates, decimals, minimum = _normalise_request(req)
        expected, eligible = _oracle(candidates, decimals, minimum, req.k)
        if len(eligible) < req.k:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "INSUFFICIENT_CANDIDATES_FOR_EXACT_K",
                    "required": req.k,
                    "actual": len(eligible),
                },
            )

        variables, score_expr, tie_expr, weights, add_base = _build_expressions(
            candidates, decimals, minimum, req.k
        )
        optimizer = Optimize()
        optimizer.set(timeout=req.z3TimeoutMs, priority="lex")
        add_base(optimizer)
        optimizer.maximize(score_expr)
        optimizer.maximize(tie_expr)
        optimize_status = optimizer.check()
        if optimize_status != sat:
            return {
                "request_id": req.request_id,
                "z3_status": "TIMEOUT" if str(optimize_status) == "unknown" else "ERROR",
                "verification": "NOT_VERIFIED",
                "verified": False,
                "selected": [],
                "proof_hash": "",
                "request_hash": "",
                "compute_ms": int((time.monotonic() - started) * 1000),
                "timestamp": _utc_now(),
            }

        model = optimizer.model()
        model_selected = [
            candidates[index]
            for index, variable in enumerate(variables)
            if is_true(model.eval(variable, model_completion=True))
        ]
        model_selected.sort(key=lambda candidate: (-_parse_decimal(candidate["composite"], candidate["id"]), candidate["id"]))
        if model_selected != expected:
            return {
                "request_id": req.request_id,
                "z3_status": "SAT",
                "verification": "Z3_DETERMINISTIC_RESULT_MISMATCH",
                "verified": False,
                "selected": model_selected,
                "expected": expected,
                "proof_hash": "",
                "request_hash": "",
                "compute_ms": int((time.monotonic() - started) * 1000),
                "timestamp": _utc_now(),
            }

        selected_ids = {candidate["id"] for candidate in expected}
        total_score = sum(
            (_parse_decimal(candidate["composite"], candidate["id"]) for candidate in expected),
            Decimal("0"),
        )
        expected_score = _decimal_string(total_score)
        expected_tie = sum(
            weights[index] for index, candidate in enumerate(candidates) if candidate["id"] in selected_ids
        )

        better_score = Solver()
        better_score.set(timeout=req.z3TimeoutMs, random_seed=Z3_SEED)
        add_base(better_score)
        better_score.add(score_expr > RealVal(expected_score))
        score_status = better_score.check()
        if score_status != unsat:
            return {
                "request_id": req.request_id,
                "z3_status": "SAT" if score_status == sat else "TIMEOUT",
                "verification": "BETTER_SCORE_NOT_REFUTED",
                "verified": False,
                "selected": expected,
                "proof_hash": "",
                "request_hash": "",
                "compute_ms": int((time.monotonic() - started) * 1000),
                "timestamp": _utc_now(),
            }

        better_tie = Solver()
        better_tie.set(timeout=req.z3TimeoutMs, random_seed=Z3_SEED)
        add_base(better_tie)
        better_tie.add(score_expr == RealVal(expected_score))
        better_tie.add(tie_expr > IntVal(expected_tie))
        tie_status = better_tie.check()
        if tie_status != unsat:
            return {
                "request_id": req.request_id,
                "z3_status": "SAT" if tie_status == sat else "TIMEOUT",
                "verification": "BETTER_TIE_NOT_REFUTED",
                "verified": False,
                "selected": expected,
                "proof_hash": "",
                "request_hash": "",
                "compute_ms": int((time.monotonic() - started) * 1000),
                "timestamp": _utc_now(),
            }

        request_payload = {
            "request_id": req.request_id,
            "candidates": candidates,
            "k": req.k,
            "minComposite": req.minComposite,
            "z3TimeoutMs": req.z3TimeoutMs,
            "seed": Z3_SEED,
        }
        request_hash = _sha256_json(request_payload)
        proof_payload = {
            "request_hash": request_hash,
            "z3_status": "SAT",
            "verification": "VERIFIED_EXACT_TOP_K",
            "verified": True,
            "selected": expected,
            "total_score_exact": expected_score,
            "score_optimality": "UNSAT_BETTER_SCORE",
            "tie_break_optimality": "UNSAT_BETTER_TIE",
        }
        proof_hash = _sha256_json(proof_payload)
        return {
            "request_id": req.request_id,
            **proof_payload,
            "proof_hash": proof_hash,
            "eligible_count": len(eligible),
            "selected_count": len(expected),
            "compute_ms": int((time.monotonic() - started) * 1000),
            "timestamp": _utc_now(),
            "audit": {
                "solver": "z3-native Real Optimize + independent Solver",
                "seed": Z3_SEED,
                "score_optimality": "UNSAT_BETTER_SCORE",
                "tie_break_optimality": "UNSAT_BETTER_TIE",
            },
        }
