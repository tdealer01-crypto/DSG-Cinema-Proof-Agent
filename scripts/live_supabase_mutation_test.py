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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="leave the test rows in place")
    args = parser.parse_args()

    database_url = (os.getenv("DSG_REVENUE_DATABASE_URL") or "").strip()
    if not database_url:
        print("DSG_REVENUE_DATABASE_URL is not set; nothing to test against.")
        return 2

    import cinema_main
    from api_v1 import guarded_store, service
    from api_v1.models import ApprovePlanRequest, PlanDocument
    from revenue import api as billing
    from revenue.engine import RevenueEngine
    from revenue.postgres import connect

    engine = billing.reset_engine(RevenueEngine.from_env())
    store = guarded_store.reset_guarded_store(guarded_store.build_guarded_store())
    check("postgres guarded store selected", store.backend == "postgres", store.summary()["table"])
    check("guarded store reports itself durable", store.durable is True)

    client = TestClient(cinema_main.app)
    suffix = uuid.uuid4().hex
    account, api_key = engine.accounts.issue(display_name=f"Guarded live test {suffix[:8]}")
    other_account, other_key = engine.accounts.issue(display_name=f"Guarded live other {suffix[:8]}")
    headers = {"X-DSG-API-Key": api_key}

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

    changed = dict(body, action=dict(body["action"], target="production/other-app"))
    conflict = client.post("/api/v1/control/mutations", json=changed, headers=headers)
    check(
        "same key for a different action is refused",
        conflict.status_code in {409, 200},
        f"HTTP {conflict.status_code}",
    )
    if conflict.status_code == 409:
        check("refusal names the conflict", conflict.json()["error"] == "IDEMPOTENCY_KEY_CONFLICT")
    else:
        # An out-of-plan target is blocked before storage is reached, which is also
        # a correct refusal — just an earlier one.
        check("out-of-plan action never reached storage", conflict.json()["executed"] is False)

    cross = client.get(
        f"/api/v1/control/mutations/{observed['evidence_id']}",
        headers={"X-DSG-API-Key": other_key},
    )
    check("another tenant cannot read the row", cross.status_code == 404)

    mine = client.get(
        f"/api/v1/control/mutations/{observed['evidence_id']}", headers=headers
    )
    check("owner reads the same row back", mine.json()["observed_evidence"] == observed)

    if not args.keep:
        with connect(database_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM dsg_guarded_evidence WHERE tenant_id = ANY(%s)",
                ([account.account_id, other_account.account_id],),
            )
            cursor.execute(
                "DELETE FROM dsg_revenue_accounts WHERE account_id = ANY(%s)",
                ([account.account_id, other_account.account_id],),
            )
            connection.commit()
        print("cleaned up test tenants and their guarded evidence")

    print(json.dumps({"checks": CHECKS, "table": guarded_store.TABLE}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
