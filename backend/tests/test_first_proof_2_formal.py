from __future__ import annotations

import hashlib
from pathlib import Path

from app.audit import AuditStore
from app.math_first_proof_2_formal import (
    FOURIER_SOURCE,
    FOURIER_SOURCE_SHA256,
    LAKEFILE_SHA256,
    LEAN_TOOLCHAIN_SHA256,
    LOGICAL_SOURCE,
    LOGICAL_SOURCE_SHA256,
    MATRIX_FOURIER_SOURCE,
    MATRIX_FOURIER_SOURCE_SHA256,
    SCALAR_SOURCE,
    SCALAR_SOURCE_SHA256,
    VECTOR_FOURIER_SOURCE,
    VECTOR_FOURIER_SOURCE_SHA256,
    first_proof_2_formal_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pinned_formal_source_hashes_match_repository() -> None:
    assert _sha256(REPO_ROOT / SCALAR_SOURCE) == SCALAR_SOURCE_SHA256
    assert _sha256(REPO_ROOT / LOGICAL_SOURCE) == LOGICAL_SOURCE_SHA256
    assert _sha256(REPO_ROOT / FOURIER_SOURCE) == FOURIER_SOURCE_SHA256
    assert _sha256(REPO_ROOT / VECTOR_FOURIER_SOURCE) == VECTOR_FOURIER_SOURCE_SHA256
    assert _sha256(REPO_ROOT / MATRIX_FOURIER_SOURCE) == MATRIX_FOURIER_SOURCE_SHA256
    assert _sha256(REPO_ROOT / "formal/first-proof-2-scalar/lean-toolchain") == LEAN_TOOLCHAIN_SHA256
    assert _sha256(REPO_ROOT / "formal/first-proof-2-scalar/lakefile.toml") == LAKEFILE_SHA256


def test_formal_evidence_is_partial_fail_closed_and_auditable(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "formal-evidence.sqlite3"))
    store.initialize()
    result = first_proof_2_formal_evidence(store)

    assert result.status == "PARTIAL_FORMALIZATION_KERNEL_CHECKED"
    assert result.full_problem_formalized is False
    assert result.build_jobs == 8032
    assert result.ci_receipts == [
        "FIRST_PROOF_2_SCALAR_LEAN=PASS",
        "FIRST_PROOF_2_LOGICAL_SKELETON=PASS",
        "FIRST_PROOF_2_FINITE_FOURIER=PASS",
        "FIRST_PROOF_2_VECTOR_FOURIER=PASS",
        "FIRST_PROOF_2_MATRIX_FOURIER=PASS",
        "NO_SORRY_AXIOM=PASS",
    ]
    assert len(result.theorem_evidence) == 5
    assert len(result.remaining_external_dependencies) == 6

    logical = next(item for item in result.theorem_evidence if "Logical" in item.theorem)
    vector = next(item for item in result.theorem_evidence if "VectorFourier" in item.theorem)
    matrix = next(item for item in result.theorem_evidence if "MatrixFourier" in item.theorem)
    assert logical.reported_axioms == []
    assert vector.reported_axioms == ["propext", "Classical.choice", "Quot.sound"]
    assert matrix.reported_axioms == ["propext", "Classical.choice", "Quot.sound"]
    assert vector.sorry_axiom == "ABSENT"
    assert matrix.sorry_axiom == "ABSENT"
    assert "finite matrix" in matrix.scope.lower()
    assert "K1(q) subgroup/lattice" in result.truth_boundary
    assert "does not claim a full formal proof" in result.truth_boundary

    event = store.get(result.audit_event_hash)
    assert event is not None
    assert event["proof_hash"] == result.proof_hash
    payload = event["payload"]["first_proof_2_formal_evidence"]
    assert payload["full_problem_formalized"] is False
    assert payload["build_jobs"] == 8032
    assert len(payload["theorem_evidence"]) == 5
