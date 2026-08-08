from __future__ import annotations

from fractions import Fraction

from app.audit import AuditStore
from app.math_epsilon_light_sweep import (
    default_graph_families,
    run_first_proof_6_sweep,
    solve_sweep_case,
)


def test_complete_k6_quarter_epsilon_is_exact_counterexample_to_c1() -> None:
    family, vertices, edges = default_graph_families()[0]
    result = solve_sweep_case(
        graph_family=family,
        vertices=vertices,
        edges=edges,
        epsilon=Fraction(1, 4),
        constant_c=Fraction(1, 1),
    )

    assert result.graph_family == "complete_K6"
    assert result.target_size == 2
    assert result.status == "FINITE_COUNTEREXAMPLE"
    assert result.discovery_method == "NONE"
    assert result.witness_subset == []
    assert result.subsets_examined == 57
    assert result.z3_status == "SAT"
    assert len(result.certificate_hash) == 64
    assert len(result.proof_hash) == 64


def test_full_sweep_finds_boundary_on_tested_grid(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "epsilon-light-sweep.sqlite3"))
    store.initialize()

    result = run_first_proof_6_sweep(store)

    assert result.status == "FINITE_SWEEP_COMPLETE"
    assert result.total_cases == 80
    assert result.verified_cases == 75
    assert result.counterexamples == 5
    assert result.unknown_cases == 0
    assert result.strongest_tested_constant_with_all_cases_verified == "1/2"
    assert len(result.constant_summaries) == 4

    c1 = next(summary for summary in result.constant_summaries if summary.constant_c == "1/1")
    assert c1.cases == 20
    assert c1.verified_cases == 15
    assert c1.counterexamples == 5
    assert c1.unknown_cases == 0

    c_half = next(summary for summary in result.constant_summaries if summary.constant_c == "1/2")
    assert c_half.verified_cases == 20
    assert c_half.counterexamples == 0

    c_openai_scale = next(summary for summary in result.constant_summaries if summary.constant_c == "1/256")
    assert c_openai_scale.verified_cases == 20
    assert c_openai_scale.counterexamples == 0

    assert len(result.proof_hash) == 64
    assert len(result.audit_event_hash) == 64
    assert "does not prove or refute the universal" in result.truth_boundary
