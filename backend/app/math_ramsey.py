from __future__ import annotations

import hashlib
import itertools
import math
from typing import Literal, Protocol, Any

from pydantic import BaseModel
from z3 import And, Bool, Not, Solver, get_version_string, sat, unsat

from .audit import canonical_json
from .hybrid_solver import DeterministicRNG
from .models import AuditChainProof


class AuditStoreProtocol(Protocol):
    def append(self, payload: dict[str, Any], proof_hash: str) -> AuditChainProof: ...


class RamseyAnnealingResult(BaseModel):
    vertices: int
    edges: int
    triangles: int
    seed: int
    iterations: int
    minimum_energy_found: float
    monochromatic_triangles: int
    coloring: dict[str, str]
    ising_model_hash: str
    trajectory_hash: str
    candidate_hash: str


class RamseyZ3Result(BaseModel):
    vertices: int
    status: Literal["SAT", "UNSAT", "UNKNOWN"]
    fixed_candidate: bool
    solver: str
    smt2_hash: str


class RamseyR33Proof(BaseModel):
    theorem: Literal["R(3,3)=6"] = "R(3,3)=6"
    status: Literal["PROVED", "FAILED"]
    lower_bound_reason: str
    upper_bound_reason: str
    k5_candidate: RamseyAnnealingResult
    k5_verification: RamseyZ3Result
    k6_verification: RamseyZ3Result
    proof_hash: str
    audit: AuditChainProof


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def complete_graph_edges(vertices: int) -> list[tuple[int, int]]:
    return [(u, v) for u in range(vertices) for v in range(u + 1, vertices)]


def triangles(vertices: int) -> list[tuple[int, int, int]]:
    return list(itertools.combinations(range(vertices), 3))


def build_ramsey_ising(vertices: int) -> tuple[list[tuple[int, int]], list[list[float]], list[float], float]:
    """Build the exact quadratic Ising penalty for monochromatic triangles.

    Each complete-graph edge is a spin s_e in {-1,+1}. For one triangle with edge
    spins a,b,c, the monochromatic indicator is exactly

        (1 + ab + ac + bc) / 4.

    Therefore energy 0 is equivalent to a 2-edge-coloring with no monochromatic
    triangle, with no higher-order reduction or approximation.
    """
    edges = complete_graph_edges(vertices)
    index = {edge: i for i, edge in enumerate(edges)}
    n = len(edges)
    j_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    h_vector = [0.0 for _ in range(n)]
    offset = 0.0

    for a, b, c in triangles(vertices):
        triangle_edges = [index[(a, b)], index[(a, c)], index[(b, c)]]
        offset += 0.25
        for left, right in itertools.combinations(triangle_edges, 2):
            j_matrix[left][right] += 0.25
            j_matrix[right][left] += 0.25

    return edges, j_matrix, h_vector, offset


def compute_ising_energy(
    spins: list[int], j_matrix: list[list[float]], h_vector: list[float], offset: float
) -> float:
    energy = offset
    for i, spin in enumerate(spins):
        energy += h_vector[i] * spin
        for j in range(i + 1, len(spins)):
            energy += j_matrix[i][j] * spin * spins[j]
    return energy


def count_monochromatic_triangles(vertices: int, spins: list[int]) -> int:
    edges = complete_graph_edges(vertices)
    index = {edge: i for i, edge in enumerate(edges)}
    count = 0
    for a, b, c in triangles(vertices):
        values = [spins[index[(a, b)]], spins[index[(a, c)]], spins[index[(b, c)]]]
        if values[0] == values[1] == values[2]:
            count += 1
    return count


def anneal_ramsey(
    vertices: int,
    *,
    seed: int = 42,
    max_iterations: int = 5000,
    initial_temperature: float = 5.0,
    cooling_rate: float = 0.995,
    min_temperature: float = 0.001,
) -> RamseyAnnealingResult:
    edges, j_matrix, h_vector, offset = build_ramsey_ising(vertices)
    rng = DeterministicRNG(seed)
    spins = [1 if rng.next() < 0.5 else -1 for _ in edges]
    current_energy = compute_ising_energy(spins, j_matrix, h_vector, offset)
    best_spins = spins.copy()
    best_energy = current_energy
    temperature = initial_temperature
    iterations = 0
    trajectory_hash = _sha256({"genesis": spins, "seed": seed, "vertices": vertices})

    for step in range(max_iterations):
        if temperature < min_temperature or best_energy == 0.0:
            break

        site = rng.next_int(len(spins))
        proposal = spins.copy()
        proposal[site] *= -1
        proposal_energy = compute_ising_energy(proposal, j_matrix, h_vector, offset)
        delta = proposal_energy - current_energy

        accepted = delta <= 0
        reason = "ENERGY_LOWER"
        if not accepted:
            probability = math.exp(-delta / max(temperature, 1e-12))
            accepted = rng.next() < probability
            reason = "METROPOLIS_ACCEPT" if accepted else "METROPOLIS_REJECT"

        if accepted:
            spins = proposal
            current_energy = proposal_energy
            if current_energy < best_energy:
                best_energy = current_energy
                best_spins = spins.copy()

        trajectory_hash = _sha256(
            {
                "previous_hash": trajectory_hash,
                "sequence": step,
                "site": site,
                "accepted": accepted,
                "reason": reason,
                "energy": current_energy,
                "temperature": temperature,
                "state": spins,
            }
        )
        temperature *= cooling_rate
        iterations = step + 1

    coloring = {
        f"{u}-{v}": ("RED" if best_spins[index] == 1 else "BLUE")
        for index, (u, v) in enumerate(edges)
    }
    ising_model_hash = _sha256({"J": j_matrix, "h": h_vector, "offset": offset})
    candidate_hash = _sha256(
        {
            "vertices": vertices,
            "seed": seed,
            "spins": best_spins,
            "energy": best_energy,
            "ising_model_hash": ising_model_hash,
            "trajectory_hash": trajectory_hash,
        }
    )

    return RamseyAnnealingResult(
        vertices=vertices,
        edges=len(edges),
        triangles=len(triangles(vertices)),
        seed=seed,
        iterations=iterations,
        minimum_energy_found=best_energy,
        monochromatic_triangles=count_monochromatic_triangles(vertices, best_spins),
        coloring=coloring,
        ising_model_hash=ising_model_hash,
        trajectory_hash=trajectory_hash,
        candidate_hash=candidate_hash,
    )


