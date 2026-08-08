from __future__ import annotations

from app.audit import AuditStore
from app.math_epsilon_light_lemma_lab import run_first_proof_6_lemma_lab


def test_exhaustive_lemma_lab_proves_finite_c_half_and_finds_exact_boundary(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "epsilon-light-lemma-lab.sqlite3"))
    store.initialize()

    result = run_first_proof_6_lemma_lab(store)

    assert result.status == "FINITE_THEOREM_VERIFIED"
    assert result.max_vertices == 5
    assert result.graph_count == 1099
    assert result.graph_epsilon_cases == 4396
    assert result.epsilon_grid == ["1/4", "1/2", "3/4", "1/1"]
    assert result.tested_constant == "1/2"
    assert result.tested_constant_verified_for_all_cases is True
    assert result.finite_optimal_constant == "8/15"

    extremal = result.extremal_case
    assert extremal.vertices == 5
    assert extremal.epsilon == "3/4"
    assert extremal.maximum_light_subset_size == 2
    assert extremal.ratio == "8/15"
    assert extremal.edges == [(0, 3), (0, 4), (1, 2), (1, 4), (2, 3)]
    assert extremal.rejected_large_subsets == 16
    assert extremal.z3_rejection_certificate_status.endswith(": SAT")
    assert len(extremal.certificate_hash) == 64

    lemmas = {lemma.name: lemma for lemma in result.universal_lemmas}
    assert lemmas["independent_sets_are_epsilon_light"].status == "PROVED_ELEMENTARY"
    assert lemmas["bounded_max_degree_reduction_for_c_half"].status == "PROVED_ELEMENTARY"
    assert lemmas["high_degree_case_for_c_half"].status == "OPEN"

    assert len(result.proof_hash) == 64
    assert len(result.audit_event_hash) == 64
    assert "does not imply a universal constant" in result.truth_boundary
    assert "not an independent solution" in result.truth_boundary
