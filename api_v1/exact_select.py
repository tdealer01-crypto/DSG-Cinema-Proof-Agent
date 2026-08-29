"""Bounded deterministic exact-decimal selection and DSG Sheet MCP surface."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

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
SHEET_SIZE = 100


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
            raise PydanticCustomError(
                "duplicate_candidate_id",
                "candidate ids must be unique",
            )
        return self


class SheetCellArgs(Strict):
    cell_id: int = Field(ge=1, le=SHEET_SIZE)


class SheetComposeArgs(Strict):
    goal: str = Field(min_length=1, max_length=1024)
    required_capabilities: list[str] = Field(min_length=1, max_length=64)


def _validate_exponent(raw: str) -> None:
    match = EXP_RE.search(raw)
    exponent = int(match.group(1)) if match else 0
    if abs(exponent) > MAX_Z3_EXPONENT:
        raise PydanticCustomError(
            "z3_exponent_limit",
            "absolute decimal exponent must be <= {max_exponent}",
            {"max_exponent": MAX_Z3_EXPONENT},
        )


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


# DSG Sheet is additive metadata over the existing system. It does not relocate,
# copy or re-host any existing DSG runtime. A provider cell only identifies a
# capability that DSG may call through that provider's existing boundary.
ASSIGNED_CELLS: dict[int, dict[str, Any]] = {
    1: {"slug": "dsg-core", "name": "DSG Core", "kind": "core", "provider": "dsg", "capabilities": ["runtime"]},
    2: {"slug": "governance", "name": "Governance", "kind": "core", "provider": "dsg", "capabilities": ["governance", "policy", "permission"]},
    3: {"slug": "execution", "name": "Execution", "kind": "core", "provider": "dsg", "capabilities": ["execution"]},
    4: {"slug": "z3", "name": "Z3", "kind": "core", "provider": "dsg", "capabilities": ["exact-verification", "solver"]},
    5: {"slug": "evidence", "name": "Evidence", "kind": "core", "provider": "dsg", "capabilities": ["evidence"]},
    6: {"slug": "proof", "name": "Proof", "kind": "core", "provider": "dsg", "capabilities": ["proof"]},
    7: {"slug": "replay", "name": "Replay", "kind": "core", "provider": "dsg", "capabilities": ["replay"]},
    8: {"slug": "identity", "name": "Identity", "kind": "core", "provider": "dsg", "capabilities": ["identity"]},
    9: {"slug": "connection-broker", "name": "Connection Broker", "kind": "core", "provider": "dsg", "capabilities": ["connection", "credential-broker"]},
    10: {"slug": "mcp", "name": "MCP Surface", "kind": "interface", "provider": "dsg", "capabilities": ["mcp"]},
    11: {"slug": "neon-postgres", "name": "Neon Postgres", "kind": "provider", "provider": "neon", "capabilities": ["memory", "postgres", "state"]},
    12: {"slug": "github", "name": "GitHub", "kind": "provider", "provider": "github", "capabilities": ["source", "repository", "ci"]},
    13: {"slug": "stripe", "name": "Stripe", "kind": "provider", "provider": "stripe", "capabilities": ["payment", "billing", "commerce"]},
    14: {"slug": "azure-devops", "name": "Azure DevOps", "kind": "provider", "provider": "microsoft", "capabilities": ["devops", "pipeline", "deployment"]},
    15: {"slug": "aws-cdk", "name": "AWS CDK", "kind": "provider", "provider": "aws", "capabilities": ["infrastructure", "cloud", "deployment"]},
    16: {"slug": "nvidia", "name": "NVIDIA", "kind": "provider", "provider": "nvidia", "capabilities": ["gpu", "inference"]},
    17: {"slug": "openai", "name": "OpenAI Developers", "kind": "provider", "provider": "openai", "capabilities": ["model", "agent", "inference"]},
    18: {"slug": "activecampaign", "name": "ActiveCampaign", "kind": "provider", "provider": "activecampaign", "capabilities": ["crm", "marketing"]},
    19: {"slug": "appdeploy", "name": "AppDeploy", "kind": "provider", "provider": "appdeploy", "capabilities": ["app-delivery", "deployment"]},
    20: {"slug": "marketplace", "name": "Marketplace", "kind": "surface", "provider": "dsg", "capabilities": ["storefront", "distribution"]},
    21: {"slug": "supabase", "name": "Supabase", "kind": "provider", "provider": "supabase", "capabilities": ["database", "auth", "storage", "realtime"]},
}


def _sheet_cell(cell_id: int) -> dict[str, Any]:
    assigned = ASSIGNED_CELLS.get(cell_id)
    if assigned is None:
        return {
            "cell_id": cell_id,
            "occupied": False,
            "slug": None,
            "name": None,
            "kind": "empty",
            "provider": None,
            "capabilities": [],
        }
    return {"cell_id": cell_id, "occupied": True, **assigned}


def sheet_snapshot() -> dict[str, Any]:
    cells = [_sheet_cell(cell_id) for cell_id in range(1, SHEET_SIZE + 1)]
    occupied = len(ASSIGNED_CELLS)
    return {
        "status": "PASSED",
        "sheet_size": SHEET_SIZE,
        "occupied_count": occupied,
        "empty_count": SHEET_SIZE - occupied,
        "cells": cells,
    }


def compose_sheet(goal: str, required_capabilities: list[str]) -> dict[str, Any]:
    required = sorted({value.strip().lower() for value in required_capabilities if value.strip()})
    if not required:
        return {
            "status": "BLOCKED",
            "reason": "NO_CAPABILITIES_REQUESTED",
            "goal": goal,
            "required_capabilities": [],
            "selected_cells": [],
        }

    by_capability: dict[str, list[int]] = {}
    for cell_id, cell in ASSIGNED_CELLS.items():
        for capability in cell["capabilities"]:
            by_capability.setdefault(capability, []).append(cell_id)

    selected: set[int] = set()
    resolution: list[dict[str, Any]] = []
    missing: list[str] = []
    for capability in required:
        choices = sorted(by_capability.get(capability, []))
        if not choices:
            missing.append(capability)
            resolution.append({"capability": capability, "status": "MISSING", "cell_id": None})
            continue
        cell_id = choices[0]
        selected.add(cell_id)
        resolution.append({"capability": capability, "status": "RESOLVED", "cell_id": cell_id})

    selected_cells = [_sheet_cell(cell_id) for cell_id in sorted(selected)]
    if missing:
        return {
            "status": "BLOCKED",
            "reason": "MISSING_CAPABILITY",
            "goal": goal,
            "required_capabilities": required,
            "missing_capabilities": missing,
            "resolution": resolution,
            "selected_cells": selected_cells,
        }
    return {
        "status": "PASSED",
        "goal": goal,
        "required_capabilities": required,
        "resolution": resolution,
        "selected_cells": selected_cells,
    }


def _validate_sheet_contract() -> None:
    if SHEET_SIZE != 100:
        raise RuntimeError("DSG Sheet size must remain exactly 100")
    if not ASSIGNED_CELLS:
        raise RuntimeError("DSG Sheet requires at least one assigned cell")
    if min(ASSIGNED_CELLS) < 1 or max(ASSIGNED_CELLS) > SHEET_SIZE:
        raise RuntimeError("DSG Sheet assigned cell is outside 1..100")
    slugs = [cell["slug"] for cell in ASSIGNED_CELLS.values()]
    if len(slugs) != len(set(slugs)):
        raise RuntimeError("DSG Sheet slugs must be unique")
    if _sheet_cell(11)["slug"] != "neon-postgres":
        raise RuntimeError("DSG Sheet memory cell 11 must remain Neon Postgres")
    known = compose_sheet("contract-check", ["memory", "payment", "source"])
    if known.get("status") != "PASSED" or [c["cell_id"] for c in known["selected_cells"]] != [11, 12, 13]:
        raise RuntimeError("DSG Sheet deterministic composition contract failed")
    missing = compose_sheet("contract-check", ["teleportation"])
    if missing.get("status") != "BLOCKED" or missing.get("reason") != "MISSING_CAPABILITY":
        raise RuntimeError("DSG Sheet fail-closed contract failed")


async def _sheet_list(_: Any) -> dict[str, Any]:
    return sheet_snapshot()


async def _sheet_get(args: SheetCellArgs) -> dict[str, Any]:
    return {"status": "PASSED", "cell": _sheet_cell(args.cell_id)}


async def _sheet_compose(args: SheetComposeArgs) -> dict[str, Any]:
    return compose_sheet(args.goal, args.required_capabilities)


def install_mcp_tool() -> None:
    from . import mcp

    if "dsg_exact_select" in mcp._BY_NAME:
        return

    _validate_sheet_contract()

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

    tools = (
        ExactSelectTool(
            "dsg_exact_select",
            "Deterministically select top-k from up to 24 exact decimal candidates. "
            "useZ3=false uses Python Decimal exact sorting; useZ3=true requires a native "
            "Z3 exact-real optimality proof and fails closed on any mismatch or backend failure.",
            ExactSelectArgs,
            exact_select,
        ),
        mcp._Tool(
            "dsg_sheet_list",
            "Read the DSG Sheet: exactly 100 stable capability cells; empty cells remain explicit and ready for future providers.",
            None,
            _sheet_list,
        ),
        mcp._Tool(
            "dsg_sheet_get",
            "Read one stable DSG Sheet cell by number 1..100. This does not move or copy the provider system.",
            SheetCellArgs,
            _sheet_get,
        ),
        mcp._Tool(
            "dsg_sheet_compose",
            "Resolve requested capabilities to existing DSG Sheet cells. Missing capability fails closed instead of inventing a provider.",
            SheetComposeArgs,
            _sheet_compose,
        ),
    )
    for tool in tools:
        mcp.TOOLS = (*mcp.TOOLS, tool)
        mcp._BY_NAME[tool.name] = tool

    if not getattr(mcp, "_dsg_exact_select_error_wrapper_installed", False):
        original_call_tool = mcp._call_tool

        async def exact_aware_call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = await original_call_tool(name, arguments)
            if name in {"dsg_exact_select", "dsg_sheet_compose"} and isinstance(result, dict):
                structured = result.get("structuredContent")
                if isinstance(structured, dict) and structured.get("status") == "BLOCKED":
                    result["isError"] = True
            return result

        mcp._call_tool = exact_aware_call_tool
        mcp._dsg_exact_select_error_wrapper_installed = True
