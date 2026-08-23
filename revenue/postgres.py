"""PostgreSQL/Supabase connection validation and schema bootstrap.

This module deliberately has no HTTP or service-role-key dependency. Revenue
workers connect with a server-side PostgreSQL URI only, so Supabase RLS and Edge
Functions remain separate application boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from revenue.accounts import Account


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dsg_revenue_schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dsg_revenue_accounts (
    account_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    plan TEXT NOT NULL,
    status TEXT NOT NULL,
    channel TEXT NOT NULL,
    key_id TEXT UNIQUE NOT NULL,
    secret_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    payment_linked BOOLEAN NOT NULL DEFAULT FALSE,
    stripe_paid_amounts_micros JSONB NOT NULL DEFAULT '{}'::jsonb,
    stripe_paid_invoice_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    stripe_processed_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    stripe_field_event_created JSONB NOT NULL DEFAULT '{}'::jsonb,
    activation_ref TEXT,
    unit_price_micros BIGINT,
    hard_cap_units BIGINT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS dsg_revenue_ledger_entries (
    sequence BIGINT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES dsg_revenue_accounts(account_id),
    channel TEXT NOT NULL,
    sku TEXT NOT NULL,
    period TEXT NOT NULL,
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    units_before BIGINT NOT NULL CHECK (units_before >= 0),
    unit_price_micros BIGINT NOT NULL CHECK (unit_price_micros >= 0),
    amount_micros BIGINT NOT NULL CHECK (amount_micros >= 0),
    context_hash TEXT NOT NULL,
    proof_hash TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    previous_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS dsg_revenue_ledger_account_period_idx
    ON dsg_revenue_ledger_entries (account_id, period);
""".strip()

_ACCOUNT_COLUMNS = (
    "account_id, display_name, plan, status, channel, key_id, secret_hash, mode, "
    "stripe_customer_id, stripe_subscription_id, payment_linked, "
    "stripe_paid_amounts_micros, stripe_paid_invoice_ids, "
    "stripe_processed_event_ids, stripe_field_event_created, activation_ref, "
    "unit_price_micros, hard_cap_units, created_at, updated_at"
)