def _ramsey_solver(vertices: int) -> tuple[Solver, list[tuple[int, int]], dict[tuple[int, int], Any]]:
    edges = complete_graph_edges(vertices)
    variables = {edge: Bool(f"e_{edge[0]}_{edge[1]}") for edge in edges}
    solver = Solver()
    for a, b, c in triangles(vertices):
        ab = variables[(a, b)]
        ac = variables[(a, c)]
        bc = variables[(b, c)]
        solver.add(Not(And(ab, ac, bc)))
        solver.add(Not(And(Not(ab), Not(ac), Not(bc))))
    return solver, edges, variables


def verify_fixed_coloring(vertices: int, coloring: dict[str, str]) -> RamseyZ3Result:
    solver, edges, variables = _ramsey_solver(vertices)
    for edge in edges:
        key = f"{edge[0]}-{edge[1]}"
        if key not in coloring:
            raise ValueError(f"missing edge coloring: {key}")
        solver.add(variables[edge] == (coloring[key] == "RED"))
    result = solver.check()
    status = "SAT" if result == sat else "UNSAT" if result == unsat else "UNKNOWN"
    return RamseyZ3Result(
        vertices=vertices,
        status=status,
        fixed_candidate=True,
        solver=f"Z3 {get_version_string()}",
        smt2_hash=_sha256(solver.to_smt2()),
    )


def prove_no_valid_coloring(vertices: int) -> RamseyZ3Result:
    solver, _, _ = _ramsey_solver(vertices)
    result = solver.check()
    status = "SAT" if result == sat else "UNSAT" if result == unsat else "UNKNOWN"
    return RamseyZ3Result(
        vertices=vertices,
        status=status,
        fixed_candidate=False,
        solver=f"Z3 {get_version_string()}",
        smt2_hash=_sha256(solver.to_smt2()),
    )


def prove_ramsey_r33(audit_store: AuditStoreProtocol) -> RamseyR33Proof:
    """Machine-check the classical theorem R(3,3)=6 using Ising search + exact Z3.

    The lower bound R(3,3)>5 is witnessed by an Ising-found K5 coloring and then
    verified with Z3. The upper bound R(3,3)<=6 is proved by Z3 UNSAT for the
    existence of any 2-coloring of K6 with no monochromatic triangle.
    """
    k5_candidate = anneal_ramsey(5)
    k5_verification = verify_fixed_coloring(5, k5_candidate.coloring)
    k6_verification = prove_no_valid_coloring(6)

    proved = (
        k5_candidate.minimum_energy_found == 0.0
        and k5_candidate.monochromatic_triangles == 0
        and k5_verification.status == "SAT"
        and k6_verification.status == "UNSAT"
    )
    status = "PROVED" if proved else "FAILED"
    proof_payload = {
        "theorem": "R(3,3)=6",
        "status": status,
        "lower_bound": {
            "claim": "R(3,3)>5",
            "candidate_hash": k5_candidate.candidate_hash,
            "ising_model_hash": k5_candidate.ising_model_hash,
            "trajectory_hash": k5_candidate.trajectory_hash,
            "z3_status": k5_verification.status,
            "smt2_hash": k5_verification.smt2_hash,
        },
        "upper_bound": {
            "claim": "R(3,3)<=6",
            "z3_status": k6_verification.status,
            "smt2_hash": k6_verification.smt2_hash,
        },
        "z3_solver": k6_verification.solver,
    }
    proof_hash = _sha256(proof_payload)
    audit = audit_store.append(payload={"math_proof": proof_payload}, proof_hash=proof_hash)

    return RamseyR33Proof(
        status=status,
        lower_bound_reason=(
            "Ising found a 2-coloring of K5 with zero monochromatic triangles; Z3 verified the fixed witness SAT."
        ),
        upper_bound_reason=(
            "Z3 returned UNSAT for the existence of any 2-coloring of K6 without a monochromatic triangle."
        ),
        k5_candidate=k5_candidate,
        k5_verification=k5_verification,
        k6_verification=k6_verification,
        proof_hash=proof_hash,
        audit=audit,
    )
