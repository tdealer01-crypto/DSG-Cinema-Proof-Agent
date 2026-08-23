#!/usr/bin/env python3
"""Run the guarded mutation flow against a live Supabase/PostgreSQL database.

The unit suite proves the semantics against fakes. This proves them against a
real database: the unique constraint, the foreign key, the single-transaction
read-back, and the refusal to answer a reused idempotency key with the wrong row.

Usage:

    export DSG_REVENUE_DATABASE_URL='postgresql://user:pass@host:5432/postgres?sslmode=require'
    python scripts/live_supabase_mutation_test.py

The script creates one throwaway tenant and its guarded evidence rows, then
deletes them again unless `--keep` is passed. It exits non-zero on the first
check that does not hold, and prints a JSON evidence block on success.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

CHECKS: list[dict] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append({"check": name, "pass": bool(condition), "detail": detail})
    marker = "PASS" if condition else "FAIL"
    print(f"[{marker}] {name}{(' - ' + detail) if detail else ''}")
    if not condition:
        raise SystemExit(f"live guarded mutation test failed at: {name}")


def run_checks(client, engine, store, database_url: str, account, other_account, api_key, other_key, suffix) -> dict:
    """Every check. Raises SystemExit on the first one that does not hold."""
    from api_v1 import service
    from api_v1.models import ApprovePlanRequest, PlanDocument
    from revenue.postgres import connect

    headers = {"X-DSG-API-Key": api_key}
    check("postgres guarded store selected", store.backend == "postgres", store.summary()["table"])
    check("guarded store reports itself durable", store.durable is True)

    created_plan = service.create_plan(
        PlanDocument.model_validate(
            {
                "title": "Live Supabase guarded mutation",
                "agent_identity": "dsg-executor",
                "channel": "api",
                "steps": [
                    {
                        "step_id": "deploy",
                        "action": "deploy_product",
                        "target": "production/app",
                        "parameters": {"environment": "production"},
                    }
                ],
            }
        )
    )
    plan = service.approve_plan(
        created_plan["plan_id"],
        ApprovePlanRequest(approver="live-test", plan_hash=created_plan["plan_hash"]),
    )

    key = f"live-guarded-{suffix}"
    body = {
        "plan_id": plan["plan_id"],
        "agent_identity": "dsg-executor",
        "idempotency_key": key,
        "action": {
            "step_id": "deploy",
            "action": "deploy_product",
            "target": "production/app",
            "parameters": {"environment": "production"},
            "status": "succeeded",
        },
        "outputs": {"revision": "live-1"},
    }

    first = client.post("/api/v1/control/mutations", json=body, headers=headers)
    check("mutation executed", first.status_code == 201, first.text)
    observed = first.json()["observed_evidence"]
    check("row is bound to the calling tenant", observed["tenant_id"] == account.account_id)
    check("read-back digest matches storage", first.json()["integrity"]["matches_stored"] is True)

    # Read the row with a connection this request never touched.
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT evidence_hash, action_hash, decision FROM dsg_guarded_evidence "
            "WHERE tenant_id = %s AND idempotency_key = %s",
            (account.account_id, key),
        )
        row = cursor.fetchone()
    check("row is visible to an independent connection", row is not None)
    check("committed digest matches the response", row[0] == observed["evidence_hash"])
    check("committed decision is ALLOW", row[2] == "ALLOW")

    replay = client.post("/api/v1/control/mutations", json=body, headers=headers)
    check("retry replays instead of writing again", replay.status_code == 200, replay.text)
    check("replayed row is identical", replay.json()["observed_evidence"] == observed)

    # Same key, same approved action, different declared output digest: the action
    # is unchanged, so this is a retry and must not become a second row.
    same_action = dict(body, outputs={"revision": "live-2"})
    again = client.post("/api/v1/control/mutations", json=same_action, headers=headers)
    check("a differing result does not fork the record", again.status_code == 200, again.text)
    check("stored outputs are not overwritten", again.json()["observed_evidence"] == observed)

    cross = client.get(
        f"/api/v1/control/mutations/{observed['evidence_id']}",
        headers={"X-DSG-API-Key": other_key},
    )
    check("another tenant cannot read the row", cross.status_code == 404)

    unknown = client.get("/api/v1/control/mutations/not-a-uuid", headers=headers)
    check("a malformed id is a refusal, not a database error", unknown.status_code == 404)

    mine = client.get(f"/api/v1/control/mutations/{observed['evidence_id']}", headers=headers)
    check("owner reads the same row back", mine.json()["observed_evidence"] == observed)

    # The other tenant may hold the very same idempotency key.
    other_body = dict(body)
    other = client.post(
        "/api/v1/control/mutations", json=other_body, headers={"X-DSG-API-Key": other_key}
    )
    check("a second tenant may reuse the key", other.status_code == 201, other.text)
    check(
        "the two rows are distinct",
        other.json()["observed_evidence"]["evidence_id"] != observed["evidence_id"],
    )
    return observed


def cleanup(database_url: str, account_ids: list[str]) -> None:
    from revenue.postgres import connect

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM dsg_guarded_evidence WHERE tenant_id = ANY(%s)", (account_ids,)
        )
        cursor.execute(
            "DELETE FROM dsg_revenue_accounts WHERE account_id = ANY(%s)", (account_ids,)
        )
        connection.commit()
    print("cleaned up test tenants and their guarded evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="leave the test rows in place")
    args = parser.parse_args()

    database_url = (os.getenv("DSG_REVENUE_DATABASE_URL") or "").strip()
    if not database_url:
        print("DSG_REVENUE_DATABASE_URL is not set; nothing to test against.")
        return 2

    import cinema_main
    from api_v1 import guarded_store
    from revenue import api as billing
    from revenue.engine import RevenueEngine

    engine = billing.reset_engine(RevenueEngine.from_env())
    store = guarded_store.reset_guarded_store(guarded_store.build_guarded_store())
    client = TestClient(cinema_main.app)

    suffix = uuid.uuid4().hex
    account, api_key = engine.accounts.issue(display_name=f"Guarded live test {suffix[:8]}")
    other_account, other_key = engine.accounts.issue(display_name=f"Guarded live other {suffix[:8]}")
    tenants = [account.account_id, other_account.account_id]

    try:
        run_checks(client, engine, store, database_url, account, other_account, api_key, other_key, suffix)
    finally:
        # A failed run leaves the most rows behind, so cleanup must not depend on
        # every check having passed.
        if not args.keep:
            cleanup(database_url, tenants)

    print(json.dumps({"checks": CHECKS, "table": guarded_store.TABLE}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
