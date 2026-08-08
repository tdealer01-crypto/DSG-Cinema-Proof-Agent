from __future__ import annotations

import itertools
from fractions import Fraction
from typing import Literal, Any

from pydantic import BaseModel
from z3 import RealVal, Solver, get_version_string, sat

from .audit import canonical_json
from .hybrid_solver import compute_qubo_energy, qubo_to_ising
from .math_epsilon_light import (
    AuditStoreProtocol,
    EpsilonLightCandidate,
    EpsilonLightInstanceRequest,
    _build_subset_qubo,
    _epsilon_light_matrix,
    _principal_minors,
    _sha256,
    search_epsilon_light_candidate,
    verify_epsilon_light_candidate,
)


class EpsilonLightSweepCase(BaseModel):
    graph_family: str
    vertices: int
    edges: int
    epsilon: str
    constant_c: str
    target_size: int
    status: Literal["WITNESS_VERIFIED", "FINITE_COUNTEREXAMPLE", "UNKNOWN"]
    discovery_method: Literal["ISING", "EXHAUSTIVE", "NONE"]
    witness_subset: list[int]
    subsets_examined: int
    z3_status: str
    certificate_hash: str
    proof_hash: str


class EpsilonLightConstantSummary(BaseModel):
    constant_c: str
    cases: int
    verified_cases: int
    counterexamples: int
    unknown_cases: int


class EpsilonLightSweepResult(BaseModel):
    benchmark: Literal["First Proof #6 finite family sweep"] = "First Proof #6 finite family sweep"
    status: Literal["FINITE_SWEEP_COMPLETE", "FINITE_SWEEP_HAS_UNKNOWN"]
    total_cases: int
    verified_cases: int
    counterexamples: int
    unknown_cases: int
    strongest_tested_constant_with_all_cases_verified: str | None
    constant_summaries: list[EpsilonLightConstantSummary]
    cases: list[EpsilonLightSweepCase]
    proof_hash: str
    audit_event_hash: str
    truth_boundary: str


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _ceil_fraction(value: Fraction) -> int:
    return (value.numerator + value.denominator - 1) // value.denominator


def _complete_edges(vertices: int) -> list[tuple[int, int]]:
    return list(itertools.combinations(range(vertices), 2))


def _path_edges(vertices: int) -> list[tuple[int, int]]:
    return [(vertex, vertex + 1) for vertex in range(vertices - 1)]


def _cycle_edges(vertices: int) -> list[tuple[int, int]]:
    return _path_edges(vertices) + [(0, vertices - 1)]


def _star_edges(vertices: int) -> list[tuple[int, int]]:
    return [(0, vertex) for vertex in range(1, vertices)]


def _complete_bipartite_edges(left: int, right: int) -> list[tuple[int, int]]:
    return [(u, left + v) for u in range(left) for v in range(right)]


def default_graph_families() -> list[tuple[str, int, list[tuple[int, int]]]]:
    vertices = 6
    return [
        ("complete_K6", vertices, _complete_edges(vertices)),
        ("path_P6", vertices, _path_edges(vertices)),
        ("cycle_C6", vertices, _cycle_edges(vertices)),
        ("star_S6", vertices, _star_edges(vertices)),
        ("complete_bipartite_K3_3", vertices, _complete_bipartite_edges(3, 3)),
    ]


def _candidate_for_exact_subset(
    request: EpsilonLightInstanceRequest,
    subset: tuple[int, ...],
) -> EpsilonLightCandidate:
    q = _build_subset_qubo(request)
    j_matrix, h_vector, offset = qubo_to_ising(q)
    state = [1 if vertex in subset else 0 for vertex in range(request.vertices)]
    selected = set(subset)
    internal_edges = sum(1 for u, v in request.edges if u in selected and v in selected)
    qubo_matrix_hash = _sha256(q)
    ising_model_hash = _sha256({"J": j_matrix, "h": h_vector, "offset": offset})
    trajectory_hash = _sha256({"method": "EXHAUSTIVE", "subset": list(subset)})
    qubo_energy = compute_qubo_energy(state, q)
    candidate_hash = _sha256(
        {
            "method": "EXHAUSTIVE",
            "subset": list(subset),
            "qubo_energy": qubo_energy,
            "qubo_matrix_hash": qubo_matrix_hash,
            "ising_model_hash": ising_model_hash,
            "trajectory_hash": trajectory_hash,
        }
    )
    return EpsilonLightCandidate(
        subset=list(subset),
        subset_size=len(subset),
        internal_edges=internal_edges,
        seed=request.seed,
        iterations=0,
        qubo_energy=qubo_energy,
        qubo_matrix_hash=qubo_matrix_hash,
        ising_model_hash=ising_model_hash,
        trajectory_hash=trajectory_hash,
        candidate_hash=candidate_hash,
    )


