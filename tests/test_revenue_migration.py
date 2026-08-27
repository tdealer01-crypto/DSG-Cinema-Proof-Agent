from __future__ import annotations

import json
from pathlib import Path

import pytest

from revenue.accounts import Account
from revenue.ledger import GENESIS_HASH, LedgerEntry, compute_entry_hash
from revenue.migration import (
    ARCHIVE_CONFIRMATION,
    MigrationError,
    RevenueSnapshot,
    SnapshotError,
    TargetSnapshot,
    _archive_table,
    load_snapshot,
    migrate_connection,
    snapshot_summary,
)


NOW = "2026-08-27T10:11:12.123456Z"
ROOT = Path(__file__).resolve().parent.parent


def account(account_id: str = "acct-live") -> Account:
    return Account(
        account_id=account_id,
        display_name="Live account",
        plan="metered",
        key_id=f"key-{account_id}",
        secret_hash="s" * 64,
        stripe_customer_id="cus_live",
        stripe_subscription_id="sub_live",
        payment_linked=True,
        stripe_paid_amounts_micros={"2026-08": 49_000_000},
        stripe_paid_invoice_ids=["in_live"],
        stripe_processed_event_ids=["evt_live"],
        stripe_field_event_created={"entitlement": 1_777_000_000},
        created_at=NOW,
        updated_at=NOW,
    )


def entry(account_id: str = "acct-live") -> LedgerEntry:
    body = {
        "sequence": 0,
        "period": "2026-08",
        "account_id": account_id,
        "channel": "api",
        "sku": "verified_execution",
        "quantity": 1,
        "units_before": 0,
        "unit_price_micros": 250_000,
        "amount_micros": 250_000,
        "proof_hash": "p" * 64,
        "context_hash": "c" * 64,
        "idempotency_key": "i" * 64,
        "recorded_at": NOW,
        "prev_hash": GENESIS_HASH,
    }
    return LedgerEntry(**body, entry_hash=compute_entry_hash(body))


def source_snapshot() -> RevenueSnapshot:
    return RevenueSnapshot(accounts=(account(),), ledger=(entry(),))


def write_snapshot(tmp_path, source: RevenueSnapshot):
    accounts_path = tmp_path / "accounts.json"
    ledger_path = tmp_path / "ledger.json"
    accounts_path.write_text(
        json.dumps([item.to_dict() for item in source.accounts]), encoding="utf-8"
    )
    ledger_path.write_text(
        json.dumps([item.to_dict() for item in source.ledger]), encoding="utf-8"
    )
    return accounts_path, ledger_path


class Cursor:
    def __init__(self):
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        self.statements.append((statement, params))


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_load_snapshot_preserves_stripe_state_and_verifies_chain(tmp_path):
    source = source_snapshot()
    accounts_path, ledger_path = write_snapshot(tmp_path, source)

    loaded = load_snapshot(accounts_path, ledger_path)
    summary = snapshot_summary(loaded)

    assert loaded == source
    assert loaded.accounts[0].stripe_processed_event_ids == ["evt_live"]
    assert summary["accounts"] == 1
    assert summary["ledger"]["entries"] == 1
    assert summary["ledger"]["head_hash"] == source.ledger[0].entry_hash
    assert len(summary["accounts_fingerprint"]) == 64


def test_load_snapshot_rejects_a_broken_ledger_before_database_access(tmp_path):
    source = source_snapshot()
    accounts_path, ledger_path = write_snapshot(tmp_path, source)
    damaged = json.loads(ledger_path.read_text(encoding="utf-8"))
    damaged[0]["entry_hash"] = "0" * 64
    ledger_path.write_text(json.dumps(damaged), encoding="utf-8")

    with pytest.raises(SnapshotError, match="hash-chain verification"):
        load_snapshot(accounts_path, ledger_path)


def test_load_snapshot_rejects_ledger_rows_without_their_account(tmp_path):
    source = RevenueSnapshot(accounts=(), ledger=(entry(),))
    accounts_path, ledger_path = write_snapshot(tmp_path, source)

    with pytest.raises(SnapshotError, match="absent from accounts snapshot"):
        load_snapshot(accounts_path, ledger_path)


