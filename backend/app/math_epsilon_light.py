from __future__ import annotations

import hashlib
import itertools
import math
from fractions import Fraction
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator
from z3 import Bool, If, RealVal, Solver, Sum, get_version_string, sat, unsat

from .audit import canonical_json
from .hybrid_solver import DeterministicRNG, compute_qubo_delta, compute_qubo_energy, qubo_to_ising
from .models import AuditChainProof


class AuditStoreProtocol(Protocol):
    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof: ...


class EpsilonLightInstanceRequest(BaseModel):
    vertices: int = Field(ge=1, le=10)
    edges: list[tuple[int, int]] = Field(default_factory=list, max_length=45)
    epsilon_numerator: int = Field(ge=0)
    epsilon_denominator: int = Field(gt=0)
    target_size: int = Field(ge=0)
    seed: int = 42
    max_iterations: int = Field(default=5000, ge=1, le=200_000)

    @model_validator(mode="after")
    def validate_graph(self) -> "EpsilonLightInstanceRequest":
        if self.epsilon_numerator > self.epsilon_denominator:
            raise ValueError("epsilon must be between 0 and 1")
        if self.target_size > self.vertices:
            raise ValueError("target_size cannot exceed vertices")
        normalized: set[tuple[int, int]] = set()
        for u, v in self.edges:
            if u == v:
                raise ValueError("self loops are not supported")
            if not (0 <= u < self.vertices and 0 <= v < self.vertices):
                raise ValueError("edge endpoint outside vertex range")
            edge = (u, v) if u < v else (v, u)
            if edge in normalized:
                raise ValueError(f"duplicate edge: {edge}")
            normalized.add(edge)
        self.edges = sorted(normalized)
        return self

    @property
    def epsilon(self) -> Fraction:
        return Fraction(self.epsilon_numerator, self.epsilon_denominator)


class EpsilonLightCandidate(BaseModel):
    subset: list[int]
    subset_size: int
    internal_edges: int
    seed: int
    iterations: int
    qubo_energy: float
    qubo_matrix_hash: str
    ising_model_hash: str
    trajectory_hash: str
    candidate_hash: str


class EpsilonLightVerification(BaseModel):
    status: Literal["SAT", "UNSAT", "UNKNOWN"]
    solver: str
    size_ok: bool
    exact_psd_by_principal_minors: bool
    principal_minors_checked: int
    negative_principal_minors: int
    matrix_hash: str
    certificate_hash: str
    smt2_hash: str


class EpsilonLightInstanceResult(BaseModel):
    problem: Literal["First Proof #6 finite epsilon-light instance"] = (
        "First Proof #6 finite epsilon-light instance"
    )
    status: Literal["FINITE_INSTANCE_VERIFIED", "CANDIDATE_REJECTED", "UNKNOWN"]
    vertices: int
    epsilon: str
    target_size: int
    candidate: EpsilonLightCandidate
    verification: EpsilonLightVerification
    proof_hash: str
    audit: AuditChainProof
    truth_boundary: str


