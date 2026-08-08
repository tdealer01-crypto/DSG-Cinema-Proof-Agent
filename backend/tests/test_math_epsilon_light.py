from __future__ import annotations

from app.audit import AuditStore
from app.math_epsilon_light import (
    EpsilonLightCandidate,
    EpsilonLightInstanceRequest,
    _complete_graph_edges,
    run_epsilon_light_instance,
    run_first_proof_6_benchmark,
    search_epsilon_light_candidate,
    verify_epsilon_light_candidate,
)


def test_k8_half_epsilon_benchmark_is_finite_instance_verified(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "epsilon-light.sqlite3"))
    store.initialize()

    benchmark = run_first_proof_6_benchmark(store)
    result = benchmark.result

    assert result.status == "FINITE_INSTANCE_VERIFIED"
    assert result.epsilon == "1/2"
    assert result.target_size == 4
    assert result.candidate.subset_size == 4
    assert result.candidate.internal_edges == 6
    assert result.verification.status == "SAT"
    assert result.verification.size_ok is True
    assert result.verification.exact_psd_by_principal_minors is True
    assert result.verification.principal_minors_checked == 255
    assert result.verification.negative_principal_minors == 0
    assert len(result.proof_hash) == 64
    assert result.audit.sequence == 1
    assert "does not prove the universal theorem" in result.truth_boundary


def test_candidate_search_replays_deterministically() -> None:
    request = EpsilonLightInstanceRequest(
        vertices=8,
        edges=_complete_graph_edges(8),
        epsilon_numerator=1,
        epsilon_denominator=2,
        target_size=4,
        seed=42,
        max_iterations=5000,
    )

    first = search_epsilon_light_candidate(request)
    second = search_epsilon_light_candidate(request)

    assert first.subset == second.subset
    assert first.qubo_energy == second.qubo_energy
    assert first.qubo_matrix_hash == second.qubo_matrix_hash
    assert first.ising_model_hash == second.ising_model_hash
    assert first.trajectory_hash == second.trajectory_hash
    assert first.candidate_hash == second.candidate_hash


def test_k8_quarter_epsilon_rejects_size_three_fixed_candidate() -> None:
    request = EpsilonLightInstanceRequest(
        vertices=8,
        edges=_complete_graph_edges(8),
        epsilon_numerator=1,
        epsilon_denominator=4,
        target_size=3,
        seed=42,
        max_iterations=100,
    )
    candidate = EpsilonLightCandidate(
        subset=[0, 1, 2],
        subset_size=3,
        internal_edges=3,
        seed=42,
        iterations=0,
        qubo_energy=0.0,
        qubo_matrix_hash="0" * 64,
        ising_model_hash="1" * 64,
        trajectory_hash="2" * 64,
        candidate_hash="3" * 64,
    )

    verification = verify_epsilon_light_candidate(request, candidate)

    assert verification.status == "UNSAT"
    assert verification.size_ok is True
    assert verification.exact_psd_by_principal_minors is False
    assert verification.negative_principal_minors > 0
    assert verification.principal_minors_checked == 255


def test_generic_instance_keeps_theorem_claim_out_of_status(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "epsilon-light-generic.sqlite3"))
    store.initialize()
    request = EpsilonLightInstanceRequest(
        vertices=6,
        edges=[(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)],
        epsilon_numerator=1,
        epsilon_denominator=2,
        target_size=3,
        seed=7,
        max_iterations=1000,
    )

    result = run_epsilon_light_instance(request, store)

    assert result.status in {"FINITE_INSTANCE_VERIFIED", "CANDIDATE_REJECTED", "UNKNOWN"}
    assert result.status != "THEOREM_PROVED"
    assert result.verification.principal_minors_checked == 63
