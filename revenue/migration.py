"""Fail-closed migration of the authoritative revenue files to PostgreSQL.

The file stores remain authoritative until a caller freezes writes and takes a
snapshot.  This module validates that snapshot, archives any divergent target
rows, replaces the target in one short transaction, and commits only after an
exact read-back comparison (including the ledger hash chain).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from api_v1.guarded_store import TABLE as GUARDED_TABLE
from revenue.accounts import Account
from revenue.ledger import LedgerEntry, verify_chain
from revenue.postgres import (
    PostgresLedgerStore,
    _ACCOUNT_COLUMNS,
    _account_from_row,
    _account_values,
)


ARCHIVE_TABLE = "dsg_revenue_cutover_archive"
CUTOVER_LOCK = 0x44534743
ARCHIVE_CONFIRMATION = "ARCHIVE_AND_REPLACE_DIVERGENT_TARGET"
_ARCHIVE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

ARCHIVE_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {ARCHIVE_TABLE} (
    archive_id TEXT NOT NULL,
    source_table TEXT NOT NULL,
    row_key TEXT NOT NULL,
    row_data JSONB NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (archive_id, source_table, row_key)
);
ALTER TABLE {ARCHIVE_TABLE} ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE {ARCHIVE_TABLE} FROM anon';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE {ARCHIVE_TABLE} FROM authenticated';
    END IF;
END $$;
""".strip()


class SnapshotError(ValueError):
    """The file snapshot cannot be represented as the live revenue state."""


class MigrationError(RuntimeError):
    """The target was unsafe to replace or failed exact parity verification."""


@dataclass(frozen=True)
class RevenueSnapshot:
    accounts: tuple[Account, ...]
    ledger: tuple[LedgerEntry, ...]


@dataclass(frozen=True)
class TargetSnapshot:
    accounts: tuple[Account, ...]
    ledger: tuple[LedgerEntry, ...]
    guarded_rows: int

    @property
    def has_rows(self) -> bool:
        return bool(self.accounts or self.ledger or self.guarded_rows)


def _load_array(path: str | Path, label: str) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{label} snapshot is not readable JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SnapshotError(f"{label} snapshot must be a JSON array of objects")
    return value


def load_snapshot(accounts_path: str | Path, ledger_path: str | Path) -> RevenueSnapshot:
    """Load and fully validate the authoritative file snapshot."""
    try:
        accounts = tuple(Account(**item) for item in _load_array(accounts_path, "accounts"))
        ledger = tuple(LedgerEntry(**item) for item in _load_array(ledger_path, "ledger"))
    except TypeError as exc:
        raise SnapshotError("revenue snapshot has missing or unexpected fields") from exc

    account_ids = [account.account_id for account in accounts]
    key_ids = [account.key_id for account in accounts if account.key_id]
    if len(account_ids) != len(set(account_ids)):
        raise SnapshotError("accounts snapshot contains duplicate account_id values")
    if len(key_ids) != len(set(key_ids)):
        raise SnapshotError("accounts snapshot contains duplicate key_id values")

    try:
        verify_chain(ledger)
    except ValueError as exc:
        raise SnapshotError(f"ledger snapshot failed hash-chain verification: {exc}") from exc

    unknown = sorted({entry.account_id for entry in ledger} - set(account_ids))
    if unknown:
        raise SnapshotError(
            f"ledger snapshot references {len(unknown)} account(s) absent from accounts snapshot"
        )
    return RevenueSnapshot(accounts=accounts, ledger=ledger)


def _account_payload(accounts: Iterable[Account]) -> list[dict[str, Any]]:
    return [
        account.to_dict()
        for account in sorted(accounts, key=lambda candidate: candidate.account_id)
    ]


def account_fingerprint(accounts: Iterable[Account]) -> str:
    """Return a safe equality commitment without exposing account or Stripe fields."""
    payload = json.dumps(
        _account_payload(accounts),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def snapshot_summary(snapshot: RevenueSnapshot | TargetSnapshot) -> dict[str, Any]:
    chain = verify_chain(snapshot.ledger)
    result: dict[str, Any] = {
        "accounts": len(snapshot.accounts),
        "accounts_fingerprint": account_fingerprint(snapshot.accounts),
        "ledger": chain,
    }
    if isinstance(snapshot, TargetSnapshot):
        result["guarded_rows"] = snapshot.guarded_rows
    return result


def snapshots_match(source: RevenueSnapshot, target: TargetSnapshot) -> bool:
    return (
        _account_payload(source.accounts) == _account_payload(target.accounts)
        and [entry.to_dict() for entry in source.ledger]
        == [entry.to_dict() for entry in target.ledger]
    )


def _read_target(cursor, *, verify_ledger: bool = True) -> TargetSnapshot:
    cursor.execute(
        f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts ORDER BY account_id"
    )
    accounts = tuple(_account_from_row(row) for row in cursor.fetchall())
    cursor.execute(
        f"SELECT {PostgresLedgerStore._LEDGER_COLUMNS} "
        "FROM dsg_revenue_ledger_entries ORDER BY sequence"
    )
    ledger = tuple(PostgresLedgerStore._entry(row) for row in cursor.fetchall())
    cursor.execute(f"SELECT COUNT(*) FROM {GUARDED_TABLE}")
    guarded_rows = int(cursor.fetchone()[0])
    if verify_ledger:
        try:
            verify_chain(ledger)
        except ValueError as exc:
            raise MigrationError(f"target ledger hash chain is invalid: {exc}") from exc
    return TargetSnapshot(accounts=accounts, ledger=ledger, guarded_rows=guarded_rows)


def read_target(connection) -> TargetSnapshot:
    with connection.cursor() as cursor:
        return _read_target(cursor)


def _archive_table(cursor, *, archive_id: str, table: str, key: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    expected = int(cursor.fetchone()[0])
    cursor.execute(
        f"INSERT INTO {ARCHIVE_TABLE} (archive_id, source_table, row_key, row_data) "
        f"SELECT %s, %s, {key}::text, to_jsonb(source_row) FROM {table} AS source_row",
        (archive_id, table),
    )
    cursor.execute(
        f"SELECT COUNT(*) FROM {ARCHIVE_TABLE} WHERE archive_id = %s AND source_table = %s",
        (archive_id, table),
    )
    archived = int(cursor.fetchone()[0])
    if archived != expected:
        raise MigrationError(
            f"archive parity failed for {table}: expected {expected} rows, stored {archived}"
        )
    return archived


def _insert_source(cursor, source: RevenueSnapshot) -> None:
    account_placeholders = ", ".join(["%s"] * len(_ACCOUNT_COLUMNS.split(", ")))
    if source.accounts:
        cursor.executemany(
            f"INSERT INTO dsg_revenue_accounts ({_ACCOUNT_COLUMNS}) "
            f"VALUES ({account_placeholders})",
            [_account_values(account) for account in source.accounts],
        )

    if source.ledger:
        cursor.executemany(
            "INSERT INTO dsg_revenue_ledger_entries "
            "(sequence, account_id, channel, sku, period, quantity, units_before, "
            "unit_price_micros, amount_micros, context_hash, proof_hash, "
            "idempotency_key, previous_hash, entry_hash, recorded_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    entry.sequence,
                    entry.account_id,
                    entry.channel,
                    entry.sku,
                    entry.period,
                    entry.quantity,
                    entry.units_before,
                    entry.unit_price_micros,
                    entry.amount_micros,
                    entry.context_hash,
                    entry.proof_hash,
                    entry.idempotency_key,
                    entry.prev_hash,
                    entry.entry_hash,
                    entry.recorded_at,
                )
                for entry in source.ledger
            ],
        )


