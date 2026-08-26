from __future__ import annotations

import json

import pytest

from revenue.revenue_events import (
    EventConflictError,
    EventNotFoundError,
    EventStatus,
    RevenueEventStore,
    canonical_payload_hash,
)


def test_payload_hash_is_canonical():
    left = canonical_payload_hash({"b": 2, "a": [3, 1]})
    right = canonical_payload_hash({"a": [3, 1], "b": 2})
    assert left == right


def test_exact_replay_returns_same_event():
    store = RevenueEventStore()
    first = store.record(
        account_id="acct_dsg_1",
        event_type="lead_created",
        source="cinema",
        source_event_id="evt_001",
        payload={"email": "person@example.com", "source": "dashboard"},
        occurred_at="2026-08-26T00:00:00Z",
    )
    replay = store.record(
        account_id="acct_dsg_1",
        event_type="lead_created",
        source="cinema",
        source_event_id="evt_001",
        payload={"source": "dashboard", "email": "person@example.com"},
        occurred_at="2026-08-26T00:00:00Z",
    )
    assert replay == first
    assert replay.event_id.startswith("rev_")


def test_conflicting_replay_fails_closed():
    store = RevenueEventStore()
    store.record(
        account_id="acct_dsg_1",
        event_type="checkout_started",
        source="stripe",
        source_event_id="cs_001",
        payload={"amount": 1000},
    )
    with pytest.raises(EventConflictError):
        store.record(
            account_id="acct_dsg_1",
            event_type="checkout_started",
            source="stripe",
            source_event_id="cs_001",
            payload={"amount": 2000},
        )


def test_persistence_reload_and_no_raw_pii(tmp_path):
    path = tmp_path / "events.json"
    store = RevenueEventStore(path)
    event = store.record(
        account_id="acct_dsg_2",
        event_type="lead_created",
        source="cinema",
        source_event_id="evt_002",
        payload={"email": "private@example.com", "name": "Private Person"},
        occurred_at="2026-08-26T01:00:00Z",
    )

    raw = path.read_text(encoding="utf-8")
    assert "private@example.com" not in raw
    assert "Private Person" not in raw
    rows = json.loads(raw)
    assert rows[0]["payload_hash"] == event.payload_hash

    reloaded = RevenueEventStore(path).get(source="cinema", source_event_id="evt_002")
    assert reloaded == event


def test_stale_store_reloads_before_write_and_preserves_prior_writer(tmp_path):
    path = tmp_path / "events.json"
    first = RevenueEventStore(path)
    stale = RevenueEventStore(path)

    first.record(
        account_id="acct_dsg_a",
        event_type="lead_created",
        source="cinema",
        source_event_id="evt_a",
    )
    stale.record(
        account_id="acct_dsg_b",
        event_type="demo_requested",
        source="cinema",
        source_event_id="evt_b",
    )

    persisted = RevenueEventStore(path).list_events()
    assert [(item.account_id, item.source_event_id) for item in persisted] == [
        ("acct_dsg_a", "evt_a"),
        ("acct_dsg_b", "evt_b"),
    ]
    assert path.with_suffix(path.suffix + ".lock").exists()


def test_terminal_status_requires_real_reason_or_evidence():
    store = RevenueEventStore()
    store.record(
        account_id="acct_dsg_3",
        event_type="demo_requested",
        source="cinema",
        source_event_id="evt_003",
    )

    with pytest.raises(ValueError):
        store.mark_processed(source="cinema", source_event_id="evt_003", evidence_ref=" ")

    processed = store.mark_processed(
        source="cinema",
        source_event_id="evt_003",
        evidence_ref="proof:demo:evt_003",
    )
    assert processed.status == EventStatus.PROCESSED
    assert processed.evidence_ref == "proof:demo:evt_003"
    assert processed.processed_at is not None

    with pytest.raises(EventConflictError):
        store.mark_failed(
            source="cinema",
            source_event_id="evt_003",
            failure_reason="late rewrite",
        )


def test_unknown_event_cannot_be_marked_processed():
    with pytest.raises(EventNotFoundError):
        RevenueEventStore().mark_processed(
            source="cinema",
            source_event_id="missing",
            evidence_ref="proof:missing",
        )
