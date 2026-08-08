from __future__ import annotations

import hashlib
from pathlib import Path

from app.audit import AuditStore
from app.math_first_proof_2_formal import (
    LAKEFILE_SHA256,
    LEAN_TOOLCHAIN_SHA256,
    LOGICAL_SOURCE,
    LOGICAL_SOURCE_SHA256,
    SCALAR_SOURCE,
    SCALAR_SOURCE_SHA256,
    first_proof_2_formal_evidence,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pinned_formal_source_hashes_match_repository() -> None:
    assert _sha256(REPO_ROOT / SCALAR_SOURCE) == SCALAR_SOURCE_SHA256
    assert _sha256(REPO_ROOT / LOGICAL_SOURCE) == LOGICAL_SOURCE_SHA256
    assert (
        _sha256(REPO_ROOT / "formal/first-proof-2-scalar/lean-toolchain")
        == LEAN_TOOLCHAIN_SHA256
    )
    assert _sha256(REPO_ROOT / "formal/first-proof-2-scalar/lakefile.toml") == LAKEFILE_SHA256


def test_formal_evidence_is_partial_fail_closed_and_auditable(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "formal-evidence.sqlite3"))
    store.initialize()

    result = first_proof_2_formal_evidence(store)

    assert result.status == "PARTIAL_FORMALIZATION_KERNEL_CHECKED"
    assert result.full_problem_formalized is False
    assert result.build_jobs == 8029
    assert "FIRST_PROOF_2_SCALAR_LEAN=PASS" in result.ci_receipts
    assert "FIRST_PROOF_2_LOGICAL_SKELETON=PASS" in result.ci_receipts
    assert "NO_SORRY_AXIOM=PASS" in result.ci_receipts
    assert len(result.remaining_external_dependencies) == 6

    scalar = next(item for item in result.theorem_evidence if "Scalar" in item.theorem)
    logical = next(item for item in result.theorem_evidence if "Logical" in item.theorem)
    assert scalar.reported_axioms == ["propext", "Classical.choice", "Quot.sound"]
    assert logical.reported_axioms == []
    assert scalar.sorry_axiom == "ABSENT"
    assert logical.sorry_axiom == "ABSENT"
    assert "partial formalization only" in result.truth_boundary
    assert "does not claim a full formal proof" in result.truth_boundary

    event = store.get(result.audit_event_hash)
    assert event is not None
    assert event["proof_hash"] == result.proof_hash
    assert event["payload"]["first_proof_2_formal_evidence"]["full_problem_formalized"] is False
