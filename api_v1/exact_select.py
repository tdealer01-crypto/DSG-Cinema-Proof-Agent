"""Bounded deterministic exact-decimal selection for the Cinema MCP surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field, field_validator, model_validator

from .canonical import canonical_json
from .models import Strict

DECIMAL_PATTERN = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
DECIMAL_RE = re.compile(DECIMAL_PATTERN)
EXP_RE = re.compile(r"[eE]([+-]?\d+)$")
MAX_RAW_LENGTH = 240
MAX_Z3_EXPONENT = 1000
MAX_CANDIDATES = 24
MAX_K = 12
Z3_TIMEOUT_MS = 30000


class ExactCandidateArgs(Strict):
    id: str = Field(min_length=1, max_length=256)
    composite: str = Field(min_length=1, max_length=MAX_RAW_LENGTH, pattern=DECIMAL_PATTERN)

    @field_validator("composite")
    @classmethod
    def bounded_exponent(cls, value: str) -> str:
        _validate_exponent(value)
        return value


class ExactSelectArgs(Strict):
    candidates: list[ExactCandidateArgs] = Field(min_length=1, max_length=MAX_CANDIDATES)
    k: int = Field(default=12, ge=1, le=MAX_K)
    minComposite: str = Field(default="0", min_length=1, max_length=MAX_RAW_LENGTH, pattern=DECIMAL_PATTERN)
    useZ3: bool = False

    @field_validator("minComposite")
    @classmethod
    def bounded_minimum_exponent(cls, value: str) -> str:
        _validate_exponent(value)
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [candidate.id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique")
        return self


def _validate_exponent(raw: str) -> None:
    match = EXP_RE.search(raw)
    exponent = int(match.group(1)) if match else 0
    if abs(exponent) > MAX_Z3_EXPONENT:
        raise ValueError(f"absolute decimal exponent must be <= {MAX_Z3_EXPONENT}")


def _decimal(raw: str) -> Decimal:
    if len(raw) > MAX_RAW_LENGTH or not DECIMAL_RE.fullmatch(raw):
        raise ValueError("invalid exact decimal")
    _validate_exponent(raw)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid exact decimal") from exc


def _normalised(args: ExactSelectArgs) -> list[dict[str, str]]:
    return [{"id": candidate.id, "composite": candidate.composite} for candidate in args.candidates]


def _eligible_and_selected(args: ExactSelectArgs):
    minimum = _decimal(args.minComposite)
    candidates = _normalised(args)
    eligible = [candidate for candidate in candidates if _decimal(candidate["composite"]) >= minimum]
    eligible.sort(key=lambda candidate: (-_decimal(candidate["composite"]), candidate["id"]))
    return candidates, eligible, eligible[: args.k]


def _evidence_hash(candidates: list[dict[str, str]], k: int, minimum: str) -> str:
    payload = {"candidates": candidates, "k": k, "minComposite": minimum}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _blocked(reason: str, evidence_hash: str, **details: Any) -> dict[str, Any]:
    return {
        "success": False,
        "status": "BLOCKED",
        "reason": reason,
        "evidenceHash": evidence_hash,
        **details,
    }


async def exact_select(args: ExactSelectArgs) -> dict[str, Any]:
    candidates, eligible, expected = _eligible_and_selected(args)
    evidence_hash = _evidence_hash(candidates, args.k, args.minComposite)

    if not args.useZ3:
        return {
            "success": True,
            "status": "PASSED",
            "mode": "no-optimization-needed" if len(eligible) <= args.k else "exact-sort",
            "solver": "none",
            "totalInput": len(candidates),
            "eligibleCount": len(eligible),
            "k": args.k,
            "selectedCount": len(expected),
            "selected": expected,
            "verification": "deterministic Python Decimal comparator with stable ID tie-break",
            "evidenceHash": evidence_hash,
        }

    if len(eligible) < args.k:
        return _blocked(
            "INSUFFICIENT_CANDIDATES_FOR_EXACT_K",
            evidence_hash,
            required=args.k,
            actual=len(eligible),
        )

    import cinema_main

    request_id = f"exact-{evidence_hash[:58]}"
    payload = {
        "request_id": request_id,
        "candidates": candidates,
        "k": args.k,
        "minComposite": args.minComposite,
        "z3TimeoutMs": Z3_TIMEOUT_MS,
    }
    try:
        status_code, body = await cinema_main.z3_request("POST", "/exact-select", payload)
    except Exception:
        return _blocked("Z3_BACKEND_UNAVAILABLE", evidence_hash)

    if status_code != 200:
        return _blocked("Z3_BACKEND_HTTP_ERROR", evidence_hash, httpStatus=status_code)
    if not isinstance(body, dict):
        return _blocked("Z3_INVALID_RESPONSE", evidence_hash)
    if body.get("verified") is not True or body.get("verification") != "VERIFIED_EXACT_TOP_K":
        return _blocked(
            "Z3_NOT_VERIFIED",
            evidence_hash,
            z3Status=body.get("z3_status"),
            verification=body.get("verification"),
        )
    if body.get("z3_status") != "SAT":
        return _blocked("Z3_NOT_SAT", evidence_hash, z3Status=body.get("z3_status"))
    if body.get("selected") != expected:
        return _blocked(
            "Z3_DETERMINISTIC_RESULT_MISMATCH",
            evidence_hash,
            expected=expected,
            actual=body.get("selected"),
        )

    request_hash = body.get("request_hash")
    proof_hash = body.get("proof_hash")
    audit = body.get("audit")
    if not isinstance(request_hash, str) or len(request_hash) != 64:
        return _blocked("Z3_INVALID_REQUEST_HASH", evidence_hash)
    if not isinstance(proof_hash, str) or len(proof_hash) != 64:
        return _blocked("Z3_INVALID_PROOF_HASH", evidence_hash)
    if not isinstance(audit, dict) or not isinstance(audit.get("seed"), int):
        return _blocked("Z3_INVALID_AUDIT", evidence_hash)

    canonical_request = {
        **payload,
        "seed": audit["seed"],
    }
    if _sha256_json(canonical_request) != request_hash:
        return _blocked("Z3_REQUEST_HASH_MISMATCH", evidence_hash)

    proof_payload = {
        "request_hash": request_hash,
        "z3_status": "SAT",
        "verification": "VERIFIED_EXACT_TOP_K",
        "verified": True,
        "selected": expected,
        "total_score_exact": body.get("total_score_exact"),
        "score_optimality": "UNSAT_BETTER_SCORE",
        "tie_break_optimality": "UNSAT_BETTER_TIE",
    }
    if _sha256_json(proof_payload) != proof_hash:
        return _blocked("Z3_PROOF_HASH_MISMATCH", evidence_hash)
    if audit.get("score_optimality") != "UNSAT_BETTER_SCORE":
        return _blocked("Z3_SCORE_PROOF_MISSING", evidence_hash)
    if audit.get("tie_break_optimality") != "UNSAT_BETTER_TIE":
        return _blocked("Z3_TIE_PROOF_MISSING", evidence_hash)

    return {
        "success": True,
        "status": "PASSED",
        "mode": "verified-exact",
        "solver": "z3-native Real Optimize + independent optimality proof",
        "solverResult": "sat",
        "totalInput": len(candidates),
        "eligibleCount": len(eligible),
        "k": args.k,
        "selectedCount": len(expected),
        "selected": expected,
        "verification": "native Z3 exact-real top-k matched deterministic Decimal comparator",
        "evidenceHash": evidence_hash,
        "z3ProofHash": proof_hash,
        "z3RequestHash": request_hash,
    }


def install_mcp_tool() -> None:
    from . import mcp

    if "dsg_exact_select" in mcp._BY_NAME:
        return

    class ExactSelectTool(mcp._Tool):
        def definition(self) -> dict[str, Any]:
            definition = super().definition()
            definition.update(
                {
                    "title": "DSG Exact Select",
                    "outputSchema": {
                        "type": "object",
                        "required": ["success", "status"],
                        "properties": {
                            "success": {"type": "boolean"},
                            "status": {"enum": ["PASSED", "BLOCKED"]},
                            "reason": {"type": "string"},
                            "mode": {"type": "string"},
                            "solver": {"type": "string"},
                            "selectedCount": {"type": "integer"},
                            "selected": {"type": "array"},
                            "evidenceHash": {"type": "string"},
                            "z3ProofHash": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                    "annotations": {
                        "readOnlyHint": True,
                        "openWorldHint": False,
                        "destructiveHint": False,
                        "idempotentHint": True,
                    },
                }
            )
            return definition

    tool = ExactSelectTool(
        "dsg_exact_select",
        "Deterministically select top-k from up to 24 exact decimal candidates. "
        "useZ3=false uses Python Decimal exact sorting; useZ3=true requires a native "
        "Z3 exact-real optimality proof and fails closed on any mismatch or backend failure.",
        ExactSelectArgs,
        exact_select,
    )
    mcp.TOOLS = (*mcp.TOOLS, tool)
    mcp._BY_NAME[tool.name] = tool
