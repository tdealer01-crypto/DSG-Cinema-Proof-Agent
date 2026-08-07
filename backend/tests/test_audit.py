from __future__ import annotations

from app.audit import AuditStore, ZERO_HASH


def test_audit_chain_links_events(tmp_path) -> None:
    store = AuditStore(str(tmp_path / "audit.sqlite3"))
    store.initialize()

    first = store.append({"value": 1}, "proof-1")
    second = store.append({"value": 2}, "proof-2")

    assert first.sequence == 1
    assert first.previous_hash == ZERO_HASH
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert second.event_hash != first.event_hash