class EpsilonLightBenchmarkResult(BaseModel):
    benchmark: Literal["First Proof #6 / K8 / epsilon=1/2 / target=4"] = (
        "First Proof #6 / K8 / epsilon=1/2 / target=4"
    )
    result: EpsilonLightInstanceResult


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _fraction_payload(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _complete_graph_edges(vertices: int) -> list[tuple[int, int]]:
    return list(itertools.combinations(range(vertices), 2))


def _laplacian(vertices: int, edges: list[tuple[int, int]]) -> list[list[Fraction]]:
    matrix = [[Fraction(0) for _ in range(vertices)] for _ in range(vertices)]
    for u, v in edges:
        matrix[u][u] += 1
        matrix[v][v] += 1
        matrix[u][v] -= 1
        matrix[v][u] -= 1
    return matrix


def _epsilon_light_matrix(request: EpsilonLightInstanceRequest, subset: list[int]) -> list[list[Fraction]]:
    selected = set(subset)
    internal = [(u, v) for u, v in request.edges if u in selected and v in selected]
    full_laplacian = _laplacian(request.vertices, request.edges)
    subset_laplacian = _laplacian(request.vertices, internal)
    epsilon = request.epsilon
    return [
        [epsilon * full_laplacian[i][j] - subset_laplacian[i][j] for j in range(request.vertices)]
        for i in range(request.vertices)
    ]


def _determinant(matrix: list[list[Fraction]]) -> Fraction:
    n = len(matrix)
    if n == 0:
        return Fraction(1)
    work = [row[:] for row in matrix]
    sign = 1
    determinant = Fraction(1)
    for column in range(n):
        pivot = next((row for row in range(column, n) if work[row][column] != 0), None)
        if pivot is None:
            return Fraction(0)
        if pivot != column:
            work[column], work[pivot] = work[pivot], work[column]
            sign *= -1
        pivot_value = work[column][column]
        determinant *= pivot_value
        for row in range(column + 1, n):
            if work[row][column] == 0:
                continue
            factor = work[row][column] / pivot_value
            for col in range(column, n):
                work[row][col] -= factor * work[column][col]
    return determinant * sign


def _principal_minors(matrix: list[list[Fraction]]) -> list[tuple[tuple[int, ...], Fraction]]:
    n = len(matrix)
    results: list[tuple[tuple[int, ...], Fraction]] = []
    for size in range(1, n + 1):
        for indexes in itertools.combinations(range(n), size):
            principal = [[matrix[i][j] for j in indexes] for i in indexes]
            results.append((indexes, _determinant(principal)))
    return results


def _matrix_payload(matrix: list[list[Fraction]]) -> list[list[dict[str, int]]]:
    return [[_fraction_payload(value) for value in row] for row in matrix]


def _build_subset_qubo(request: EpsilonLightInstanceRequest) -> list[list[float]]:
    """QUBO candidate search only; exact epsilon-lightness is verified afterwards.

    The dominant term targets |S|=target_size. A smaller pairwise penalty discourages
    internal edges as a sparsity surrogate. It is intentionally not claimed to encode
    the PSD condition exactly.
    """
    n = request.vertices
    target = request.target_size
    cardinality_weight = 100.0
    edge_weight = 1.0
    q = [[0.0 for _ in range(n)] for _ in range(n)]

    for i in range(n):
        q[i][i] += cardinality_weight * (1 - 2 * target)
    for i in range(n):
        for j in range(i + 1, n):
            q[i][j] += 2 * cardinality_weight
    for u, v in request.edges:
        q[u][v] += edge_weight
    return q


def _initial_subset_configuration(request: EpsilonLightInstanceRequest) -> list[int]:
    degree = [0] * request.vertices
    for u, v in request.edges:
        degree[u] += 1
        degree[v] += 1
    order = sorted(range(request.vertices), key=lambda vertex: (degree[vertex], vertex))
    selected = set(order[: request.target_size])
    return [1 if vertex in selected else 0 for vertex in range(request.vertices)]


def search_epsilon_light_candidate(request: EpsilonLightInstanceRequest) -> EpsilonLightCandidate:
    q = _build_subset_qubo(request)
    j_matrix, h_vector, offset = qubo_to_ising(q)
    qubo_matrix_hash = _sha256(q)
    ising_model_hash = _sha256({"J": j_matrix, "h": h_vector, "offset": offset})

    rng = DeterministicRNG(request.seed)
    current = _initial_subset_configuration(request)
    current_energy = compute_qubo_energy(current, q)
    best = current[:]
    best_energy = current_energy
    temperature = 50.0
    cooling_rate = 0.995
    min_temperature = 0.001
    iterations = 0
    trajectory_hash = _sha256({"genesis": current, "seed": request.seed})

    for step in range(request.max_iterations):
        if temperature < min_temperature:
            break
        site = rng.next_int(request.vertices)
        delta = compute_qubo_delta(current, q, site)
        accepted = False
        if delta <= 0:
            accepted = True
        elif rng.next() < math.exp(-delta / max(temperature, 0.0001)):
            accepted = True
        if accepted:
            current[site] = 1 - current[site]
            current_energy += delta
            if current_energy < best_energy:
                best = current[:]
                best_energy = current_energy
        trajectory_hash = _sha256(
            {
                "previous_hash": trajectory_hash,
                "step": step,
                "site": site,
                "accepted": accepted,
                "energy": current_energy,
                "temperature": temperature,
                "state": current,
            }
        )
        temperature *= cooling_rate
        iterations = step + 1

    subset = [index for index, active in enumerate(best) if active]
    selected = set(subset)
    internal_edges = sum(1 for u, v in request.edges if u in selected and v in selected)
    candidate_hash = _sha256(
        {
            "subset": subset,
            "qubo_energy": best_energy,
            "seed": request.seed,
            "trajectory_hash": trajectory_hash,
            "qubo_matrix_hash": qubo_matrix_hash,
            "ising_model_hash": ising_model_hash,
        }
    )
    return EpsilonLightCandidate(
        subset=subset,
        subset_size=len(subset),
        internal_edges=internal_edges,
        seed=request.seed,
        iterations=iterations,
        qubo_energy=best_energy,
        qubo_matrix_hash=qubo_matrix_hash,
        ising_model_hash=ising_model_hash,
        trajectory_hash=trajectory_hash,
        candidate_hash=candidate_hash,
    )


def verify_epsilon_light_candidate(
    request: EpsilonLightInstanceRequest, candidate: EpsilonLightCandidate
) -> EpsilonLightVerification:
    matrix = _epsilon_light_matrix(request, candidate.subset)
    minors = _principal_minors(matrix)
    negative = [(indexes, value) for indexes, value in minors if value < 0]
    exact_psd = not negative
    size_ok = candidate.subset_size >= request.target_size

    solver = Solver()
    membership = [Bool(f"epsilon_light_v_{i}") for i in range(request.vertices)]
    selected = set(candidate.subset)
    for index, variable in enumerate(membership):
        solver.add(variable == (index in selected))
    solver.add(Sum([If(variable, 1, 0) for variable in membership]) >= request.target_size)
    for _, value in minors:
        solver.add(RealVal(value.numerator) / RealVal(value.denominator) >= 0)

    result = solver.check()
    status = "SAT" if result == sat else "UNSAT" if result == unsat else "UNKNOWN"
    certificate_payload = [
        {"indexes": list(indexes), "determinant": _fraction_payload(value)}
        for indexes, value in minors
    ]
    return EpsilonLightVerification(
        status=status,
        solver=f"Z3 {get_version_string()}",
        size_ok=size_ok,
        exact_psd_by_principal_minors=exact_psd,
        principal_minors_checked=len(minors),
        negative_principal_minors=len(negative),
        matrix_hash=_sha256(_matrix_payload(matrix)),
        certificate_hash=_sha256(certificate_payload),
        smt2_hash=_sha256(solver.to_smt2()),
    )


def run_epsilon_light_instance(
    request: EpsilonLightInstanceRequest, audit_store: AuditStoreProtocol
) -> EpsilonLightInstanceResult:
    candidate = search_epsilon_light_candidate(request)
    verification = verify_epsilon_light_candidate(request, candidate)
    if verification.status == "UNKNOWN":
        status = "UNKNOWN"
    elif verification.status == "SAT" and verification.size_ok and verification.exact_psd_by_principal_minors:
        status = "FINITE_INSTANCE_VERIFIED"
    else:
        status = "CANDIDATE_REJECTED"

    proof_payload = {
        "problem": "First Proof #6 finite epsilon-light instance",
        "status": status,
        "graph": {"vertices": request.vertices, "edges": request.edges},
        "epsilon": _fraction_payload(request.epsilon),
        "target_size": request.target_size,
        "candidate_hash": candidate.candidate_hash,
        "qubo_matrix_hash": candidate.qubo_matrix_hash,
        "ising_model_hash": candidate.ising_model_hash,
        "trajectory_hash": candidate.trajectory_hash,
        "z3_status": verification.status,
        "matrix_hash": verification.matrix_hash,
        "principal_minor_certificate_hash": verification.certificate_hash,
        "smt2_hash": verification.smt2_hash,
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"math_proof": proof_payload}, proof_hash=proof_hash)
    return EpsilonLightInstanceResult(
        status=status,
        vertices=request.vertices,
        epsilon=f"{request.epsilon.numerator}/{request.epsilon.denominator}",
        target_size=request.target_size,
        candidate=candidate,
        verification=verification,
        proof_hash=proof_hash,
        audit=audit,
        truth_boundary=(
            "This verifies one finite graph instance of First Proof #6. The QUBO/Ising stage is a candidate-search "
            "heuristic; the epsilon-light PSD condition is checked exactly for the fixed candidate using all "
            "principal minors and Z3 arithmetic. It does not prove the universal theorem or the c=1/256 claim."
        ),
    )


def run_first_proof_6_benchmark(audit_store: AuditStoreProtocol) -> EpsilonLightBenchmarkResult:
    request = EpsilonLightInstanceRequest(
        vertices=8,
        edges=_complete_graph_edges(8),
        epsilon_numerator=1,
        epsilon_denominator=2,
        target_size=4,
        seed=42,
        max_iterations=5000,
    )
    return EpsilonLightBenchmarkResult(result=run_epsilon_light_instance(request, audit_store))