def test_file_backend_reports_durable_only_with_the_deployment_attestation(
    tmp_path, monkeypatch
):
    from revenue.accounts import AccountStore
    from revenue.cutover import storage_summary
    from revenue.engine import RevenueEngine
    from revenue.ledger import LedgerStore

    engine = RevenueEngine(
        accounts=AccountStore(str(tmp_path / "accounts.json")),
        ledger=LedgerStore(str(tmp_path / "ledger.json")),
    )
    monkeypatch.delenv("DSG_REVENUE_STORAGE_DURABLE", raising=False)
    assert storage_summary(engine)["durable"] is False

    monkeypatch.setenv("DSG_REVENUE_STORAGE_DURABLE", "1")
    assert storage_summary(engine)["durable"] is True


def test_migration_refuses_divergent_target_without_archive_confirmation(monkeypatch):
    source = source_snapshot()
    target = TargetSnapshot(accounts=(account("acct-target"),), ledger=(), guarded_rows=1)
    connection = Connection()
    monkeypatch.setattr(
        "revenue.migration._read_target", lambda _cursor, **_kwargs: target
    )

    with pytest.raises(MigrationError, match="refusing replacement"):
        migrate_connection(connection, source)

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert not any("DELETE FROM" in sql for sql, _ in connection.cursor_instance.statements)


def test_migration_treats_guarded_rows_as_divergent_even_when_revenue_matches(
    monkeypatch,
):
    source = source_snapshot()
    target = TargetSnapshot(accounts=source.accounts, ledger=source.ledger, guarded_rows=1)
    connection = Connection()
    monkeypatch.setattr(
        "revenue.migration._read_target", lambda _cursor, **_kwargs: target
    )

    with pytest.raises(MigrationError, match="refusing replacement"):
        migrate_connection(connection, source)

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_migration_archives_then_commits_only_after_exact_readback(monkeypatch):
    source = source_snapshot()
    divergent = TargetSnapshot(
        accounts=(account("acct-target"),), ledger=(), guarded_rows=1
    )
    observed = TargetSnapshot(accounts=source.accounts, ledger=source.ledger, guarded_rows=0)
    targets = iter((divergent, observed))
    connection = Connection()
    archived: list[str] = []
    inserted: list[RevenueSnapshot] = []

    monkeypatch.setattr(
        "revenue.migration._read_target", lambda _cursor, **_kwargs: next(targets)
    )
    monkeypatch.setattr(
        "revenue.migration._archive_table",
        lambda _cursor, *, archive_id, table, key: archived.append(table) or 1,
    )
    monkeypatch.setattr(
        "revenue.migration._insert_source",
        lambda _cursor, snapshot: inserted.append(snapshot),
    )

    result = migrate_connection(
        connection,
        source,
        archive_divergent_target=True,
        archive_id="cutover-123-1",
        confirmation=ARCHIVE_CONFIRMATION,
    )

    assert result["action"] == "migrated"
    assert result["source"]["ledger"] == result["target"]["ledger"]
    assert archived == [
        "dsg_guarded_evidence",
        "dsg_revenue_ledger_entries",
        "dsg_revenue_accounts",
    ]
    assert inserted == [source]
    deletes = [sql for sql, _ in connection.cursor_instance.statements if "DELETE FROM" in sql]
    assert deletes == [
        "DELETE FROM dsg_guarded_evidence",
        "DELETE FROM dsg_revenue_ledger_entries",
        "DELETE FROM dsg_revenue_accounts",
    ]
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_migration_rolls_back_when_readback_differs(monkeypatch):
    source = source_snapshot()
    empty = TargetSnapshot(accounts=(), ledger=(), guarded_rows=0)
    mismatched = TargetSnapshot(accounts=(), ledger=(), guarded_rows=0)
    targets = iter((empty, mismatched))
    connection = Connection()
    monkeypatch.setattr(
        "revenue.migration._read_target", lambda _cursor, **_kwargs: next(targets)
    )
    monkeypatch.setattr("revenue.migration._insert_source", lambda *_args: None)

    with pytest.raises(MigrationError, match="read-back"):
        migrate_connection(connection, source)

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_archive_uses_parameterized_metadata_and_checks_row_count():
    class ArchiveCursor:
        def __init__(self):
            self.statements = []
            self.results = iter(((2,), (2,)))

        def execute(self, statement, params=()):
            self.statements.append((statement, params))

        def fetchone(self):
            return next(self.results)

    cursor = ArchiveCursor()
    assert (
        _archive_table(
            cursor,
            archive_id="cutover-123-1",
            table="dsg_revenue_accounts",
            key="account_id",
        )
        == 2
    )
    insert_sql, insert_params = cursor.statements[1]
    assert "to_jsonb(source_row)" in insert_sql
    assert "cutover-123-1" not in insert_sql
    assert insert_params == ("cutover-123-1", "dsg_revenue_accounts")


