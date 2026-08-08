from __future__ import annotations

from app.audit import AuditStore
from app.hybrid_solver import (
    HybridSolveRequest,
    compute_qubo_energy,
    qubo_to_ising,
    solve_and_verify,
    solve_annealing,
)
from app.service import VerificationService


def sat_request() -> HybridSolveRequest:
    return HybridSolveRequest.model_validate(
        {
            "request_id": "hybrid-sat",
            "preset_name": "HYBRID_TEST",
            "rules": [
                {
                    "id": 10,
                    "name": "A",
                    "cost": 10,
                    "risk_reduction": 5,
                    "business_value": 10,
                    "category": "TEST",
                },
                {
                    "id": 20,
                    "name": "B",
                    "cost": 10,
                    "risk_reduction": 10,
                    "business_value": 20,
                    "category": "TEST",
                },
            ],
            "constraints": [
                {
                    "type": "implication",
                    "if_rule": 10,
                    "then_rule": 20,
                    "description": "A requires B",
                },
                {
                    "type": "min_active",
                    "minimum": 1,
                    "description": "At least one active",
                },
                {
                    "type": "max_cost",
                    "budget": 20,
                    "description": "Budget cap",
                },
            ],
            "config": {
                "seed": 42,
                "max_iterations": 500,
                "initial_temperature": 10,
                "min_temperature": 0.001,
                "cooling_rate": 0.99,
                "penalty_weight": 1000,
            },
        }
    )


def test_qubo_to_ising_preserves_energy_for_every_binary_state() -> None:
    q = [[-2.0, 3.0], [0.0, -5.0]]
    j_matrix, h_vector, offset = qubo_to_ising(q)

    for x0 in (0, 1):
        for x1 in (0, 1):
            configuration = [x0, x1]
            spins = [2 * value - 1 for value in configuration]
            qubo_energy = compute_qubo_energy(configuration, q)
            ising_energy = offset
            ising_energy += sum(h_vector[i] * spins[i] for i in range(2))
            ising_energy += j_matrix[0][1] * spins[0] * spins[1]
            assert abs(qubo_energy - ising_energy) < 1e-9


def test_annealing_is_replay_deterministic() -> None:
    request = sat_request()
    first = solve_annealing(request)
    second = solve_annealing(request)

    assert first.configuration == second.configuration
    assert first.solution_hash == second.solution_hash
    assert first.trajectory_hash == second.trajectory_hash
    assert first.qubo_matrix_hash == second.qubo_matrix_hash
    assert first.ising_model_hash == second.ising_model_hash
    assert first.satisfies_local_constraints is True


def test_hybrid_pipeline_uses_z3_and_creates_audit_proof(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "hybrid.sqlite3"))
    store.initialize()
    service = VerificationService(store, signing_secret="test-secret")

    result = solve_and_verify(sat_request(), service)

    assert result.solver_strategy == "deterministic-qubo-ising-annealing+z3"
    assert result.hybrid_status == "Z3_VERIFIED"
    assert result.verification.accepted is True
    assert result.verification.z3_status == "SAT"
    assert result.verification.solver_name == "Z3"
    assert len(result.candidate.solution_hash) == 64
    assert len(result.candidate.trajectory_hash) == 64
    assert len(result.candidate.ising_model_hash) == 64
    assert len(result.verification.proof_hash) == 64
    assert result.verification.audit.sequence == 1


def test_impossible_policy_is_not_claimed_as_verified(tmp_path) -> None:
    request = HybridSolveRequest.model_validate(
        {
            "request_id": "hybrid-unsat",
            "preset_name": "IMPOSSIBLE",
            "rules": [
                {
                    "id": 1,
                    "name": "A",
                    "cost": 0,
                    "risk_reduction": 1,
                    "business_value": 1,
                    "category": "TEST",
                },
                {
                    "id": 2,
                    "name": "B",
                    "cost": 0,
                    "risk_reduction": 1,
                    "business_value": 1,
                    "category": "TEST",
                },
            ],
            "constraints": [
                {
                    "type": "equivalence",
                    "rules": [1, 2],
                    "description": "A and B must match",
                },
                {
                    "type": "mutual_exclusion",
                    "rules": [1, 2],
                    "description": "A and B cannot both be active",
                },
                {
                    "type": "min_active",
                    "minimum": 2,
                    "description": "Both must be active",
                },
            ],
            "config": {"seed": 42, "max_iterations": 200},
        }
    )
    store = AuditStore(str(tmp_path / "hybrid-unsat.sqlite3"))
    store.initialize()
    service = VerificationService(store)

    result = solve_and_verify(request, service)

    assert result.candidate.satisfies_local_constraints is False
    assert result.hybrid_status == "Z3_REJECTED"
    assert result.verification.accepted is False
    assert result.verification.z3_status == "UNSAT"
    assert result.verification.unsat_core
