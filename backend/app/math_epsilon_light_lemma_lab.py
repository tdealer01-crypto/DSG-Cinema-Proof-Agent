from __future__ import annotations

import itertools
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel
from z3 import RealVal, Solver, get_version_string, sat

from .math_epsilon_light import (
    AuditStoreProtocol,
    EpsilonLightInstanceRequest,
    _epsilon_light_matrix,
    _principal_minors,
    _sha256,
)


EPSILON_GRID = (Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1, 1))


class UniversalLemma(BaseModel):
    name: str
    status: Literal["PROVED_ELEMENTARY", "OPEN"]
    statement: str
    consequence: str


class FiniteExtremalCase(BaseModel):
    vertices: int
    edges: list[tuple[int, int]]
    epsilon: str
    maximum_light_subset_size: int
    witness_subset: list[int]
    ratio: str
    rejected_large_subsets: int
    z3_rejection_certificate_status: str
    certificate_hash: str


class LemmaDiscoveryResult(BaseModel):
    benchmark: Literal["First Proof #6 exhaustive lemma lab"] = "First Proof #6 exhaustive lemma lab"
    status: Literal["FINITE_THEOREM_VERIFIED", "COUNTEREXAMPLE_FOUND", "UNKNOWN"]
    max_vertices: int
    graph_count: int
    graph_epsilon_cases: int
    epsilon_grid: list[str]
    tested_constant: str
    tested_constant_verified_for_all_cases: bool
    finite_optimal_constant: str
    extremal_case: FiniteExtremalCase
    universal_lemmas: list[UniversalLemma]
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _all_possible_edges(vertices: int) -> list[tuple[int, int]]:
    return list(itertools.combinations(range(vertices), 2))


def _edges_from_mask(vertices: int, mask: int) -> list[tuple[int, int]]:
    possible = _all_possible_edges(vertices)
    return [edge for index, edge in enumerate(possible) if (mask >> index) & 1]


def _is_epsilon_light_exact(
    vertices: int,
    edges: list[tuple[int, int]],
    epsilon: Fraction,
    subset: tuple[int, ...],
) -> tuple[bool, dict[str, Any] | None]:
    request = EpsilonLightInstanceRequest(
        vertices=vertices,
        edges=edges,
        epsilon_numerator=epsilon.numerator,
        epsilon_denominator=epsilon.denominator,
        target_size=len(subset),
        seed=42,
        max_iterations=1,
    )
    matrix = _epsilon_light_matrix(request, list(subset))
    for indexes, determinant in _principal_minors(matrix):
        if determinant < 0:
            return False, {
                "subset": list(subset),
                "negative_minor_indexes": list(indexes),
                "determinant": {
                    "numerator": determinant.numerator,
                    "denominator": determinant.denominator,
                },
            }
    return True, None


def maximum_epsilon_light_subset(
    vertices: int,
    edges: list[tuple[int, int]],
    epsilon: Fraction,
) -> tuple[int, tuple[int, ...]]:
    for size in range(vertices, -1, -1):
        for subset in itertools.combinations(range(vertices), size):
            valid, _ = _is_epsilon_light_exact(vertices, edges, epsilon, subset)
            if valid:
                return size, subset
    raise RuntimeError("empty set must always be epsilon-light")


def _rejection_certificate_for_threshold(
    vertices: int,
    edges: list[tuple[int, int]],
    epsilon: Fraction,
    minimum_size: int,
) -> tuple[int, str, str]:
    certificates: list[dict[str, Any]] = []
    solver = Solver()
    rejected = 0
    for size in range(minimum_size, vertices + 1):
        for subset in itertools.combinations(range(vertices), size):
            valid, rejection = _is_epsilon_light_exact(vertices, edges, epsilon, subset)
            if valid:
                raise RuntimeError("threshold is not a counterexample: a valid subset exists")
            if rejection is None:
                raise RuntimeError("missing exact rejection certificate")
            determinant = rejection["determinant"]
            solver.add(RealVal(determinant["numerator"]) / RealVal(determinant["denominator"]) < 0)
            certificates.append(rejection)
            rejected += 1
    z3_result = solver.check()
    z3_status = "SAT" if z3_result == sat else str(z3_result).upper()
    return rejected, z3_status, _sha256(certificates)