def validate_database_url(value: str) -> str:
    """Validate a server-side Supabase/PostgreSQL URI without exposing it."""
    url = (value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("DSG_REVENUE_DATABASE_URL must be a PostgreSQL URI")
    query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
    if query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("DSG_REVENUE_DATABASE_URL must enforce TLS with sslmode=require")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise ValueError("DSG_REVENUE_DATABASE_URL must include host and database")
    if not parsed.username or parsed.password is None:
        raise ValueError("DSG_REVENUE_DATABASE_URL must include server-side credentials")
    return url


def connect(database_url: str):
    """Open a TLS-required PostgreSQL/Supabase connection without logging its URI."""
    validated = validate_database_url(database_url)
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - dependency installation contract
        raise RuntimeError("psycopg is required for PostgreSQL revenue storage") from error
    return psycopg.connect(validated, autocommit=False)


def initialize_schema(connection) -> None:
    """Apply the initial idempotent schema under a transaction advisory lock."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (0x4453474D,))
        cursor.execute(SCHEMA_SQL)
        cursor.execute("SELECT COALESCE(MAX(version), 0) FROM dsg_revenue_schema_migrations")
        current = int(cursor.fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError("database schema is newer than this DSG runtime")
        cursor.execute(
            "INSERT INTO dsg_revenue_schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING",
            (SCHEMA_VERSION,),
        )
    connection.commit()


def _iso(value: object) -> object:
    """Render a TIMESTAMPTZ read-back as the ISO-8601 string that was written.

    PostgreSQL hands back a `datetime`, but every hash this system publishes is
    computed over canonical JSON of the stored record. A `datetime` in that record
    is not merely a different type — it cannot be encoded at all, so a chain read
    back from the database could not be re-verified against its own entry hashes.
    """
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _account_values(account: Account) -> tuple:
    return (
        account.account_id,
        account.display_name,
        account.plan,
        account.status,
        account.channel,
        account.key_id,
        account.secret_hash,
        account.mode,
        account.stripe_customer_id,
        account.stripe_subscription_id,
        account.payment_linked,
        _json(account.stripe_paid_amounts_micros),
        _json(account.stripe_paid_invoice_ids),
        _json(account.stripe_processed_event_ids),
        _json(account.stripe_field_event_created),
        account.activation_ref,
        account.unit_price_micros,
        account.hard_cap_units,
        account.created_at,
        account.updated_at,
    )


def _account_from_row(row: tuple) -> Account:
    fields = _ACCOUNT_COLUMNS.split(", ")
    data = dict(zip(fields, row, strict=True))
    for name in (
        "stripe_paid_amounts_micros",
        "stripe_paid_invoice_ids",
        "stripe_processed_event_ids",
        "stripe_field_event_created",
    ):
        if isinstance(data[name], str):
            data[name] = json.loads(data[name])
    data["stripe_paid_amounts_micros"] = {
        str(key): int(value) for key, value in data["stripe_paid_amounts_micros"].items()
    }
    for name in ("created_at", "updated_at"):
        data[name] = _iso(data[name])
    return Account(**data)


class PostgresLedgerStore:
    """Proof-bound ledger with PostgreSQL row locks and idempotency uniqueness."""

    #: Read order for a ledger row. `_entry` depends on it, so both live together.
    _LEDGER_COLUMNS = (
        "sequence, period, account_id, channel, sku, quantity, units_before, "
        "unit_price_micros, amount_micros, proof_hash, context_hash, idempotency_key, "
        "recorded_at, previous_hash, entry_hash"
    )

    @staticmethod
    def _entry(row: tuple):
        """Build a LedgerEntry whose fields match what was hashed on write."""
        from revenue.ledger import LedgerEntry

        values = list(row)
        values[12] = _iso(values[12])  # recorded_at
        return LedgerEntry(*values)

    def __init__(self, database_url: str) -> None:
        self._database_url = validate_database_url(database_url)

    def _connection(self):
        connection = connect(self._database_url)
        initialize_schema(connection)
        return connection

    def _rows(self, where: str = "", params: tuple = (), order: str = "ORDER BY sequence"):
        columns = self._LEDGER_COLUMNS
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {columns} FROM dsg_revenue_ledger_entries {where} {order}", params)
            rows = cursor.fetchall()
        return [self._entry(row) for row in rows]

    def entries(self): return self._rows()
    def size(self) -> int: return len(self._rows())
    def head_hash(self) -> str:
        from revenue.ledger import GENESIS_HASH
        rows = self._rows(order="ORDER BY sequence DESC LIMIT 1")
        return rows[0].entry_hash if rows else GENESIS_HASH
    def units_used(self, account_id: str, period: str) -> int:
        return sum(item.quantity for item in self.period_entries(account_id, period))
    def period_entries(self, account_id: str, period: str):
        return self._rows("WHERE account_id = %s AND period = %s", (account_id, period))
    def find_by_idempotency_key(self, key: str):
        rows = self._rows("WHERE idempotency_key = %s", (key,))
        return rows[0] if rows else None
    def find_account_entry(self, account_id: str, sequence: int):
        rows = self._rows("WHERE account_id = %s AND sequence = %s", (account_id, sequence))
        return rows[0] if rows else None
    def account_entries_before(self, account_id: str, *, before_sequence=None, limit: int = 20):
        if limit < 1: return []
        where = "WHERE account_id = %s"
        params: tuple = (account_id,)
        if before_sequence is not None:
            where += " AND sequence < %s"
            params += (before_sequence,)
        return self._rows(where, params, f"ORDER BY sequence DESC LIMIT {int(limit)}")

    def append_metered(
        self,
        *,
        account_id: str,
        channel: str,
        sku: str,
        quantity: int,
        unit_price_micros: int,
        included_units: int,
        hard_cap_units: int | None,
        proof_hash: str,
        context_hash: str,
        idempotency_key: str,
        period: str,
        recorded_at: str | None = None,
    ):
        """Serialize same-account writes and atomically enforce cap + idempotency."""
        from revenue.ledger import (
            GENESIS_HASH,
            LedgerEntry,
            QuotaExceededError,
            compute_entry_hash,
            utc_now,
        )

        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        recorded = recorded_at or utc_now()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (0x445347,))
            cursor.execute(
                f"SELECT {self._LEDGER_COLUMNS} FROM dsg_revenue_ledger_entries "
                "WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            duplicate = cursor.fetchone()
            if duplicate:
                connection.rollback()
                return self._entry(duplicate), False

            cursor.execute(
                "SELECT account_id FROM dsg_revenue_accounts WHERE account_id = %s FOR UPDATE",
                (account_id,),
            )
            if cursor.fetchone() is None:
                raise ValueError("unknown revenue account")
            cursor.execute(
                "SELECT COALESCE(SUM(quantity), 0) FROM dsg_revenue_ledger_entries "
                "WHERE account_id = %s AND period = %s",
                (account_id, period),
            )
            units_before = int(cursor.fetchone()[0])
            if hard_cap_units is not None and units_before + quantity > hard_cap_units:
                raise QuotaExceededError("plan quota was consumed by another request before metering")
            cursor.execute(
                "SELECT sequence, entry_hash FROM dsg_revenue_ledger_entries "
                "ORDER BY sequence DESC LIMIT 1 FOR UPDATE"
            )
            head = cursor.fetchone()
            sequence = int(head[0]) + 1 if head else 0
            previous_hash = head[1] if head else GENESIS_HASH
            billable_quantity = max(quantity - max(included_units - units_before, 0), 0)
            amount_micros = billable_quantity * unit_price_micros
            body = {
                "sequence": sequence,
                "period": period,
                "account_id": account_id,
                "channel": channel,
                "sku": sku,
                "quantity": quantity,
                "units_before": units_before,
                "unit_price_micros": unit_price_micros,
                "amount_micros": amount_micros,
                "proof_hash": proof_hash,
                "context_hash": context_hash,
                "idempotency_key": idempotency_key,
                "recorded_at": recorded,
                "prev_hash": previous_hash,
            }
            entry = LedgerEntry(**body, entry_hash=compute_entry_hash(body))
            cursor.execute(
                "INSERT INTO dsg_revenue_ledger_entries "
                "(sequence, account_id, channel, sku, period, quantity, units_before, unit_price_micros, "
                "amount_micros, context_hash, proof_hash, idempotency_key, previous_hash, "
                "entry_hash, recorded_at) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    sequence, account_id, channel, sku, period, quantity, units_before,
                    unit_price_micros, amount_micros, context_hash, proof_hash,
                    idempotency_key, previous_hash, entry.entry_hash, recorded,
                ),
            )
            connection.commit()
            return entry, True


class PostgresAccountStore:
    """Tenant account registry backed by Supabase/PostgreSQL transactions."""

    def __init__(self, database_url: str) -> None:
        self._database_url = validate_database_url(database_url)

    def _connection(self):
        connection = connect(self._database_url)
        initialize_schema(connection)
        return connection

    def import_account(self, account: Account) -> None:
        placeholders = ", ".join(["%s"] * 20)
        updates = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in _ACCOUNT_COLUMNS.split(", ")
            if column not in {"account_id", "created_at"}
        )
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO dsg_revenue_accounts ({_ACCOUNT_COLUMNS}) VALUES ({placeholders}) "
                f"ON CONFLICT (account_id) DO UPDATE SET {updates}",
                _account_values(account),
            )
            connection.commit()

    def get(self, account_id: str) -> Account | None:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts WHERE account_id = %s",
                (account_id,),
            )
            row = cursor.fetchone()
        return _account_from_row(row) if row else None

    def issue(self, *, display_name: str, plan: str = "free", channel: str = "api", mode: str = "live", stripe_customer_id=None, unit_price_micros=None, hard_cap_units=None, activation_ref=None):
        import secrets
        from revenue.accounts import Account, hash_secret
        from revenue.pricing import get_plan
        get_plan(plan)
        if mode not in {"live", "test"}: raise ValueError("mode must be live or test")
        key_id, secret = secrets.token_hex(8), secrets.token_hex(24)
        account = Account(account_id=f"acct_dsg_{secrets.token_hex(8)}", display_name=display_name, plan=plan, channel=channel, key_id=key_id, secret_hash=hash_secret(secret), mode=mode, stripe_customer_id=stripe_customer_id, unit_price_micros=unit_price_micros, hard_cap_units=hard_cap_units, activation_ref=activation_ref)
        self.import_account(account)
        return account, f"dsg_{mode}_{key_id}_{secret}"

    def all(self) -> list[Account]:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts ORDER BY account_id")
            rows = cursor.fetchall()
        return [_account_from_row(row) for row in rows]

    def find_by_stripe_customer(self, customer_id: str) -> Account | None:
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts WHERE stripe_customer_id = %s",
                (customer_id,),
            )
            row = cursor.fetchone()
        return _account_from_row(row) if row else None

    def update(self, account_id: str, **changes) -> Account:
        allowed = {
            "plan", "status", "display_name", "stripe_customer_id",
            "stripe_subscription_id", "payment_linked", "stripe_paid_amounts_micros",
            "stripe_paid_invoice_ids", "stripe_processed_event_ids",
            "stripe_field_event_created", "activation_ref", "unit_price_micros",
            "hard_cap_units", "channel", "updated_at",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported account fields: {sorted(unknown)}")
        current = self.get(account_id)
        if current is None:
            raise KeyError(account_id)
        data = current.to_dict()
        data.update(changes)
        updated = Account(**data)
        self.import_account(updated)
        return updated

    def apply_stripe_event(self, **kwargs):
        """Apply webhook idempotency/order changes while locking the account row."""
        customer_id = kwargs["customer_id"]
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts "
                "WHERE stripe_customer_id = %s FOR UPDATE",
                (customer_id,),
            )
            row = cursor.fetchone()
            if not row:
                connection.rollback(); return None, "unknown_customer"
            account = _account_from_row(row)
            event_id = kwargs["event_id"]
            if event_id in account.stripe_processed_event_ids:
                connection.rollback(); return account, "duplicate"
            invoice = kwargs.get("paid_invoice_id")
            if invoice and invoice in account.stripe_paid_invoice_ids:
                connection.rollback(); return account, "duplicate_invoice"
            subscription_id = kwargs["subscription_id"]
            if account.stripe_subscription_id and account.stripe_subscription_id != subscription_id:
                connection.rollback(); return account, "subscription_mismatch"
            if not account.stripe_subscription_id and not kwargs["allow_subscription_binding"]:
                connection.rollback(); return account, "subscription_not_bound"
            changes = dict(kwargs["changes"])
            if not account.stripe_subscription_id:
                changes.setdefault("stripe_subscription_id", subscription_id)
            paid = dict(account.stripe_paid_amounts_micros)
            period, amount = kwargs.get("paid_period"), kwargs.get("paid_amount_micros")
            if period and amount is not None:
                if amount < 0: raise ValueError("paid Stripe amount must not be negative")
                paid[period] = paid.get(period, 0) + amount
            changes.update(
                stripe_processed_event_ids=[*account.stripe_processed_event_ids, event_id],
                stripe_paid_invoice_ids=[*account.stripe_paid_invoice_ids, *([invoice] if invoice else [])],
                stripe_paid_amounts_micros=paid,
            )
            data = account.to_dict(); data.update(changes)
            updated = Account(**data)
            placeholders = ", ".join(["%s"] * 20)
            updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _ACCOUNT_COLUMNS.split(", ") if c not in {"account_id", "created_at"})
            cursor.execute(f"INSERT INTO dsg_revenue_accounts ({_ACCOUNT_COLUMNS}) VALUES ({placeholders}) ON CONFLICT (account_id) DO UPDATE SET {updates}", _account_values(updated))
            connection.commit(); return updated, "applied"

    def authenticate(self, api_key: str) -> Account | None:
        from revenue.accounts import KEY_PATTERN, hash_secret
        import hmac

        match = KEY_PATTERN.match((api_key or "").strip())
        if not match:
            return None
        mode, key_id, secret = match.groups()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_ACCOUNT_COLUMNS} FROM dsg_revenue_accounts WHERE key_id = %s",
                (key_id,),
            )
            row = cursor.fetchone()
        account = _account_from_row(row) if row else None
        if account is None or account.mode != mode:
            return None
        return account if hmac.compare_digest(account.secret_hash, hash_secret(secret)) else None