def migrate_connection(
    connection,
    source: RevenueSnapshot,
    *,
    archive_divergent_target: bool = False,
    archive_id: str | None = None,
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Replace target rows atomically, committing only after exact parity."""
    if archive_divergent_target:
        if not archive_id or not _ARCHIVE_ID.fullmatch(archive_id):
            raise MigrationError("a safe archive_id is required to replace divergent target rows")
        if confirmation != ARCHIVE_CONFIRMATION:
            raise MigrationError(
                f"divergent replacement requires confirmation {ARCHIVE_CONFIRMATION}"
            )

    try:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (CUTOVER_LOCK,))
            # Explicit archival authorisation permits recovery from a broken
            # throwaway/test target too: every raw row is archived before it is
            # deleted. Without that authorisation, even an invalid chain fails
            # before any target mutation.
            target = _read_target(cursor, verify_ledger=not archive_divergent_target)

            if snapshots_match(source, target) and target.guarded_rows == 0:
                connection.commit()
                return {
                    "action": "already_in_sync",
                    "archived": {},
                    "source": snapshot_summary(source),
                    "target": snapshot_summary(target),
                }

            archived: dict[str, int] = {}
            if target.has_rows:
                if not archive_divergent_target:
                    raise MigrationError(
                        "target contains divergent rows; refusing replacement without archival confirmation"
                    )
                cursor.execute(ARCHIVE_SCHEMA_SQL)
                for table, key in (
                    (GUARDED_TABLE, "evidence_id"),
                    ("dsg_revenue_ledger_entries", "sequence"),
                    ("dsg_revenue_accounts", "account_id"),
                ):
                    archived[table] = _archive_table(
                        cursor, archive_id=archive_id, table=table, key=key
                    )
                cursor.execute(f"DELETE FROM {GUARDED_TABLE}")
                cursor.execute("DELETE FROM dsg_revenue_ledger_entries")
                cursor.execute("DELETE FROM dsg_revenue_accounts")

            _insert_source(cursor, source)
            observed = _read_target(cursor)
            if not snapshots_match(source, observed):
                raise MigrationError("PostgreSQL read-back did not exactly match the file snapshot")
            observed_summary = snapshot_summary(observed)
            source_summary = snapshot_summary(source)
            if observed_summary["ledger"] != source_summary["ledger"]:
                raise MigrationError("PostgreSQL ledger count or chain head changed during read-back")

        connection.commit()
        return {
            "action": "migrated",
            "archive_id": archive_id if archived else None,
            "archived": archived,
            "source": source_summary,
            "target": observed_summary,
        }
    except Exception:
        connection.rollback()
        raise


def verify_connection(connection, source: RevenueSnapshot) -> dict[str, Any]:
    target = read_target(connection)
    if not snapshots_match(source, target):
        raise MigrationError("PostgreSQL state does not exactly match the file snapshot")
    if target.guarded_rows != 0:
        raise MigrationError(
            "PostgreSQL guarded evidence is not empty at the file-store cutover boundary"
        )
    source_summary = snapshot_summary(source)
    target_summary = snapshot_summary(target)
    if source_summary["ledger"] != target_summary["ledger"]:
        raise MigrationError("PostgreSQL ledger count or chain head differs from the file snapshot")
    return {"verified": True, "source": source_summary, "target": target_summary}


__all__ = [
    "ARCHIVE_CONFIRMATION",
    "ARCHIVE_TABLE",
    "MigrationError",
    "RevenueSnapshot",
    "SnapshotError",
    "TargetSnapshot",
    "account_fingerprint",
    "load_snapshot",
    "migrate_connection",
    "read_target",
    "snapshot_summary",
    "snapshots_match",
    "verify_connection",
]
