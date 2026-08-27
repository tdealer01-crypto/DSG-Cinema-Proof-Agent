#!/usr/bin/env python3
"""Summarize, migrate, or verify a frozen revenue file snapshot."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from revenue.migration import (  # noqa: E402
    MigrationError,
    SnapshotError,
    load_snapshot,
    migrate_connection,
    read_target,
    snapshot_summary,
    verify_connection,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("summarize", "apply", "verify"):
        command = subcommands.add_parser(name)
        command.add_argument("--accounts", required=True, help="frozen accounts.json snapshot")
        command.add_argument("--ledger", required=True, help="frozen ledger.json snapshot")
        if name == "apply":
            command.add_argument("--archive-divergent-target", action="store_true")
            command.add_argument("--archive-id")
            command.add_argument("--confirmation")
    subcommands.add_parser(
        "inspect", help="verify and summarize the current PostgreSQL chain"
    )
    return parser


def _database_url() -> str:
    value = (os.getenv("DSG_REVENUE_DATABASE_URL") or "").strip()
    if not value:
        raise MigrationError("DSG_REVENUE_DATABASE_URL is not set; refusing to guess a database")
    return value


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = (
            None
            if args.command == "inspect"
            else load_snapshot(args.accounts, args.ledger)
        )
        if args.command == "summarize":
            assert source is not None
            result = {"verified": True, "source": snapshot_summary(source)}
        else:
            from api_v1.guarded_store import initialize_guarded_schema
            from revenue.postgres import connect, initialize_schema

            with connect(_database_url()) as connection:
                initialize_schema(connection)
                initialize_guarded_schema(connection)
                if args.command == "inspect":
                    result = {
                        "verified": True,
                        "target": snapshot_summary(read_target(connection)),
                    }
                elif args.command == "apply":
                    assert source is not None
                    result = migrate_connection(
                        connection,
                        source,
                        archive_divergent_target=args.archive_divergent_target,
                        archive_id=args.archive_id,
                        confirmation=args.confirmation,
                    )
                else:
                    assert source is not None
                    result = verify_connection(connection, source)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (MigrationError, SnapshotError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception:  # Keep connection strings out of runner output.
        print(
            f"FAIL: {type(exc).__name__} during revenue migration; database URI not printed",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