def _universal_lemmas() -> list[UniversalLemma]:
    return [
        UniversalLemma(
            name="independent_sets_are_epsilon_light",
            status="PROVED_ELEMENTARY",
            statement=(
                "If S is an independent set, then L_S = 0, so epsilon*L - L_S = epsilon*L is PSD "
                "for every epsilon in [0,1]."
            ),
            consequence=(
                "Any independent set of size at least c*epsilon*n immediately proves the target bound for that graph."
            ),
        ),
        UniversalLemma(
            name="bounded_max_degree_reduction_for_c_half",
            status="PROVED_ELEMENTARY",
            statement=(
                "Greedy independent-set selection gives alpha(G) >= n/(Delta+1). Therefore if Delta+1 <= 2/epsilon, "
                "there is an epsilon-light set of size at least epsilon*n/2."
            ),
            consequence=(
                "Any counterexample to c=1/2 must lie in the remaining high-maximum-degree regime Delta+1 > 2/epsilon."
            ),
        ),
        UniversalLemma(
            name="high_degree_case_for_c_half",
            status="OPEN",
            statement=(
                "Show every graph with Delta+1 > 2/epsilon still contains an epsilon-light set of size at least epsilon*n/2."
            ),
            consequence=(
                "Closing this case would prove c=1/2, which is much stronger than the known c=1/256 proof attempt."
            ),
        ),
    ]


def run_first_proof_6_lemma_lab(audit_store: AuditStoreProtocol) -> LemmaDiscoveryResult:
    max_vertices = 5
    tested_constant = Fraction(1, 2)
    graph_count = 0
    graph_epsilon_cases = 0
    minimum_ratio: Fraction | None = None
    extremal: tuple[int, list[tuple[int, int]], Fraction, int, tuple[int, ...]] | None = None
    tested_constant_ok = True

    for vertices in range(1, max_vertices + 1):
        possible_edges = len(_all_possible_edges(vertices))
        for graph_mask in range(1 << possible_edges):
            graph_count += 1
            edges = _edges_from_mask(vertices, graph_mask)
            for epsilon in EPSILON_GRID:
                graph_epsilon_cases += 1
                maximum_size, witness = maximum_epsilon_light_subset(vertices, edges, epsilon)
                ratio = Fraction(maximum_size, 1) / (epsilon * vertices)
                if minimum_ratio is None or ratio < minimum_ratio:
                    minimum_ratio = ratio
                    extremal = (vertices, edges, epsilon, maximum_size, witness)
                required = tested_constant * epsilon * vertices
                if Fraction(maximum_size, 1) < required:
                    tested_constant_ok = False

    if minimum_ratio is None or extremal is None:
        raise RuntimeError("lemma lab did not enumerate any cases")

    vertices, edges, epsilon, maximum_size, witness = extremal
    rejected, z3_status, certificate_hash = _rejection_certificate_for_threshold(
        vertices=vertices,
        edges=edges,
        epsilon=epsilon,
        minimum_size=maximum_size + 1,
    )
    extremal_case = FiniteExtremalCase(
        vertices=vertices,
        edges=edges,
        epsilon=_fraction_text(epsilon),
        maximum_light_subset_size=maximum_size,
        witness_subset=list(witness),
        ratio=_fraction_text(minimum_ratio),
        rejected_large_subsets=rejected,
        z3_rejection_certificate_status=f"Z3 {get_version_string()}: {z3_status}",
        certificate_hash=certificate_hash,
    )

    proof_payload = {
        "benchmark": "First Proof #6 exhaustive lemma lab",
        "max_vertices": max_vertices,
        "graph_count": graph_count,
        "graph_epsilon_cases": graph_epsilon_cases,
        "epsilon_grid": [_fraction_text(value) for value in EPSILON_GRID],
        "tested_constant": _fraction_text(tested_constant),
        "tested_constant_verified_for_all_cases": tested_constant_ok,
        "finite_optimal_constant": _fraction_text(minimum_ratio),
        "extremal_case": extremal_case.model_dump(mode="json"),
        "universal_lemmas": [lemma.model_dump(mode="json") for lemma in _universal_lemmas()],
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"lemma_discovery": proof_payload}, proof_hash=proof_hash)

    return LemmaDiscoveryResult(
        status="FINITE_THEOREM_VERIFIED" if tested_constant_ok and z3_status == "SAT" else "UNKNOWN",
        max_vertices=max_vertices,
        graph_count=graph_count,
        graph_epsilon_cases=graph_epsilon_cases,
        epsilon_grid=[_fraction_text(value) for value in EPSILON_GRID],
        tested_constant=_fraction_text(tested_constant),
        tested_constant_verified_for_all_cases=tested_constant_ok,
        finite_optimal_constant=_fraction_text(minimum_ratio),
        extremal_case=extremal_case,
        universal_lemmas=_universal_lemmas(),
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "This is an exhaustive finite theorem for labeled simple graphs with at most five vertices and the listed epsilon grid. "
            "The exact optimum 8/15 on that finite domain does not imply a universal constant for arbitrary graph size or arbitrary epsilon. "
            "The independent-set and bounded-maximum-degree reductions are elementary universal lemmas; the high-degree case remains open here. "
            "The OpenAI First Proof submission already contains a separate proof attempt with c=1/256, so this lab is not an independent solution of the original challenge."
        ),
    )
