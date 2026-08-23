"""Tenant-bound storage for guarded mutation evidence.

A mutation is a state change, so the record of it has to be a row somebody can
go and look at — not a value this process remembers and reports back to itself.
Three rules follow from that, and they are the whole point of this module:

1. Every row is bound to a `tenant_id`. There is no shared or anonymous row, and
   the tenant is the authenticated revenue account, not a caller-supplied label.
2. `(tenant_id, idempotency_key)` is unique in the database, so a retry can never
   produce a second mutation record even if two workers race.
3. The insert and the read-back happen inside one transaction, and what the
   endpoint returns is the row that was read back — never the payload that was
   sent in. If the row and the request disagree, the row wins.

Reusing an idempotency key for a *different* action is refused rather than
quietly served from cache: the same key with a new `action_hash` means the caller
believes it is retrying something it is not.

The PostgreSQL backend is selected by the same `DSG_REVENUE_DATABASE_URL` that
selects the PostgreSQL revenue stores, so `tenant_id` can carry a real foreign
key to `dsg_revenue_accounts`. Without that variable the store is process memory,
which is honest for local runs and is reported as `durable: false` by
`/api/v1/status` — a memory-backed store forgets idempotency across a restart, so
paid enforcement refuses to run on it.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from typing import Any, Optional

from revenue.postgres import connect, initialize_schema, validate_database_url

from .canonical import canonical_hash, utc_now

TABLE = "dsg_guarded_evidence"

GUARDED_EVIDENCE_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    evidence_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES dsg_revenue_accounts(account_id),
    idempotency_key TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    label TEXT NOT NULL CHECK (char_length(label) >= 1 AND char_length(label) <= 200),
    plan_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    agent_identity TEXT NOT NULL,
    channel TEXT NOT NULL,
    step_id TEXT,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    parameters TEXT NOT NULL DEFAULT '{{}}',
    decision TEXT NOT NULL,
    control_hash TEXT NOT NULL,
    mutation_status TEXT NOT NULL,
    outputs TEXT NOT NULL DEFAULT '{{}}',
    output_sha256 TEXT,
    started_at TEXT,
    finished_at TEXT,
    evidence_hash TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS {TABLE}_tenant_created_idx
    ON {TABLE} (tenant_id, created_at DESC);
DO $$
BEGIN
    -- Deny-by-default for Supabase's anon/authenticated roles. Guarded evidence is
    -- reachable only through the server-side role this service connects with.
    IF NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = '{TABLE}' AND relrowsecurity
    ) THEN
        EXECUTE 'ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY';
    END IF;
END $$;
""".strip()

#: Columns written and read back, in one order both directions use.
COLUMNS = (
    "evidence_id",
    "tenant_id",
    "idempotency_key",
    "action_hash",
    "label",
    "plan_id",
    "plan_hash",
    "agent_identity",
    "channel",
    "step_id",
    "action",
    "target",
    "parameters",
    "decision",
    "control_hash",
    "mutation_status",
    "outputs",
    "output_sha256",
    "started_at",
    "finished_at",
    "evidence_hash",
    "recorded_at",
)

#: Fields the evidence hash is computed over. `evidence_hash` itself is excluded,
#: which is what makes the digest reproducible from a row read back later.
_HASHED = tuple(name for name in COLUMNS if name != "evidence_hash")

#: Held as canonical JSON *text*, not JSONB. JSONB normalises numbers on the way
#: back out (1e16 returns as an integer), which would make a correctly written row
#: fail its own digest check. Exactness matters more here than queryability.
_JSON_COLUMNS = ("parameters", "outputs")


class IdempotencyConflict(Exception):
    """The stored row for this key describes a different action than the retry."""

    def __init__(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        stored_action_hash: str,
        submitted_action_hash: str,
        stored_evidence_id: str,
    ) -> None:
        super().__init__(
            f"idempotency key '{idempotency_key}' is already bound to action "
            f"{stored_action_hash}, not {submitted_action_hash}"
        )
        self.tenant_id = tenant_id
        self.idempotency_key = idempotency_key
        self.stored_action_hash = stored_action_hash
        self.submitted_action_hash = submitted_action_hash
        self.stored_evidence_id = stored_evidence_id


class GuardedEvidenceLost(RuntimeError):
    """The row was not readable inside the transaction that wrote it."""


