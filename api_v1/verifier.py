"""The exact-proof step: encode the decision, then make Z3 prove it.

DSG derives the ALLOW / REVIEW / BLOCK target from raw records (alignment,
constraints, evidence, replay). This module encodes that target as a bounded
3-variable QUBO, asks the server-side Z3 verifier for a global-optimum proof,
and refuses the result unless the returned witness is exactly the decision DSG
derived. There is no path here that returns a verdict without a proof: if Z3 is
unreachable, the request fails closed.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

Decision = Literal["ALLOW", "REVIEW", "BLOCK"]

WITNESS_TO_DECISION: dict[tuple[int, ...], Decision] = {
    (1, 0, 0): "ALLOW",
    (0, 1, 0): "REVIEW",
    (0, 0, 1): "BLOCK",
}

_ONE_HOT_PENALTY = 100
_TARGET_COSTS: dict[str, list[int]] = {
    "ALLOW": [0, 30, 60],
    "REVIEW": [40, 0, 40],
    "BLOCK": [60, 30, 0],
}


class ProofUnavailable(RuntimeError):
    """Raised when no exact proof could be obtained. Never downgraded to a pass."""

    def __init__(self, message: str, code: str = "VERIFICATION_NOT_PROVED") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def decision_qubo(target: str) -> tuple[list[int], list[list[int]]]:
    """Three binary variables [ALLOW, REVIEW, BLOCK] under a one-hot penalty."""
    costs = _TARGET_COSTS[target]
    linear = [cost - _ONE_HOT_PENALTY for cost in costs]
    pair_penalty = 2 * _ONE_HOT_PENALTY
    quadratic = [
        [0, 1, pair_penalty],
        [0, 2, pair_penalty],
        [1, 2, pair_penalty],
    ]
    return linear, quadratic


def decision_from_witness(witness: Any) -> Optional[Decision]:
    if not isinstance(witness, list) or len(witness) != 3:
        return None
    try:
        key = tuple(int(item) for item in witness)
    except (TypeError, ValueError):
        return None
    return WITNESS_TO_DECISION.get(key)


def validate_exact_proof(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ProofUnavailable("the Z3 verifier returned non-object JSON")
    if body.get("verified") is not True:
        raise ProofUnavailable("the Z3 verifier did not report a verified result")
    if body.get("verification") != "VERIFIED_GLOBAL_OPTIMUM":
        raise ProofUnavailable("the Z3 verifier did not prove global optimality")
    for field in ("proof_hash", "request_hash"):
        value = body.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise ProofUnavailable(f"the Z3 verifier returned an invalid {field}")
    return body


async def _solve(payload: dict[str, Any]) -> tuple[int, Any]:
    # Resolved at call time so the deployed adapter stays the single owner of the
    # Z3 credential, and so a test that substitutes the transport is honoured.
    import cinema_main

    return await cinema_main.z3_request("POST", "/solve", payload)


async def prove_decision(
    target: Decision,
    request_id: str,
    preset_name: str = "dsg-one-v1",
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    """Return an exact Z3 proof whose witness is the decision DSG derived."""
    linear, quadratic = decision_qubo(target)
    payload = {
        "request_id": request_id[:64],
        "preset_name": preset_name,
        "problem_type": "qubo",
        "linear": linear,
        "quadratic": quadratic,
        "proveOptimality": True,
        "z3TimeoutMs": timeout_ms,
    }

    try:
        status_code, body = await _solve(payload)
    except ProofUnavailable:
        raise
    except Exception as exc:  # transport failures surface as an unavailable backend
        raise ProofUnavailable(
            "the Z3 verification backend could not be reached",
            "BACKEND_UNAVAILABLE",
        ) from exc

    if status_code != 200:
        raise ProofUnavailable(
            f"the Z3 verification backend returned HTTP {status_code}",
            "BACKEND_UNAVAILABLE",
        )

    proof = validate_exact_proof(body)
    proved = decision_from_witness(proof.get("witness"))
    if proved is None:
        raise ProofUnavailable("the Z3 verifier returned an invalid decision witness")
    if proved != target:
        raise ProofUnavailable(
            f"the proved decision {proved} does not match the derived decision {target}"
        )
    return proof
