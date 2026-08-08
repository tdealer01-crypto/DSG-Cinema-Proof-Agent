from __future__ import annotations

import hashlib
import math
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .audit import canonical_json
from .models import PolicyConstraint, PolicyRule, SolverEvidence, VerificationRequest, VerificationResponse
from .service import VerificationService

MASK32 = 0xFFFFFFFF
UINT32_SCALE = 4294967296.0


class DeterministicRNG:
    """Mulberry32-compatible deterministic PRNG ported from the Android solver."""

    def __init__(self, seed: int):
        self.state = seed & MASK32

    def next(self) -> float:
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = ((self.state ^ (self.state >> 15)) * (self.state | 1)) & MASK32
        mixed = ((t ^ (t >> 7)) * (t | 61)) & MASK32
        t = (t ^ ((t + mixed) & MASK32)) & MASK32
        raw = (t ^ (t >> 14)) & MASK32
        return raw / UINT32_SCALE

    def next_int(self, maximum: int) -> int:
        if maximum <= 0:
            return 0
        return min(int(math.floor(self.next() * maximum)), maximum - 1)


class AnnealingConfig(BaseModel):
    seed: int = 42
    max_iterations: int = Field(default=5000, ge=1, le=1_000_000)
    initial_temperature: float = Field(default=100.0, gt=0)
    min_temperature: float = Field(default=0.001, gt=0)
    cooling_rate: float = Field(default=0.995, gt=0, lt=1)
    penalty_weight: float = Field(default=1000.0, gt=0)


class HybridSolveRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=200)
    preset_name: str = Field(min_length=1, max_length=200)
    rules: list[PolicyRule] = Field(min_length=1, max_length=1000)
    constraints: list[PolicyConstraint] = Field(default_factory=list, max_length=5000)
    config: AnnealingConfig = Field(default_factory=AnnealingConfig)
    client_name: str = Field(default="server-hybrid", max_length=100)
    client_version: str = Field(default="1.0", max_length=100)

    @model_validator(mode="after")
    def validate_rule_references(self) -> "HybridSolveRequest":
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        valid_ids = set(ids)
        for constraint in self.constraints:
            referenced = set(constraint.rules)
            if constraint.if_rule is not None:
                referenced.add(constraint.if_rule)
            if constraint.then_rule is not None:
                referenced.add(constraint.then_rule)
            unknown = referenced - valid_ids
            if unknown:
                raise ValueError(f"constraint references unknown rule ids: {sorted(unknown)}")
        return self


class AnnealingCandidate(BaseModel):
    configuration: list[int]
    qubo_energy: float
    feasibility_penalty: float
    total_energy: float
    seed: int
    iterations: int
    solution_hash: str
    trajectory_hash: str
    qubo_matrix_hash: str
    ising_model_hash: str
    satisfies_local_constraints: bool


class HybridSolveResponse(BaseModel):
    request_id: str
    solver_strategy: Literal["deterministic-qubo-ising-annealing+z3"] = (
        "deterministic-qubo-ising-annealing+z3"
    )
    hybrid_status: Literal["Z3_VERIFIED", "Z3_REJECTED", "Z3_UNKNOWN"]
    candidate: AnnealingCandidate
    verification: VerificationResponse


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _id_to_index(rules: list[PolicyRule]) -> dict[int, int]:
    return {rule.id: index for index, rule in enumerate(rules)}


def build_qubo_matrix(
    rules: list[PolicyRule], constraints: list[PolicyConstraint], penalty_weight: float
) -> list[list[float]]:
    """Build the Android DSG policy-QUBO structure while supporting non-contiguous rule IDs."""
    n = len(rules)
    indexes = _id_to_index(rules)
    q = [[0.0 for _ in range(n)] for _ in range(n)]

    for i, rule in enumerate(rules):
        q[i][i] = -(rule.business_value + rule.risk_reduction)

    p = penalty_weight
    for constraint in constraints:
        if constraint.type == "implication":
            a, b = indexes[constraint.if_rule], indexes[constraint.then_rule]
            q[a][a] += p
            q[a][b] -= p
        elif constraint.type == "equivalence":
            group = [indexes[rule_id] for rule_id in constraint.rules]
            for a, b in zip(group, group[1:]):
                q[a][a] += p
                q[b][b] += p
                q[a][b] -= 2 * p
        elif constraint.type == "mutual_exclusion":
            group = [indexes[rule_id] for rule_id in constraint.rules]
            for offset, a in enumerate(group):
                for b in group[offset + 1 :]:
                    q[a][b] += p
        elif constraint.type == "at_least_one_of":
            for rule_id in constraint.rules:
                q[indexes[rule_id]][indexes[rule_id]] -= p * 0.1
        elif constraint.type in {"min_active", "max_cost"}:
            # Enforced by explicit feasibility penalties and then exactly by Z3.
            continue
    return q