def test_inspect_command_needs_no_file_arguments_and_refuses_an_unknown_database(
    monkeypatch, capsys
):
    from scripts import migrate_revenue_store

    monkeypatch.delenv("DSG_REVENUE_DATABASE_URL", raising=False)
    assert migrate_revenue_store.main(["inspect"]) == 1
    assert "refusing to guess a database" in capsys.readouterr().err


def test_workflows_require_manual_parity_before_deploy_can_keep_postgres_enabled():
    deploy = (ROOT / ".github/workflows/deploy-cinema-production.yml").read_text(
        encoding="utf-8"
    )
    cutover = (ROOT / ".github/workflows/cutover-revenue-postgres.yml").read_text(
        encoding="utf-8"
    )

    marker_gate = 'if [[ "$REVENUE_POSTGRES_ENABLED" == "1" ]]; then'
    secret_binding = 'CINEMA_SECRET_ARGS+=("revenue-database-url='
    assert marker_gate in deploy
    assert deploy.index(marker_gate) < deploy.index(secret_binding)
    assert "Merely adding the GitHub\n          # secret or merging this workflow must never switch" in deploy
    assert "DSG_REVENUE_DATABASE_URL= DSG_REVENUE_POSTGRES_ENABLED=0" in deploy
    assert "Refusing an ordinary deployment until the cutover workflow" in deploy
    assert deploy.index("CURRENT_REVENUE_FREEZE_MARKER") < deploy.index(
        "            DSG_REVENUE_WRITE_FROZEN=0"
    )

    positions = [
        cutover.index("CUTOVER_REVENUE_TO_POSTGRES"),
        cutover.index('FREEZE_SUFFIX="freeze-'),
        cutover.index("scripts/migrate_revenue_store.py apply"),
        cutover.index("scripts/migrate_revenue_store.py verify"),
        cutover.index("DSG_REVENUE_DATABASE_URL=secretref:revenue-database-url"),
        cutover.index('COMMIT_SUFFIX="commit-'),
        cutover.index("replay_github_marketplace_queue /tmp/github-marketplace-before-unfreeze.json"),
        cutover.index('UNFREEZE_SUFFIX="unfreeze-'),
        cutover.index("replay_github_marketplace_queue /tmp/github-marketplace-final.json"),
    ]
    assert positions == sorted(positions)
    assert "az containerapp ingress disable" not in cutover
    assert "ARCHIVE_AND_REPLACE_DIVERGENT_TARGET" in cutover
    assert "restoring the unchanged file stores" in cutover
    assert "POSTGRES_RECOVERY_REQUIRED=1" in cutover
    assert "/marketplace/github/replay-pending" in cutover

    production_mutators = (
        "apply-guarded-migration.yml",
        "activecampaign-revenue-reconcile.yml",
        "bind-browserbase-production.yml",
        "configure-github-marketplace-production.yml",
        "configure-stripe-production.yml",
        "deploy-cinema-production.yml",
        "enforce-v1-persistent-store.yml",
        "post-deploy-v1-persistence-audit.yml",
    )
    for name in production_mutators:
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "  group: cinema-z3-production" in workflow, name
