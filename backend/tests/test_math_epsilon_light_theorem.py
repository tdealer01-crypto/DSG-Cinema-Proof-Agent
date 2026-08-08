from __future__ import annotations

from app.audit import AuditStore
from app.math_epsilon_light_theorem import close_first_proof_6, verify_official_scalar_spine


def test_official_scalar_spine_is_machine_checked() -> None:
    obligations = verify_official_scalar_spine()

    assert len(obligations) == 5
    assert all(item.status == "UNSAT_NEGATION" for item in obligations)
    assert {item.name for item in obligations} == {
        "initial_barrier_budget",
        "final_barrier_below_epsilon",
        "remaining_vertex_mass",
        "barrier_good_vertex_exists",
        "cardinality_lower_bound",
    }


def test_first_proof_6_closure_reports_reference_theorem(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "first-proof-6-closure.sqlite3"))
    store.initialize()

    result = close_first_proof_6(store)

    assert result.status == "REFERENCE_THEOREM_CLOSED"
    assert result.answer == "YES"
    assert result.universal_constant_c == "1/42"
    assert len(result.scalar_obligations) == 5
    assert len(result.proof_hash) == 64
    assert len(result.audit_event_hash) == 64
    assert "does not claim independent discovery" in result.evidence_level
    assert "mathematically answered YES" in result.truth_boundary
