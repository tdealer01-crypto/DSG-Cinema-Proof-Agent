from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from z3 import Real, Solver, unsat

from .audit import canonical_json
from .math_epsilon_light import AuditStoreProtocol, _sha256


OFFICIAL_SOLUTION_URL = "https://cowles.yale.edu/sites/default/files/2026-04/d2511.pdf"
LEAN_PROOF_URL = "https://github.com/frenzymath/Archon-FirstProof-Results/blob/main/FirstProof/FirstProof6/Problem6.lean"
OPENAI_ATTEMPT_URL = "https://cdn.openai.com/pdf/26177a73-3b75-4828-8c91-e8f1cf27aaa0/oai_first_proof.pdf"


class ScalarProofObligation(BaseModel):
    name: str
    status: Literal["UNSAT_NEGATION"]
    statement: str


class FirstProof6ClosureResult(BaseModel):
    benchmark: Literal["First Proof #6 theorem closure"] = "First Proof #6 theorem closure"
    status: Literal["REFERENCE_THEOREM_CLOSED", "VERIFICATION_FAILED"]
    answer: Literal["YES"] = "YES"
    universal_constant_c: str
    graph_scope: str
    epsilon_scope: str
    official_solution: str
    independent_formal_artifact: str
    prior_openai_attempt: str
    scalar_obligations: list[ScalarProofObligation]
    proof_steps: list[str]
    evidence_level: str
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def _check_unsat(name: str, statement: str, constraints: list, negated_goal) -> ScalarProofObligation:
    solver = Solver()
    solver.add(*constraints)
    solver.add(negated_goal)
    result = solver.check()
    if result != unsat:
        raise RuntimeError(f"scalar proof obligation {name} was not proved: {result}")
    return ScalarProofObligation(name=name, status="UNSAT_NEGATION", statement=statement)


def verify_official_scalar_spine() -> list[ScalarProofObligation]:
    """Machine-check the scalar inequalities used by the official c=1/42 proof.

    The matrix-analysis lemmas remain mathematical lemmas from the cited proof; this function
    deliberately checks only the arithmetic spine and does not mislabel Z3 arithmetic as a
    formalization of the full matrix theorem.
    """

    obligations: list[ScalarProofObligation] = []

    # Write q = epsilon*n.  In the official proof sigma=floor(q/42), so 42*sigma <= q.
    q = Real("q")
    n = Real("n")
    sigma = Real("sigma")
    base = [n > 0, q > 0, q < n, sigma >= 0, 42 * sigma <= q]

    obligations.append(
        _check_unsat(
            "initial_barrier_budget",
            "sigma/(epsilon/2) <= n/21 follows from sigma <= epsilon*n/42",
            base,
            42 * sigma > q,
        )
    )

    # u0=epsilon/2 and delta=21/n.  After sigma additions:
    # u0 + sigma*delta <= epsilon is again equivalent to 42*sigma <= epsilon*n.
    obligations.append(
        _check_unsat(
            "final_barrier_below_epsilon",
            "epsilon/2 + sigma*(21/n) <= epsilon",
            base,
            42 * sigma > q,
        )
    )

    # Since epsilon<1, q=epsilon*n<n. Combined with 42*sigma<=q gives
    # n-sigma > 41n/42, which supplies enough unchosen vertices for the averaging step.
    obligations.append(
        _check_unsat(
            "remaining_vertex_mass",
            "n - sigma > 41*n/42",
            base,
            42 * (n - sigma) <= 41 * n,
        )
    )

    # Lemma 2.5 obtains sum U(S,t) <= 5/delta + 5*phi with
    # delta=21/n and phi=n/21, hence <=10n/21. More than 41n/42 candidates
    # remain, so twice this sum divided by the candidate count is < 1.
    remaining = Real("remaining")
    sum_u = Real("sum_u")
    average_constraints = [n > 0, 42 * remaining > 41 * n, sum_u <= 10 * n / 21, sum_u >= 0]
    obligations.append(
        _check_unsat(
            "barrier_good_vertex_exists",
            "2*sumU/(n-|S|) < 1 under the official 21/42 constants",
            average_constraints,
            2 * sum_u >= remaining,
        )
    )

    # floor(x)+1 > x yields the requested cardinality after sigma greedy additions
    # starting from one vertex. Encode the floor interval directly.
    x = Real("x")
    obligations.append(
        _check_unsat(
            "cardinality_lower_bound",
            "sigma=floor(epsilon*n/42) implies sigma+1 > epsilon*n/42",
            [sigma <= x, x < sigma + 1],
            sigma + 1 <= x,
        )
    )

    return obligations


def close_first_proof_6(audit_store: AuditStoreProtocol) -> FirstProof6ClosureResult:
    obligations = verify_official_scalar_spine()
    proof_steps = [
        "Normalize every induced-edge Laplacian by the Moore-Penrose square root of the full graph Laplacian, reducing epsilon-lightness to an operator-norm bound.",
        "Use effective-resistance leverage scores to control the boundary cost of adding a vertex to the growing set.",
        "Track a truncated one-sided BSS barrier potential over the largest sigma eigenvalues of the normalized induced Laplacian.",
        "At each greedy step, intersect the leverage-good majority with the barrier-good half to obtain a vertex preserving both invariants.",
        "Iterate sigma=floor(epsilon*n/42) times from a singleton; the barrier stays below epsilon while the final set has more than epsilon*n/42 vertices.",
    ]
    proof_payload = {
        "answer": "YES",
        "constant": "1/42",
        "scope": "every finite weighted undirected graph; 0 < epsilon < 1",
        "official_solution": OFFICIAL_SOLUTION_URL,
        "lean_artifact": LEAN_PROOF_URL,
        "scalar_obligations": [item.model_dump(mode="json") for item in obligations],
        "proof_steps": proof_steps,
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"first_proof_6_closure": proof_payload}, proof_hash=proof_hash)

    return FirstProof6ClosureResult(
        status="REFERENCE_THEOREM_CLOSED",
        universal_constant_c="1/42",
        graph_scope="Every finite weighted undirected graph (hence every simple graph).",
        epsilon_scope="0 < epsilon < 1; endpoint/degenerate cases are immediate from the definition.",
        official_solution=OFFICIAL_SOLUTION_URL,
        independent_formal_artifact=LEAN_PROOF_URL,
        prior_openai_attempt=OPENAI_ATTEMPT_URL,
        scalar_obligations=obligations,
        proof_steps=proof_steps,
        evidence_level=(
            "Official human reference proof + DSG Z3 checks of the scalar constant arithmetic + "
            "external Lean proof artifact reference. DSG does not claim independent discovery or "
            "that the external Lean file was recompiled inside this repository."
        ),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "Problem #6 is mathematically answered YES by the cited official solution with c=1/42. "
            "This DSG artifact closes the verification/provenance workflow around that known theorem; "
            "it is not a claim that DSG independently discovered the theorem. Z3 checks only the scalar "
            "inequalities encoded here, while the matrix-analysis argument is supplied by the cited proof."
        ),
    )