def _exact_subset_rejection(
    request: EpsilonLightInstanceRequest,
    subset: tuple[int, ...],
) -> tuple[bool, dict[str, Any] | None]:
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


def solve_sweep_case(
    graph_family: str,
    vertices: int,
    edges: list[tuple[int, int]],
    epsilon: Fraction,
    constant_c: Fraction,
    seed: int = 42,
) -> EpsilonLightSweepCase:
    target_size = _ceil_fraction(constant_c * epsilon * vertices)
    request = EpsilonLightInstanceRequest(
        vertices=vertices,
        edges=edges,
        epsilon_numerator=epsilon.numerator,
        epsilon_denominator=epsilon.denominator,
        target_size=target_size,
        seed=seed,
        max_iterations=5000,
    )

    ising_candidate = search_epsilon_light_candidate(request)
    ising_verification = verify_epsilon_light_candidate(request, ising_candidate)
    if (
        ising_verification.status == "SAT"
        and ising_verification.size_ok
        and ising_verification.exact_psd_by_principal_minors
    ):
        payload = {
            "graph_family": graph_family,
            "epsilon": _fraction_text(epsilon),
            "constant_c": _fraction_text(constant_c),
            "target_size": target_size,
            "method": "ISING",
            "candidate_hash": ising_candidate.candidate_hash,
            "certificate_hash": ising_verification.certificate_hash,
            "z3_status": ising_verification.status,
        }
        return EpsilonLightSweepCase(
            graph_family=graph_family,
            vertices=vertices,
            edges=len(edges),
            epsilon=_fraction_text(epsilon),
            constant_c=_fraction_text(constant_c),
            target_size=target_size,
            status="WITNESS_VERIFIED",
            discovery_method="ISING",
            witness_subset=ising_candidate.subset,
            subsets_examined=1,
            z3_status=ising_verification.status,
            certificate_hash=ising_verification.certificate_hash,
            proof_hash=_sha256(payload),
        )

    rejection_certificates: list[dict[str, Any]] = []
    examined = 0
    ising_subset = tuple(sorted(ising_candidate.subset))
    for size in range(target_size, vertices + 1):
        for subset in itertools.combinations(range(vertices), size):
            if subset == ising_subset:
                continue
            examined += 1
            valid, rejection = _exact_subset_rejection(request, subset)
            if valid:
                candidate = _candidate_for_exact_subset(request, subset)
                verification = verify_epsilon_light_candidate(request, candidate)
                payload = {
                    "graph_family": graph_family,
                    "epsilon": _fraction_text(epsilon),
                    "constant_c": _fraction_text(constant_c),
                    "target_size": target_size,
                    "method": "EXHAUSTIVE",
                    "candidate_hash": candidate.candidate_hash,
                    "certificate_hash": verification.certificate_hash,
                    "z3_status": verification.status,
                    "subsets_examined": examined + 1,
                }
                status = "WITNESS_VERIFIED" if verification.status == "SAT" else "UNKNOWN"
                return EpsilonLightSweepCase(
                    graph_family=graph_family,
                    vertices=vertices,
                    edges=len(edges),
                    epsilon=_fraction_text(epsilon),
                    constant_c=_fraction_text(constant_c),
                    target_size=target_size,
                    status=status,
                    discovery_method="EXHAUSTIVE",
                    witness_subset=list(subset),
                    subsets_examined=examined + 1,
                    z3_status=verification.status,
                    certificate_hash=verification.certificate_hash,
                    proof_hash=_sha256(payload),
                )
            if rejection is not None:
                rejection_certificates.append(rejection)

    # Include the Ising candidate in the exhaustive rejection certificate when it was eligible.
    if len(ising_candidate.subset) >= target_size:
        valid, rejection = _exact_subset_rejection(request, ising_subset)
        if valid:
            return EpsilonLightSweepCase(
                graph_family=graph_family,
                vertices=vertices,
                edges=len(edges),
                epsilon=_fraction_text(epsilon),
                constant_c=_fraction_text(constant_c),
                target_size=target_size,
                status="UNKNOWN",
                discovery_method="NONE",
                witness_subset=[],
                subsets_examined=examined + 1,
                z3_status="INCONSISTENT_RECHECK",
                certificate_hash=_sha256({"inconsistent_subset": list(ising_subset)}),
                proof_hash=_sha256({"status": "INCONSISTENT_RECHECK", "subset": list(ising_subset)}),
            )
        if rejection is not None:
            rejection_certificates.append(rejection)
        examined += 1

    # Z3 checks the arithmetic sign of every recorded rejection witness. The exhaustive
    # Python enumeration establishes that every eligible subset has one such certificate.
    solver = Solver()
    for certificate in rejection_certificates:
        determinant = certificate["determinant"]
        solver.add(
            RealVal(determinant["numerator"]) / RealVal(determinant["denominator"]) < 0
        )
    z3_result = solver.check()
    z3_status = "SAT" if z3_result == sat else str(z3_result).upper()
    certificate_hash = _sha256(rejection_certificates)
    payload = {
        "graph_family": graph_family,
        "epsilon": _fraction_text(epsilon),
        "constant_c": _fraction_text(constant_c),
        "target_size": target_size,
        "status": "FINITE_COUNTEREXAMPLE",
        "eligible_subsets_examined": examined,
        "rejection_certificate_hash": certificate_hash,
        "z3_certificate_status": z3_status,
        "z3_solver": f"Z3 {get_version_string()}",
    }
    return EpsilonLightSweepCase(
        graph_family=graph_family,
        vertices=vertices,
        edges=len(edges),
        epsilon=_fraction_text(epsilon),
        constant_c=_fraction_text(constant_c),
        target_size=target_size,
        status="FINITE_COUNTEREXAMPLE" if z3_status == "SAT" else "UNKNOWN",
        discovery_method="NONE",
        witness_subset=[],
        subsets_examined=examined,
        z3_status=z3_status,
        certificate_hash=certificate_hash,
        proof_hash=_sha256(payload),
    )


