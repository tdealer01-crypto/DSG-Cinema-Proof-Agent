from __future__ import annotations

from app.audit import AuditStore
from app.math_first_proof_2_triangulation import (
    ALETHEIA_BLOB_SHA,
    ALETHEIA_COMMIT,
    public_sources,
    triangulate_first_proof_2,
)


def test_public_sources_pin_aletheia_and_fail_closed_on_lean_report() -> None:
    sources = public_sources()
    assert len(sources) == 3

    aletheia = next(item for item in sources if item.name.startswith("Google DeepMind Aletheia"))
    assert aletheia.immutable_ref == ALETHEIA_COMMIT
    assert aletheia.content_sha == ALETHEIA_BLOB_SHA
    assert aletheia.verification_status == "PINNED_PUBLIC_SOURCE_RECORDED"

    lean_report = next(item for item in sources if item.source_kind == "REPORTED_LEAN_SKELETON")
    assert lean_report.verification_status == "REPORT_ONLY_NOT_REPLAYED"


def test_triangulation_certificate_is_auditable(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "triangulation.sqlite3"))
    store.initialize()

    result = triangulate_first_proof_2(store)

    assert result.status == "MULTISOURCE_CORROBORATED"
    assert result.answer == "YES"
    assert len(result.shared_invariants) == 4
    assert "universal_W_quantifier_guard" in result.dsg_machine_checks
    assert "proposition6_exponent_cancellation" in result.dsg_machine_checks
    assert "a02069ef66dbae4c5b0713ba0dc144a35375558f" in result.replayable_external_source
    assert "9cae0e02192093ac828d5688184ce7daf66e9eed" in result.replayable_external_source
    assert "not located" in result.nonreplayable_external_report
    assert "not a full Lean/Coq formalization" in result.truth_boundary

    event = store.get(result.audit_event_hash)
    assert event is not None
    assert event["proof_hash"] == result.proof_hash
    assert event["payload"]["first_proof_2_multisource_triangulation"]["answer"] == "YES"