def compute_qubo_energy(configuration: list[int], q: list[list[float]]) -> float:
    energy = 0.0
    for i, xi in enumerate(configuration):
        if xi == 0:
            continue
        row = q[i]
        for j, xj in enumerate(configuration):
            if xj:
                energy += row[j]
    return energy


def compute_qubo_delta(configuration: list[int], q: list[list[float]], site: int) -> float:
    flip = 1 if configuration[site] == 0 else -1
    delta = q[site][site] * flip
    for j, xj in enumerate(configuration):
        if j != site:
            delta += (q[site][j] + q[j][site]) * xj * flip
    return delta


def _constraint_satisfied(
    constraint: PolicyConstraint,
    configuration: list[int],
    rules: list[PolicyRule],
) -> bool:
    selected = {rule.id: configuration[index] == 1 for index, rule in enumerate(rules)}
    if constraint.type == "implication":
        return (not selected[constraint.if_rule]) or selected[constraint.then_rule]
    if constraint.type == "equivalence":
        values = [selected[rule_id] for rule_id in constraint.rules]
        return len(set(values)) <= 1
    if constraint.type == "mutual_exclusion":
        return sum(1 for rule_id in constraint.rules if selected[rule_id]) <= 1
    if constraint.type == "at_least_one_of":
        return any(selected[rule_id] for rule_id in constraint.rules)
    if constraint.type == "min_active":
        return sum(configuration) >= constraint.minimum
    if constraint.type == "max_cost":
        total_cost = sum(rule.cost for index, rule in enumerate(rules) if configuration[index])
        return total_cost <= constraint.budget
    raise ValueError(f"Unsupported constraint type: {constraint.type}")


def _feasibility_penalty(
    configuration: list[int],
    rules: list[PolicyRule],
    constraints: list[PolicyConstraint],
    penalty_weight: float,
) -> tuple[float, bool]:
    violations = sum(
        1
        for constraint in constraints
        if not _constraint_satisfied(constraint, configuration, rules)
    )
    return violations * penalty_weight, violations == 0


def qubo_to_ising(q: list[list[float]]) -> tuple[list[list[float]], list[float], float]:
    """Map x∈{0,1} QUBO to E(s)=offset+Σhᵢsᵢ+Σᵢ<ⱼJᵢⱼsᵢsⱼ with s=2x-1."""
    n = len(q)
    j_matrix = [[0.0 for _ in range(n)] for _ in range(n)]
    h_vector = [0.0 for _ in range(n)]
    offset = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            coupling = (q[i][j] + q[j][i]) / 4.0
            j_matrix[i][j] = coupling
            j_matrix[j][i] = coupling

    for i in range(n):
        h_vector[i] = q[i][i] / 2.0
        for j in range(n):
            if j != i:
                h_vector[i] += (q[i][j] + q[j][i]) / 4.0

    for i in range(n):
        # Diagonal QUBO term q_ii*x_i contributes q_ii/2 to the constant offset.
        offset += q[i][i] / 2.0
        for j in range(i + 1, n):
            offset += (q[i][j] + q[j][i]) / 4.0

    return j_matrix, h_vector, offset


def _initial_configuration(rules: list[PolicyRule], constraints: list[PolicyConstraint]) -> list[int]:
    budgets = [constraint.budget for constraint in constraints if constraint.type == "max_cost"]
    budget = min(budgets) if budgets else math.inf
    order = sorted(
        range(len(rules)),
        key=lambda index: (
            (rules[index].business_value + rules[index].risk_reduction)
            / max(rules[index].cost, 1.0)
        ),
        reverse=True,
    )
    configuration = [0] * len(rules)
    running_cost = 0.0
    for index in order:
        rule = rules[index]
        if running_cost + rule.cost <= budget:
            configuration[index] = 1
            running_cost += rule.cost
    return configuration


