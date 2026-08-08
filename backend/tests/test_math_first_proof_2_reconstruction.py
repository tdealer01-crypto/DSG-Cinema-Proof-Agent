from __future__ import annotations

from app.audit import AuditStore
from app.math_first_proof_2_reconstruction import (
    audit_first_proof_2_reconstruction,
    reconstruction_dag,
    reference_dependencies,
    verify_reference_scalar_spine,
)


def test_scalar_spine_is_machine_checked() -> None:
    obligations = verify_reference_scalar_spine()

    assert {item.name for item in obligations} == {
        "proposition6_exponent_cancellation",
        "basepoint_normalization",
        "nonzero_scalar_factor",
    }
    assert all(item.status == "UNSAT_NEGATION" for item in obligations)


def test_universal_w0_does_not_depend_on_smaller_representation() -> None:
    step = next(item for item in reconstruction_dag() if item.name == "fix_universal_W0")

    assert step.kind == "REFERENCE"
    assert "Pi" in step.depends_on
    assert "psi" in step.depends_on
    assert not {"pi", "q", "Q"}.intersection(step.depends_on)


def test_reference_dependencies_leave_deep_math_explicit() -> None:
    names = {item.name for item in reference_dependencies()}

    assert {
        "kirillov_extension",
        "godement_jacquet_functional_equation",
        "mellin_support_transform",
        "fourier_to_K1_identity",
        "normalized_newvector_theory",
        "epsilon_factor_nonvanishing",
    } <= names
    assert all(item.status == "REFERENCE_THEOREM_REQUIRED" for item in reference_dependencies())


def test_reconstruction_audit_emits_tamper_evident_receipt(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "first-proof-2-reconstruction.sqlite3"))
    store.initialize()

    result = audit_first_proof_2_reconstruction(store)

    assert result.status == "REFERENCE_RECONSTRUCTION_AUDITED"
    assert result.answer == "YES"
    assert len(result.machine_obligations) == 3
    assert len(result.external_dependencies) == 6
    assert result.final_identity == "ell_RS(s,u_Q W0,d_Q V)=c |Q|^{-n/2} for every s"
    assert len(result.proof_hash) == 64
    assert len(result.audit_event_hash) == 64
    assert "not an independent formal proof" in result.truth_boundary
