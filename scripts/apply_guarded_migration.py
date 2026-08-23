#!/usr/bin/env python3
"""Bring a live database to the guarded evidence schema this runtime writes.

Order matters and is the whole point of the script:

1. The application's own bootstrap runs first, so a database that has never seen
   this feature gets the final shape directly and needs no migration at all.
2. `scripts/sql/0002_extend_dsg_guarded_evidence.sql` runs second, for databases
   that already carry the earlier skeleton. It is idempotent, so running it
   against a database already in the final shape changes nothing.

The connection URI is read from `DSG_REVENUE_DATABASE_URL` and never printed —
`revenue.postgres.connect` validates it without echoing it, and what this script
reports is the resulting schema, not the credential that reached it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIGRATION = ROOT / "scripts" / "sql" / "0002_extend_dsg_guarded_evidence.sql"


def main() -> int:
    database_url = (os.getenv("DSG_REVENUE_DATABASE_URL") or "").strip()
    if not database_url:
        print("DSG_REVENUE_DATABASE_URL is not set; refusing to guess a database.")
        return 2

    from api_v1.guarded_store import TABLE, initialize_guarded_schema
    from revenue.postgres import connect, initialize_schema

    with connect(database_url) as connection:
        initialize_schema(connection)
        print("revenue schema bootstrapped")
        initialize_guarded_schema(connection)
        print(f"{TABLE} bootstrapped")

        with connection.cursor() as cursor:
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.commit()
        print(f"applied {MIGRATION.relative_to(ROOT)}")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = %s ORDER BY ordinal_position",
                (TABLE,),
            )
            columns = cursor.fetchall()
            cursor.execute(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = %s "
                "ORDER BY c.conname",
                (TABLE,),
            )
            constraints = [row[0] for row in cursor.fetchall()]
            cursor.execute(f"SELECT count(*) FROM {TABLE}")
            rows = int(cursor.fetchone()[0])

    print(f"\n{TABLE}: {len(columns)} columns, {rows} rows")
    for name, kind in columns:
        print(f"  {name:<18} {kind}")
    print("\nconstraints:")
    for definition in constraints:
        print(f"  {definition}")

    expected = {"tenant_id", "idempotency_key", "action_hash", "evidence_hash", "recorded_at"}
    present = {name for name, _ in columns}
    missing = sorted(expected - present)
    if missing:
        print(f"\nFAIL: the guarded evidence table is missing {missing}")
        return 1
    payload_types = {name: kind for name, kind in columns if name in {"parameters", "outputs"}}
    if set(payload_types.values()) != {"text"}:
        # JSONB normalises numbers on read-back, so a row could fail its own digest.
        print(f"\nFAIL: parameters/outputs must be text, found {payload_types}")
        return 1
    if not any("UNIQUE (tenant_id, idempotency_key)" in item for item in constraints):
        print("\nFAIL: (tenant_id, idempotency_key) is not unique")
        return 1

    print("\nOK: schema matches what this runtime writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
