"""Persistence contract for DSG ONE v1 plan/execution/proof records."""

from __future__ import annotations

from api_v1.store import RecordStore, resolve_store_path


def test_v1_store_reuses_durable_revenue_mount_and_survives_reopen(tmp_path):
    env = {
        "DSG_REVENUE_LEDGER_STORE": str(tmp_path / "ledger.json"),
        "DSG_V1_SINGLE_WRITER": "1",
    }

    path, source = resolve_store_path(env=env)
    assert path == tmp_path / "v1-records.json"
    assert source == "revenue_mount"

    first = RecordStore(env=env)
    assert first.mode == "file"
    assert first.durable is True
    assert first.source == "revenue_mount"
    assert first.single_writer_attested is True
    assert first.production_safe is True

    first.put(
        "proofs",
        "proof_persistent",
        {
            "proof_id": "proof_persistent",
            "decision": "ALLOW",
            "receipt_hash": "a" * 64,
        },
    )

    reopened = RecordStore(env=env)
    assert reopened.get("proofs", "proof_persistent") == {
        "proof_id": "proof_persistent",
        "decision": "ALLOW",
        "receipt_hash": "a" * 64,
    }
    assert reopened.counts()["proofs"] == 1


def test_explicit_v1_path_wins_over_revenue_mount(tmp_path):
    env = {
        "DSG_V1_STORE_PATH": str(tmp_path / "explicit.json"),
        "DSG_REVENUE_LEDGER_STORE": str(tmp_path / "revenue" / "ledger.json"),
        "DSG_V1_SINGLE_WRITER": "1",
    }

    path, source = resolve_store_path(env=env)
    assert path == tmp_path / "explicit.json"
    assert source == "explicit"


def test_store_truthfully_reports_memory_when_no_persistence_is_bound():
    store = RecordStore(env={})
    assert store.path is None
    assert store.mode == "memory"
    assert store.durable is False
    assert store.source == "memory"
    assert store.single_writer_attested is False
    assert store.production_safe is False


def test_file_store_without_single_writer_attestation_is_not_production_safe(tmp_path):
    store = RecordStore(str(tmp_path / "records.json"), env={})
    assert store.durable is True
    assert store.single_writer_attested is False
    assert store.production_safe is False