def evidence_hash(record: dict[str, Any]) -> str:
    """DSG's digest over the stored evidence body, recomputable from any read-back."""
    return canonical_hash({name: record[name] for name in _HASHED})


def label_for(action: str, target: str) -> str:
    """A short human-readable name for the row, kept inside the column's bound."""
    return f"{action} {target}"[:200]


def build_record(
    *,
    tenant_id: str,
    idempotency_key: str,
    action_hash: str,
    plan_id: str,
    plan_hash: str,
    agent_identity: str,
    channel: str,
    step_id: Optional[str],
    action: str,
    target: str,
    parameters: dict[str, Any],
    decision: str,
    control_hash: str,
    mutation_status: str,
    outputs: dict[str, Any],
    output_sha256: Optional[str] = None,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    evidence_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the row DSG intends to write, including its own digest."""
    record: dict[str, Any] = {
        "evidence_id": evidence_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "idempotency_key": idempotency_key,
        "action_hash": action_hash,
        "label": label_for(action, target),
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "agent_identity": agent_identity,
        "channel": channel,
        "step_id": step_id,
        "action": action,
        "target": target,
        "parameters": dict(parameters),
        "decision": decision,
        "control_hash": control_hash,
        "mutation_status": mutation_status,
        "outputs": dict(outputs),
        "output_sha256": output_sha256,
        "started_at": started_at,
        "finished_at": finished_at,
        "recorded_at": recorded_at or utc_now(),
    }
    record["evidence_hash"] = evidence_hash(record)
    return record


def _normalize(row: tuple) -> dict[str, Any]:
    record = dict(zip(COLUMNS, row, strict=True))
    # A UUID column reads back as a uuid.UUID, which canonical JSON cannot encode.
    record["evidence_id"] = str(record["evidence_id"])
    for name in _JSON_COLUMNS:
        value = record[name]
        record[name] = json.loads(value) if isinstance(value, str) else dict(value or {})
    return record


class MemoryGuardedEvidenceStore:
    """Process-local store with the same uniqueness and read-back semantics.

    Not durable: a restart forgets every idempotency key it has seen. That is
    stated in `summary()` rather than hidden, and enforced deployments refuse it.
    """

    backend = "memory"
    durable = False

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._by_id: dict[str, tuple[str, str]] = {}

    def record(self, candidate: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        key = (candidate["tenant_id"], candidate["idempotency_key"])
        with self._lock:
            created = key not in self._rows
            if created:
                stored = copy.deepcopy(candidate)
                self._rows[key] = stored
                self._by_id[stored["evidence_id"]] = key
            observed = copy.deepcopy(self._rows[key])
        if observed["action_hash"] != candidate["action_hash"]:
            raise IdempotencyConflict(
                tenant_id=candidate["tenant_id"],
                idempotency_key=candidate["idempotency_key"],
                stored_action_hash=observed["action_hash"],
                submitted_action_hash=candidate["action_hash"],
                stored_evidence_id=observed["evidence_id"],
            )
        return observed, created

    def get(self, tenant_id: str, evidence_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            key = self._by_id.get(evidence_id)
            if key is None or key[0] != tenant_id:
                return None
            return copy.deepcopy(self._rows[key])

    def count(self, tenant_id: Optional[str] = None) -> int:
        with self._lock:
            if tenant_id is None:
                return len(self._rows)
            return sum(1 for holder, _ in self._rows if holder == tenant_id)

    def summary(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "table": None,
            "durable": self.durable,
            "tenant_bound": True,
            "unique_on": ["tenant_id", "idempotency_key"],
            "read_back_in_write_transaction": True,
            "rows": self.count(),
        }


class PostgresGuardedEvidenceStore:
    """Guarded evidence in PostgreSQL/Supabase: one transaction, insert then read back."""

    backend = "postgres"
    durable = True

    def __init__(self, database_url: str) -> None:
        self._database_url = validate_database_url(database_url)
        self._schema_ready = False

    def _connection(self):
        connection = connect(self._database_url)
        if not self._schema_ready:
            # Bootstrap once per store, not once per statement: the DDL is idempotent
            # but ALTER/CREATE take heavy locks, and a hot path should not re-take them.
            # The revenue schema owns dsg_revenue_accounts, which tenant_id references.
            initialize_schema(connection)
            initialize_guarded_schema(connection)
            self._schema_ready = True
        return connection

    def record(self, candidate: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        names = ", ".join(COLUMNS)
        placeholders = ", ".join(["%s"] * len(COLUMNS))
        values = tuple(
            json.dumps(candidate[name], sort_keys=True, separators=(",", ":"))
            if name in _JSON_COLUMNS
            else candidate[name]
            for name in COLUMNS
        )
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {TABLE} ({names}) VALUES ({placeholders}) "
                "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING",
                values,
            )
            created = cursor.rowcount == 1
            # Same transaction, same connection: the endpoint answers with the row
            # the database holds, not with the payload it was handed.
            row = None
            for _ in range(2):
                # Read committed: each statement takes a fresh snapshot, so a second
                # look sees a row a concurrent writer committed a moment ago.
                cursor.execute(
                    f"SELECT {names} FROM {TABLE} WHERE tenant_id = %s AND idempotency_key = %s",
                    (candidate["tenant_id"], candidate["idempotency_key"]),
                )
                row = cursor.fetchone()
                if row is not None:
                    break
            if row is None:
                connection.rollback()
                raise GuardedEvidenceLost(
                    "guarded evidence was not readable in the transaction that wrote it"
                )
            observed = _normalize(row)
            if observed["action_hash"] != candidate["action_hash"]:
                connection.rollback()
                raise IdempotencyConflict(
                    tenant_id=candidate["tenant_id"],
                    idempotency_key=candidate["idempotency_key"],
                    stored_action_hash=observed["action_hash"],
                    submitted_action_hash=candidate["action_hash"],
                    stored_evidence_id=observed["evidence_id"],
                )
            connection.commit()
        return observed, created

    def get(self, tenant_id: str, evidence_id: str) -> Optional[dict[str, Any]]:
        try:
            # evidence_id is a uuid column, so anything else is not a row that
            # exists — asking the database would only raise a type error.
            uuid.UUID(evidence_id)
        except (ValueError, AttributeError, TypeError):
            return None
        names = ", ".join(COLUMNS)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {names} FROM {TABLE} WHERE tenant_id = %s AND evidence_id = %s",
                (tenant_id, evidence_id),
            )
            row = cursor.fetchone()
        return _normalize(row) if row else None

    def count(self, tenant_id: Optional[str] = None) -> int:
        with self._connection() as connection, connection.cursor() as cursor:
            if tenant_id is None:
                cursor.execute(f"SELECT COUNT(*) FROM {TABLE}")
            else:
                cursor.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE tenant_id = %s", (tenant_id,))
            return int(cursor.fetchone()[0])

    def summary(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "table": TABLE,
            "durable": self.durable,
            "tenant_bound": True,
            "unique_on": ["tenant_id", "idempotency_key"],
            "read_back_in_write_transaction": True,
        }


def initialize_guarded_schema(connection) -> None:
    """Create the guarded evidence table under its own advisory lock."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (0x44534745,))
        cursor.execute(GUARDED_EVIDENCE_SCHEMA_SQL)
    connection.commit()


_store: Optional[Any] = None
_store_lock = threading.Lock()


def build_guarded_store(env: Optional[dict] = None) -> Any:
    source = env if env is not None else os.environ
    database_url = (source.get("DSG_REVENUE_DATABASE_URL") or "").strip()
    if database_url:
        return PostgresGuardedEvidenceStore(database_url)
    return MemoryGuardedEvidenceStore()


def get_guarded_store() -> Any:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = build_guarded_store()
    return _store


def reset_guarded_store(store: Optional[Any] = None) -> Any:
    """Replace the process store. Used by tests and explicit reconfiguration."""
    global _store
    _store = store if store is not None else build_guarded_store()
    return _store


__all__ = [
    "COLUMNS",
    "GUARDED_EVIDENCE_SCHEMA_SQL",
    "GuardedEvidenceLost",
    "IdempotencyConflict",
    "MemoryGuardedEvidenceStore",
    "PostgresGuardedEvidenceStore",
    "TABLE",
    "build_guarded_store",
    "build_record",
    "evidence_hash",
    "get_guarded_store",
    "initialize_guarded_schema",
    "reset_guarded_store",
]
