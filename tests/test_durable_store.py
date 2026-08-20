"""A shared revenue store must survive more than one writer.

Container Apps runs the old and new replica together for a moment during a
revision switch. With a file-backed store that means two processes writing the
same ledger. Before cross-process locking this silently dropped entries and the
surviving chain still verified, so the loss was invisible.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

from revenue.accounts import AccountStore
from revenue.ledger import LedgerStore, verify_chain

REPO_ROOT = Path(__file__).resolve().parents[1]

WRITER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    from revenue.ledger import LedgerStore

    path, worker, count = sys.argv[1], sys.argv[2], int(sys.argv[3])
    store = LedgerStore(path)
    for index in range(count):
        store.append(
            account_id="acct_" + worker,
            channel="api",
            sku="verified_execution",
            quantity=1,
            unit_price_micros=100_000,
            amount_micros=100_000,
            proof_hash="a" * 64,
            context_hash=worker + format(index, "063d"),
            idempotency_key=worker + "-" + str(index),
            units_before=0,
        )
    """
)


def run_writers(tmp_path: Path, workers: list[str], per_worker: int) -> Path:
    ledger = tmp_path / "ledger.json"
    script = tmp_path / "writer.py"
    script.write_text(WRITER.format(root=str(REPO_ROOT)), encoding="utf-8")

    processes = [
        subprocess.Popen(
            [sys.executable, str(script), str(ledger), worker, str(per_worker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for worker in workers
    ]
    for process in processes:
        _, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, stderr.decode()[-2000:]
    return ledger


def test_concurrent_replicas_lose_no_ledger_entries(tmp_path):
    workers = ["A", "B", "C", "D"]
    per_worker = 20
    ledger = run_writers(tmp_path, workers, per_worker)

    entries = LedgerStore(str(ledger)).entries()
    assert len(entries) == len(workers) * per_worker

    # Every writer's units survived, so no process overwrote another's work.
    assert Counter(entry.account_id for entry in entries) == {
        f"acct_{worker}": per_worker for worker in workers
    }


def test_a_concurrently_written_chain_still_verifies(tmp_path):
    ledger = run_writers(tmp_path, ["A", "B", "C"], 15)
    entries = LedgerStore(str(ledger)).entries()

    report = verify_chain(entries)
    assert report["verified"] is True
    assert report["entries"] == 45
    assert report["total_amount_micros"] == 45 * 100_000
    # Sequences must be dense: a gap means an interleaved write was lost.
    assert [entry.sequence for entry in entries] == list(range(45))


def test_a_second_store_sees_the_first_stores_writes(tmp_path):
    path = str(tmp_path / "ledger.json")
    first = LedgerStore(path)
    second = LedgerStore(path)

    first.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="key-0",
        units_before=0,
    )

    # The second store was opened before that write and must not serve a stale
    # view, or it would reuse sequence 0 and fork the chain.
    assert second.size() == 1
    assert second.head_hash() == first.head_hash()

    second.append(
        account_id="acct_2",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="b" * 64,
        context_hash="d" * 64,
        idempotency_key="key-1",
        units_before=0,
    )

    assert verify_chain(LedgerStore(path).entries())["verified"] is True


def test_idempotency_holds_across_processes(tmp_path):
    path = str(tmp_path / "ledger.json")
    first = LedgerStore(path)
    second = LedgerStore(path)

    payload = dict(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="shared-key",
        units_before=0,
    )

    entry_one, created_one = first.append(**payload)
    entry_two, created_two = second.append(**payload)

    assert created_one is True
    assert created_two is False, "a second replica double-billed the same context"
    assert entry_two.entry_hash == entry_one.entry_hash
    assert LedgerStore(path).size() == 1


def test_the_lock_file_is_not_mistaken_for_ledger_data(tmp_path):
    path = tmp_path / "ledger.json"
    store = LedgerStore(str(path))
    store.append(
        account_id="acct_1",
        channel="api",
        sku="verified_execution",
        quantity=1,
        unit_price_micros=100_000,
        amount_micros=100_000,
        proof_hash="a" * 64,
        context_hash="c" * 64,
        idempotency_key="key-0",
        units_before=0,
    )

    assert path.with_suffix(".json.lock").exists()
    assert json.loads(path.read_text(encoding="utf-8"))
    assert LedgerStore(str(path)).size() == 1


def test_a_paid_upgrade_survives_an_unrelated_write_from_another_replica(tmp_path):
    """A long-lived replica must not revert a customer who has paid.

    Persistence rewrites the whole registry. Without a reload under lock, the
    replica that issued the account still believes the customer is on the free
    plan and silently reverts the upgrade on its next unrelated write.
    """
    path = str(tmp_path / "accounts.json")

    replica_a = AccountStore(path)
    account, _ = replica_a.issue(display_name="Acme", plan="free")

    # Replica B handles the Stripe webhook: the customer paid.
    replica_b = AccountStore(path)
    replica_b.update(account.account_id, plan="metered", payment_linked=True)

    # Replica A is still alive and writes something unrelated.
    replica_a.issue(display_name="Someone Else", plan="free")

    stored = AccountStore(path).get(account.account_id)
    assert stored is not None
    assert stored.plan == "metered", "a paying customer was reverted to the free plan"
    assert stored.payment_linked is True
    assert len(AccountStore(path).all()) == 2


def test_a_key_issued_by_another_replica_authenticates(tmp_path):
    """An activation on one replica must be usable against another."""
    path = str(tmp_path / "accounts.json")
    replica_a = AccountStore(path)
    replica_b = AccountStore(path)

    account, api_key = replica_a.issue(display_name="Acme", plan="free")

    authenticated = replica_b.authenticate(api_key)
    assert authenticated is not None, "a key issued elsewhere was rejected"
    assert authenticated.account_id == account.account_id