def run_first_proof_6_sweep(audit_store: AuditStoreProtocol) -> EpsilonLightSweepResult:
    constants = [Fraction(1, 1), Fraction(1, 2), Fraction(1, 4), Fraction(1, 256)]
    epsilons = [Fraction(1, 4), Fraction(1, 2), Fraction(3, 4), Fraction(1, 1)]
    cases: list[EpsilonLightSweepCase] = []

    for constant_c in constants:
        for graph_family, vertices, edges in default_graph_families():
            for epsilon in epsilons:
                cases.append(
                    solve_sweep_case(
                        graph_family=graph_family,
                        vertices=vertices,
                        edges=edges,
                        epsilon=epsilon,
                        constant_c=constant_c,
                    )
                )

    summaries: list[EpsilonLightConstantSummary] = []
    strongest: str | None = None
    for constant_c in constants:
        label = _fraction_text(constant_c)
        selected = [case for case in cases if case.constant_c == label]
        verified = sum(case.status == "WITNESS_VERIFIED" for case in selected)
        counterexamples = sum(case.status == "FINITE_COUNTEREXAMPLE" for case in selected)
        unknown = sum(case.status == "UNKNOWN" for case in selected)
        summaries.append(
            EpsilonLightConstantSummary(
                constant_c=label,
                cases=len(selected),
                verified_cases=verified,
                counterexamples=counterexamples,
                unknown_cases=unknown,
            )
        )
        if strongest is None and verified == len(selected):
            strongest = label

    verified_cases = sum(case.status == "WITNESS_VERIFIED" for case in cases)
    counterexamples = sum(case.status == "FINITE_COUNTEREXAMPLE" for case in cases)
    unknown_cases = sum(case.status == "UNKNOWN" for case in cases)
    proof_payload = {
        "benchmark": "First Proof #6 finite family sweep",
        "total_cases": len(cases),
        "verified_cases": verified_cases,
        "counterexamples": counterexamples,
        "unknown_cases": unknown_cases,
        "strongest_tested_constant_with_all_cases_verified": strongest,
        "case_proof_hashes": [case.proof_hash for case in cases],
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"math_sweep": proof_payload}, proof_hash=proof_hash)
    return EpsilonLightSweepResult(
        status="FINITE_SWEEP_COMPLETE" if unknown_cases == 0 else "FINITE_SWEEP_HAS_UNKNOWN",
        total_cases=len(cases),
        verified_cases=verified_cases,
        counterexamples=counterexamples,
        unknown_cases=unknown_cases,
        strongest_tested_constant_with_all_cases_verified=strongest,
        constant_summaries=summaries,
        cases=cases,
        proof_hash=proof_hash,
        audit_event_hash=audit.event_hash,
        truth_boundary=(
            "This is an exhaustive finite sweep over the listed six-vertex graph families, epsilon grid, and tested constants only. "
            "A FINITE_COUNTEREXAMPLE refutes that tested constant for the specific finite case, while a fully verified constant means only "
            "that all cases in this finite grid had exact witnesses. It does not prove or refute the universal First Proof #6 theorem."
        ),
    )
