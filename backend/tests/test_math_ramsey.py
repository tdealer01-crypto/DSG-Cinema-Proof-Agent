from __future__ import annotations

import itertools

from app.audit import AuditStore
from app.math_ramsey import (
    anneal_ramsey,
    build_ramsey_ising,
    compute_ising_energy,
    prove_no_valid_coloring,
    prove_ramsey_r33,
    verify_fixed_coloring,
)


def test_triangle_ising_energy_is_exact_monochromatic_indicator() -> None:
    _, j_matrix, h_vector, offset = build_ramsey_ising(3)

    for spins in itertools.product((-1, 1), repeat=3):
        energy = compute_ising_energy(list(spins), j_matrix, h_vector, offset)
        expected = 1.0 if spins[0] == spins[1] == spins[2] else 0.0
        assert energy == expected


def test_k5_annealing_finds_deterministic_zero_energy_witness() -> None:
    first = anneal_ramsey(5, seed=42)
    second = anneal_ramsey(5, seed=42)

    assert first.minimum_energy_found == 0.0
    assert first.monochromatic_triangles == 0
    assert first.coloring == second.coloring
    assert first.candidate_hash == second.candidate_hash
    assert first.trajectory_hash == second.trajectory_hash
    assert first.ising_model_hash == second.ising_model_hash


def test_z3_verifies_k5_witness_and_proves_k6_unsat() -> None:
    candidate = anneal_ramsey(5, seed=42)

    k5 = verify_fixed_coloring(5, candidate.coloring)
    k6 = prove_no_valid_coloring(6)

    assert k5.status == "SAT"
    assert k5.fixed_candidate is True
    assert k6.status == "UNSAT"
    assert k6.fixed_candidate is False
    assert k5.solver.startswith("Z3 ")
    assert len(k5.smt2_hash) == 64
    assert len(k6.smt2_hash) == 64


def test_full_ramsey_r33_proof_creates_audit_evidence(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "ramsey.sqlite3"))
    store.initialize()

    proof = prove_ramsey_r33(store)

    assert proof.theorem == "R(3,3)=6"
    assert proof.status == "PROVED"
    assert proof.k5_candidate.minimum_energy_found == 0.0
    assert proof.k5_verification.status == "SAT"
    assert proof.k6_verification.status == "UNSAT"
    assert len(proof.proof_hash) == 64
    assert proof.audit.sequence == 1
    assert len(proof.audit.event_hash) == 64