def solve_annealing(request: HybridSolveRequest) -> AnnealingCandidate:
    """Run deterministic QUBO/Ising-equivalent simulated annealing and return one candidate."""
    config = request.config
    q = build_qubo_matrix(request.rules, request.constraints, config.penalty_weight)
    j_matrix, h_vector, offset = qubo_to_ising(q)
    qubo_matrix_hash = _sha256(q)
    ising_model_hash = _sha256({"J": j_matrix, "h": h_vector, "offset": offset})

    rng = DeterministicRNG(config.seed)
    current = _initial_configuration(request.rules, request.constraints)
    current_qubo = compute_qubo_energy(current, q)
    current_penalty, current_feasible = _feasibility_penalty(
        current, request.rules, request.constraints, config.penalty_weight
    )
    current_total = current_qubo + current_penalty

    best_any = (current.copy(), current_qubo, current_penalty, current_total, current_feasible)
    best_feasible = best_any if current_feasible else None
    temperature = config.initial_temperature
    iterations = 0
    trajectory_hash = _sha256({"genesis": current, "seed": config.seed})

    for step in range(config.max_iterations):
        if temperature < config.min_temperature:
            break
        site = step % len(current) if step % len(current) != 0 else rng.next_int(len(current))
        proposal = current.copy()
        proposal[site] = 1 - proposal[site]

        qubo_delta = compute_qubo_delta(current, q, site)
        proposal_qubo = current_qubo + qubo_delta
        proposal_penalty, proposal_feasible = _feasibility_penalty(
            proposal, request.rules, request.constraints, config.penalty_weight
        )
        proposal_total = proposal_qubo + proposal_penalty
        total_delta = proposal_total - current_total

        accepted = False
        reason = "METROPOLIS_REJECT"
        if total_delta <= 0:
            accepted = True
            reason = "ENERGY_LOWER"
        else:
            probability = math.exp(-total_delta / max(temperature, 0.0001))
            if rng.next() < probability:
                accepted = True
                reason = "METROPOLIS_ACCEPT"

        if accepted:
            current = proposal
            current_qubo = proposal_qubo
            current_penalty = proposal_penalty
            current_total = proposal_total
            current_feasible = proposal_feasible

            if current_total < best_any[3]:
                best_any = (
                    current.copy(), current_qubo, current_penalty, current_total, current_feasible
                )
            if current_feasible and (best_feasible is None or current_total < best_feasible[3]):
                best_feasible = (
                    current.copy(), current_qubo, current_penalty, current_total, True
                )

        trajectory_hash = _sha256(
            {
                "previous_hash": trajectory_hash,
                "sequence": step,
                "site": site,
                "accepted": accepted,
                "reason": reason,
                "qubo_energy": current_qubo,
                "feasibility_penalty": current_penalty,
                "temperature": temperature,
                "state": current,
            }
        )
        temperature *= config.cooling_rate
        iterations = step + 1

    chosen = best_feasible or best_any
    chosen_configuration, chosen_qubo, chosen_penalty, chosen_total, chosen_feasible = chosen
    solution_hash = _sha256(
        {
            "configuration": chosen_configuration,
            "qubo_energy": chosen_qubo,
            "feasibility_penalty": chosen_penalty,
            "seed": config.seed,
            "iterations": iterations,
            "trajectory_hash": trajectory_hash,
            "qubo_matrix_hash": qubo_matrix_hash,
            "ising_model_hash": ising_model_hash,
        }
    )

    return AnnealingCandidate(
        configuration=chosen_configuration,
        qubo_energy=chosen_qubo,
        feasibility_penalty=chosen_penalty,
        total_energy=chosen_total,
        seed=config.seed,
        iterations=iterations,
        solution_hash=solution_hash,
        trajectory_hash=trajectory_hash,
        qubo_matrix_hash=qubo_matrix_hash,
        ising_model_hash=ising_model_hash,
        satisfies_local_constraints=chosen_feasible,
    )


def solve_and_verify(
    request: HybridSolveRequest, verification_service: VerificationService
) -> HybridSolveResponse:
    """Search with deterministic annealing, then verify the fixed candidate with real server-side Z3."""
    candidate = solve_annealing(request)
    verification_request = VerificationRequest(
        request_id=request.request_id,
        preset_name=request.preset_name,
        configuration=candidate.configuration,
        rules=request.rules,
        constraints=request.constraints,
        solver=SolverEvidence(
            seed=candidate.seed,
            iterations=candidate.iterations,
            qubo_energy=candidate.qubo_energy,
            solution_hash=candidate.solution_hash,
        ),
        client_name=request.client_name,
        client_version=request.client_version,
    )
    verification = verification_service.verify(verification_request)
    if verification.z3_status == "SAT" and verification.accepted:
        hybrid_status = "Z3_VERIFIED"
    elif verification.z3_status == "UNKNOWN":
        hybrid_status = "Z3_UNKNOWN"
    else:
        hybrid_status = "Z3_REJECTED"
    return HybridSolveResponse(
        request_id=request.request_id,
        hybrid_status=hybrid_status,
        candidate=candidate,
        verification=verification,
    )
