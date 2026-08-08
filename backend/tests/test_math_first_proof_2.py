from __future__ import annotations

from app.audit import AuditStore
from app.math_first_proof_2 import close_first_proof_2, reference_proof_contract


def test_reference_contract_preserves_universal_W_quantifier() -> None:
    steps, failures = reference_proof_contract()

    universal = next(item for item in steps if item.name == "fixed_whittaker_vector")
    assert universal.depends_on == ["Pi", "psi"]
    assert {item.code for item in failures} == {
        "W_DEPENDS_ON_PI",
        "FALSE_HOWE_VECTOR_SUPPORT",
        "CONSTANT_INTEGRAND_REQUIREMENT",
        "UNJUSTIFIED_NONVANISHING",
    }
    assert all(item.forbidden is True for item in failures)


def test_first_proof_2_closure_is_reference_scoped(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "first-proof-2-closure.sqlite3"))
    store.initialize()

    result = close_first_proof_2(store)

    assert result.status == "REFERENCE_THEOREM_CLOSED"
    assert result.answer == "YES"
    assert "must not depend on pi" in result.universal_vector_contract
    assert "normalized" in result.smaller_representation_contract
    assert len(result.proof_steps) == 5
    assert len(result.rejected_failure_modes) == 4
    assert result.formalization_status == "PARTIAL_FORMALIZATION_KERNEL_CHECKED"
    assert result.full_problem_formalized is False
    assert result.formal_theorems == [
        "Problem2Scalar.proposition6_scalar_spine",
        "Problem2Logical.reference_dependency_logical_closure",
    ]
    assert len(result.formal_source_hashes) == 2
    assert result.formal_ci_receipts == [
        "FIRST_PROOF_2_SCALAR_LEAN=PASS",
        "FIRST_PROOF_2_LOGICAL_SKELETON=PASS",
        "NO_SORRY_AXIOM=PASS",
    ]
    assert len(result.remaining_external_dependencies) == 6
    assert len(result.proof_hash) == 64
    assert len(result.audit_event_hash) == 64
    assert "full_problem_formalized=false" in result.truth_boundary
    assert "does not claim" in result.truth_boundary
